"""``orchestra-desk check``: validate a ``[desk]`` configuration before it is committed.

For the Supervisor's tools (and anyone editing by hand)::

    orchestra-desk check                      # the configuration of the repository here (overlay merged)
    orchestra-desk check --repo ~/work        # ... of that repository
    orchestra-desk check --file proposed.toml # a whole proposed configuration, not yet in place
    orchestra-desk check --file - --json      # read from stdin; answer in JSON

Exit 0 when the configuration is valid, 1 when it is not, 2 when it cannot be read. The JSON is
``{"ok": bool, "errors": [...], "warnings": [...], "conditions": {name: {check, severity, holds}},
"ledger": {type: kind}}``. Errors are what the Desk would refuse. Warnings are what would leave a
condition unknown later (a script that is not there or not executable, a series this project's
metrics store has never had); they do not fail the check, because the script or the series may
come after the configuration."""

from __future__ import annotations

import os
from pathlib import Path

from .config import Settings, problems
from .scripts import argv


def warnings(s: Settings, repo_root: Path, store=None, project_key: str | None = None) -> list[str]:
    out: list[str] = []
    for c in s.conditions.values():
        where = f'[desk.conditions."{c.name}"]'
        if c.check == "script":
            cmd = argv(c.command, repo_root)[0]
            if not os.path.isfile(cmd):
                out.append(f"{where} command {c.command[0]!r} is not a file (looked at {cmd}); "
                           "the condition is unknown until it is")
            elif not os.access(cmd, os.X_OK):
                out.append(f"{where} command {cmd} is not executable")
        elif store is not None:
            for var, r in c.readings.items():
                labels = {**dict(r.labels), "project": project_key} if project_key else dict(r.labels)
                if not any(n == r.series for n, _ in store.series(r.series, labels)):
                    what = "" if var == "value" else f" (vars.{var})"
                    out.append(f"{where} series {r.selector()}{what} is not in this project's metrics store yet")
    return out


def check(raw: dict, repo_root: Path, store=None, project_key: str | None = None) -> dict:
    s, errors = problems(raw)
    if s is None:
        return {"ok": False, "errors": errors, "warnings": [], "conditions": {}, "ledger": {}}
    return {"ok": True, "errors": [], "warnings": warnings(s, repo_root, store, project_key),
            "conditions": {c.name: {"check": c.check, "severity": c.severity,
                                    "holds": str(c.holds) if c.holds else None} for c in s.conditions.values()},
            "ledger": {t: r.kind for t, r in sorted(s.rules.items())}}
