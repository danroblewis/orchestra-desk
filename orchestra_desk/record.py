"""What the instrument found, kept over time: ``<state>/desk/conditions.json``. For each condition,
its last outcome, since when it has been in that state, and since when it has been false (which
an unknown check in between does not reset: an outage of the readings is not a recovery).

A condition that turns false, or holds again after being false, is a change, returned as ledger
entries of kind ``condition``. These are the Desk's own entries: they are never put on the bus."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from . import STATE
from .conditions import FALSE, HOLDS, Outcome
from .ledger import Entry


def path_for(state_dir: Path) -> Path:
    return state_dir / STATE / "conditions.json"


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path.with_suffix(".lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def load(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("conditions"), dict) else {"conditions": {}}
    except (OSError, ValueError):
        return {"conditions": {}}


def _write(path: Path, d: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".conditions.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def change(name: str, state: str, now: float, false_for: float | None = None) -> Entry:
    label = f"{name} turned false" if state == FALSE else f"{name} holds again" + (
        f" after {false_for / 3600:.1f}h" if false_for else "")
    return Entry(f"desk:condition:{name}:{now:.3f}", now, "condition", f"desk.condition.{state}", None, name,
                 label, f"/desk#condition={quote(name)}", "desk")


def update(path: Path, outcomes: dict[str, Outcome], now: float) -> tuple[dict, list[Entry]]:
    """Fold the outcomes into the record; returns it and the changes. Conditions no longer
    configured are dropped."""
    with _locked(path):
        old = load(path)["conditions"]
        new: dict[str, dict] = {}
        changes: list[Entry] = []
        for name, o in outcomes.items():
            prev = old.get(name) or {}
            false_since = prev.get("false_since")
            if o.state == FALSE and false_since is None:
                false_since = now
                changes.append(change(name, FALSE, now))
            elif o.state == HOLDS and false_since is not None:
                changes.append(change(name, HOLDS, now, now - false_since))
                false_since = None
            new[name] = {"state": o.state, "value": o.value, "evidence": o.evidence, "reason": o.reason,
                         "since": prev.get("since", now) if prev.get("state") == o.state else now,
                         "false_since": false_since, "checked_at": now}
        record = {"checked_at": now, "conditions": new}
        _write(path, record)
    return record, changes
