"""``orchestra desk``: ``check`` a configuration; ``measure`` (the instrument ``desk.conditions``)
and ``read`` (the process ``desk.reader``), which ``orchestra run`` starts and nobody else needs to."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from orchestra.config import ConfigError, load_project
from orchestra.metrics import for_project

from .check import check


def _check(a) -> int:
    store = key = None
    try:
        if a.file == "-":
            raw = tomllib.loads(sys.stdin.read())
        elif a.file:
            raw = tomllib.loads(Path(a.file).read_text(encoding="utf-8"))
        else:
            project = load_project(a.repo)          # the configuration as Orchestra reads it, overlay merged
            raw, key = project.config.raw, project.key
            store = for_project(project)
    except (OSError, tomllib.TOMLDecodeError, ConfigError) as e:
        print(json.dumps({"ok": False, "errors": [f"cannot read it: {e}"]}) if a.json else f"cannot read it: {e}")
        return 2
    try:
        out = check(raw, a.repo.resolve(), store, key)
    finally:
        if store is not None:
            store.close()
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        for e in out["errors"]:
            print(f"error: {e}")
        for w in out["warnings"]:
            print(f"warning: {w}")
        if out["ok"]:
            conds = ", ".join(f"{n} ({v['check']}, {v['severity']})" for n, v in out["conditions"].items()) or "none"
            print(f"ok: conditions {conds}; ledger kinds {', '.join(sorted(set(out['ledger'].values()))) or 'none'}")
    return 0 if out["ok"] else 1


def main(args: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orchestra desk", description="The Desk's tools.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate [desk] in a configuration")
    c.add_argument("--repo", type=Path, default=Path.cwd(), help="the repository (default: here)")
    c.add_argument("--file", help="a whole proposed orchestra.toml to check instead; - for stdin")
    c.add_argument("--json", action="store_true", help="answer in JSON")
    sub.add_parser("measure", help="check every condition once and print the measurements (the instrument)")
    sub.add_parser("read", help="follow the bus for the ledger (the process orchestra run keeps)")
    a = ap.parse_args(args)
    if a.cmd == "check":
        return _check(a)
    if a.cmd == "measure":
        from .instrument import main as measure
        return measure()
    from .reader import main as read
    return read()


if __name__ == "__main__":
    sys.exit(main())
