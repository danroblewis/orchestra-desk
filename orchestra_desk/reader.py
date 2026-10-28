"""The ledger's reader: it follows the bus by offset and keeps an entry for each event a rule
names. It is a reader, not a machine: it never announces itself and never publishes.

``catch_up`` is one pass, from the offset kept in the ledger to the end of the bus. The
``desk.reader`` process (``python -m orchestra_desk read``) calls it every two seconds, and the web
server before it answers for the ledger, so the page is current with ``orchestra web`` alone. When
the rules change, or the bus is shorter than the offset (a new bus), it reads again from the
start; entries are kept by event id, so nothing is doubled."""

from __future__ import annotations

import hashlib
import json
import signal
import sys
import threading
from dataclasses import asdict

from orchestra.config import ConfigError, load_project
from orchestra.events import Events, event_time

from .config import Settings, settings
from .ledger import Entry, Ledger
from .rules import Rule, render, safe_link

OFFSET, RULES = "bus_offset", "rules"
EVERY_S = 2.0


def fingerprint(rules: dict[str, Rule]) -> str:
    return hashlib.sha256(json.dumps([asdict(r) for _, r in sorted(rules.items())]).encode()).hexdigest()[:16]


def entry_for(ev: dict, rules: dict[str, Rule]) -> Entry | None:
    r = rules.get(ev.get("type"))
    if r is None:
        return None
    source = ev.get("source") if isinstance(ev.get("source"), str) else None
    if r.sources and not (source in r.sources or (source or "").split("/")[0] in r.sources):
        return None
    at, eid = event_time(ev), ev.get("id")
    if at is None or not isinstance(eid, str) or not eid:
        return None
    subject = ev.get("subject") if isinstance(ev.get("subject"), str) else None
    label = render(r.label, ev) or subject or r.type
    return Entry(eid, at, r.kind, r.type, source, subject, label, safe_link(render(r.link, ev)))


def catch_up(events: Events, ledger: Ledger, rules: dict[str, Rule]) -> int:
    """Read the bus from where the ledger left off; returns how many entries were written."""
    fp = fingerprint(rules)
    replay = ledger.meta(RULES) != fp
    try:
        offset = int(ledger.meta(OFFSET) or 0)
    except ValueError:
        offset = 0
    if replay or events.end() < offset:
        offset = 0
    evs, nxt = events.after(offset)
    entries = [e for ev in evs if (e := entry_for(ev, rules)) is not None]
    return ledger.record(entries, {OFFSET: str(nxt), RULES: fp}, replace=replay)


def current(project, last: Settings | None) -> Settings | None:
    """The settings now, or the last good ones when the configuration is broken (said in the log)."""
    try:
        project.reload_config()
        return settings(project.config.raw)
    except (ConfigError, OSError, ValueError) as e:
        print(f"desk reader: the configuration is not usable, so the last good rules stand: {e}", flush=True)
        return last


def main() -> int:
    project = load_project()                  # ORCHESTRA_REPO, which the launcher sets
    events, ledger = Events.for_project(project), Ledger.for_project(project)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    stamp, s = None, None
    print("desk reader: following the bus for the ledger", flush=True)
    while not stop.is_set():
        if project.config_stamp() != stamp:
            stamp = project.config_stamp()
            s = current(project, s)
        if s is not None:
            try:
                n = catch_up(events, ledger, s.rules)
                if n:
                    print(f"desk reader: {n} new ledger entries", flush=True)
            except Exception as e:  # noqa: BLE001 - the bus or the ledger is down: try again next round
                print(f"desk reader: {type(e).__name__}: {e}", flush=True)
        stop.wait(EVERY_S)
    events.close()
    ledger.close()
    print("desk reader: stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
