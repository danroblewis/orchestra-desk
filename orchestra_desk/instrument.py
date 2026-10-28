"""The instrument ``desk.conditions``: ``python -m orchestra_desk measure``, which ``orchestra run``
runs every ``[desk] every`` (``Plugin.collectors``). One round checks every condition, folds the
outcomes into the record, adds a ledger entry for each change, and prints the conditions' state in
the Prometheus text format, which ``orchestra run`` stores labelled ``instrument=desk.conditions``.
The Desk never writes the metrics store itself.

- ``desk_condition_holds{condition}``: 1 when it holds, 0 when it does not (left out while unknown);
- ``desk_condition_false_seconds{condition}``: how long it has been false, 0 when it holds (left
  out while unknown);
- ``desk_conditions{state}``: how many conditions hold, are false, are unknown.

A condition is a measurement like any other: discovery may read a 0/1 level as a flag. Severity,
statements and reasons are the board's, never labels or values here."""

from __future__ import annotations

import sys
import time

from orchestra.config import ConfigError, load_project
from orchestra.metrics import for_project

from . import record as R
from .conditions import FALSE, HOLDS, UNKNOWN, check_all
from .config import Settings, settings
from .ledger import Ledger


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def text(rec: dict, s: Settings, now: float) -> str:
    conds = rec.get("conditions", {})
    lines = ["# HELP desk_condition_holds Whether a standing condition holds (1) or not (0).",
             "# TYPE desk_condition_holds gauge"]
    known = [(n, conds[n]) for n in s.conditions if conds.get(n, {}).get("state") in (HOLDS, FALSE)]
    lines += [f'desk_condition_holds{{condition="{_esc(n)}"}} {1 if c["state"] == HOLDS else 0}' for n, c in known]
    lines += ["# HELP desk_condition_false_seconds How long a standing condition has been false; 0 when it holds.",
              "# TYPE desk_condition_false_seconds gauge"]
    for n, c in known:
        age = max(now - c["false_since"], 0.0) if c["state"] == FALSE and c.get("false_since") else 0.0
        lines.append(f'desk_condition_false_seconds{{condition="{_esc(n)}"}} {age:g}')
    lines += ["# HELP desk_conditions Standing conditions by state.", "# TYPE desk_conditions gauge"]
    for state in (HOLDS, FALSE, UNKNOWN):
        n = sum(1 for name in s.conditions if conds.get(name, {}).get("state", UNKNOWN) == state)
        lines.append(f'desk_conditions{{state="{state}"}} {n}')
    return "\n".join(lines) + "\n"


def measure(project, now: float | None = None) -> str:
    """One round: check, record, note the changes in the ledger; the exposition text."""
    now = time.time() if now is None else now
    s = settings(project.config.raw)
    store = for_project(project)
    try:
        outcomes = check_all(s, store, project.key, project.repo_root, now)
    finally:
        store.close()
    rec, changes = R.update(R.path_for(project.state_dir), outcomes, now)
    if changes:
        ledger = Ledger.for_project(project)
        try:
            ledger.record(changes)
        finally:
            ledger.close()
    return text(rec, s, now)


def main() -> int:
    project = load_project()                  # ORCHESTRA_REPO, which orchestra run sets for an instrument
    try:
        out = measure(project)
    except ConfigError as e:
        print(f"desk: [desk] is not usable: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0
