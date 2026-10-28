"""The board: every configured condition with its last outcome, ranked for the owner.

False conditions come first, most severe first, and among equals the longest false first. Then the
unknown ones (a check that could not be made is a thing to fix), most severe first. Then those that
hold. A condition not checked yet is unknown, with that as its evidence."""

from __future__ import annotations

from urllib.parse import quote

from .conditions import FALSE, HOLDS, UNKNOWN
from .config import Condition, Settings

_ORDER = {FALSE: 0, UNKNOWN: 1, HOLDS: 2}


def evidence_link(c: Condition) -> str | None:
    """Where the evidence can be looked at: the readings in Orchestra's metrics query (24 hours)."""
    if c.check == "script" or not c.readings:
        return None
    r = next(iter(c.readings.values()))
    return f"/api/core/metrics/query?q={quote(r.selector())}&hours=24"


def item(c: Condition, rec: dict | None, now: float) -> dict:
    rec = rec or {}
    state = rec.get("state", UNKNOWN)
    false_since = rec.get("false_since")
    return {
        "name": c.name, "statement": c.statement, "severity": c.severity, "check": c.check,
        "state": state, "value": rec.get("value"),
        "evidence": rec.get("evidence") or "not checked yet: the instrument desk.conditions checks under orchestra run",
        "reason": rec.get("reason"),
        "false_for": now - false_since if false_since is not None and state == FALSE else None,
        "since": rec.get("since"), "checked_at": rec.get("checked_at"),
        "link": c.link, "evidence_link": evidence_link(c),
        "holds_when": str(c.holds) if c.holds else None,
        "command": list(c.command) or None,
    }


def ranked(s: Settings, record: dict, now: float) -> list[dict]:
    conds = record.get("conditions", {})
    items = [item(c, conds.get(name), now) for name, c in s.conditions.items()]
    rank = {name: c.rank for name, c in s.conditions.items()}
    return sorted(items, key=lambda i: (_ORDER[i["state"]], rank[i["name"]], -(i["false_for"] or 0), i["name"]))
