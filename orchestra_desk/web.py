"""The Desk's pages' API, at ``/api/plugins/desk``. Read only: nothing here changes the system.

- ``GET /board``: every condition, ranked (``board.py``), with when they were last checked;
- ``GET /ledger?period=day|week|all&at=YYYY-MM-DD&kind=landed,merged&mine=1``: the ledger's
  entries in that day or week (local time, weeks from Monday) containing ``at`` (default today),
  newest first, with the count of each kind. It first reads the bus up to now (``reader.py``).

The configuration is read again whenever it changed (``project.config_stamp()``), so an edit shows
on the next request."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException
from orchestra.config import ConfigError
from orchestra.events import Events

from . import record as R
from .board import ranked
from .config import Settings, section, settings
from .ledger import Ledger
from .reader import catch_up

PERIODS = ("day", "week", "all")


def window(period: str, at: str | None) -> tuple[float | None, float | None, str]:
    """``[start, end)`` in unix seconds of the local day or week holding ``at``, and its name."""
    if period not in PERIODS:
        raise HTTPException(400, f"period must be one of {', '.join(PERIODS)}")
    if period == "all":
        return None, None, "everything"
    try:
        day = date.fromisoformat(at) if at else date.today()
    except ValueError:
        raise HTTPException(400, "at must be a date, YYYY-MM-DD") from None
    if period == "week":
        day -= timedelta(days=day.weekday())
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1 if period == "day" else 7)
    name = day.isoformat() if period == "day" else f"week of {day.isoformat()}"
    return start.timestamp(), end.timestamp(), name


def router(project) -> APIRouter:
    r = APIRouter()
    cache: dict = {"stamp": None, "settings": None, "error": None}

    def current() -> tuple[Settings | None, str | None]:
        stamp = project.config_stamp()
        if stamp != cache["stamp"]:
            cache["stamp"] = stamp
            try:
                project.reload_config()
                if section(project.config.raw) is None:
                    cache["settings"], cache["error"] = None, None
                else:
                    cache["settings"], cache["error"] = settings(project.config.raw), None
            except (ConfigError, OSError, ValueError) as e:
                cache["settings"], cache["error"] = None, str(e)
        return cache["settings"], cache["error"]

    @r.get("/board")
    def board() -> dict:
        s, error = current()
        now = time.time()
        out = {"ok": True, "now": now, "configured": section(project.config.raw) is not None, "error": error,
               "conditions": [], "checked_at": None, "every": None}
        if s is None:
            return out
        rec = R.load(R.path_for(project.state_dir))
        items = ranked(s, rec, now)
        counts = {st: sum(1 for i in items if i["state"] == st) for st in ("false", "unknown", "holds")}
        return {**out, "conditions": items, "counts": counts, "checked_at": rec.get("checked_at"), "every": s.every}

    @r.get("/ledger")
    def ledger(period: str = "week", at: str | None = None, kind: str = "", mine: bool = False) -> dict:
        s, error = current()
        start, end, name = window(period, at)
        led = Ledger.for_project(project)
        events = Events.for_project(project)
        read_error = None
        try:
            if s is not None:
                try:
                    catch_up(events, led, s.rules)
                except Exception as e:  # noqa: BLE001 - show what the ledger has, and say the bus could not be read
                    read_error = f"{type(e).__name__}: {e}"
            kinds = [k for k in kind.split(",") if k]
            owner = s.owner if s else ()
            entries = [e.view(owner) for e in led.entries(start, end, kinds or None)]
            if mine:
                entries = [e for e in entries if e["mine"] or e["origin"] == "desk"]
            counts: dict[str, int] = {}
            for e in entries:
                counts[e["kind"]] = counts.get(e["kind"], 0) + 1
            return {"ok": True, "now": time.time(), "configured": section(project.config.raw) is not None,
                    "error": error, "read_error": read_error, "period": period, "name": name, "start": start,
                    "end": end, "owner": list(owner), "kinds": led.kinds(), "counts": counts, "entries": entries}
        finally:
            events.close()
            led.close()

    return r
