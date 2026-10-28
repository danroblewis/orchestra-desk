"""Checking conditions: each one's readings from the metrics store, or its script, to an outcome
(holds, false or unknown) with its evidence. Pure of state: ``record.py`` keeps what was found
over time, and the instrument (``instrument.py``) is what runs this."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .config import Condition, Settings
from .language import LanguageError
from .readings import take
from .scripts import run

HOLDS, FALSE, UNKNOWN = "holds", "false", "unknown"


@dataclass(frozen=True)
class Outcome:
    name: str
    state: str                        # holds, false or unknown
    value: float | None = None        # the expression's value (series and expr checks)
    evidence: str = ""                # what was read, or why it is unknown
    reason: str | None = None         # a script's own words


def check_readings(c: Condition, store, project_key: str, now: float) -> Outcome:
    taken = {var: take(store, project_key, r, now) for var, r in c.readings.items()}
    evidence = "; ".join(t.evidence for t in taken.values())
    missing = [var for var, t in taken.items() if t.value is None]
    if missing:
        state = {"unknown": UNKNOWN, "holds": HOLDS, "false": FALSE}[c.when_missing]
        why = "" if state == UNKNOWN else f" (when_missing = {c.when_missing})"
        return Outcome(c.name, state, None, f"missing: {evidence}{why}")
    values = {var: t.value for var, t in taken.items()}
    try:
        value = c.expr(values) if c.expr else values["value"]
    except (ArithmeticError, LanguageError) as e:
        return Outcome(c.name, UNKNOWN, None, f"{c.expr.text}: {e}; {evidence}")
    shown = f"{c.expr.text} = {value:g} from {evidence}" if c.expr else evidence
    holds = c.holds(value)
    return Outcome(c.name, HOLDS if holds else FALSE, value, f"{shown}; holds when {c.holds}")


def check_script(c: Condition, repo_root: Path) -> Outcome:
    r = run(c, repo_root)
    if r.holds is None:
        return Outcome(c.name, UNKNOWN, None, f"{' '.join(c.command)}: {r.error}")
    return Outcome(c.name, HOLDS if r.holds else FALSE, None, " ".join(c.command), r.reason)


def check_all(s: Settings, store, project_key: str, repo_root: Path, now: float) -> dict[str, Outcome]:
    """Every configured condition's outcome; scripts run side by side, each under its timeout."""
    out: dict[str, Outcome] = {}
    scripts = [c for c in s.conditions.values() if c.check == "script"]
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(scripts)))) as pool:
        running = {c.name: pool.submit(check_script, c, repo_root) for c in scripts}
        for c in s.conditions.values():
            if c.check != "script":
                try:
                    out[c.name] = check_readings(c, store, project_key, now)
                except Exception as e:  # noqa: BLE001 - one condition's failure is that condition's unknown
                    out[c.name] = Outcome(c.name, UNKNOWN, None, f"could not read the metrics store: {type(e).__name__}: {e}")
        for name, f in running.items():
            out[name] = f.result()
    return {name: out[name] for name in s.conditions}
