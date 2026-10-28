"""End to end: `orchestra run` loads the plugin, keeps the reader running and runs the instrument.
A project instrument measures a queue; the condition over it turns false and true as the
measurement changes, and its state reaches the store through the instrument desk.conditions.
A landing on the bus reaches the ledger. Nothing on the bus comes from the Desk, and a restart
doubles nothing in the ledger."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from conftest import bus, publish
from orchestra.metrics import for_project

from orchestra_desk.ledger import Ledger

TOML = """[events]
url = "file"

[metrics]
url = "file"

[[collect]]
name = "queue"
command = "cat queue.prom"
every = "1s"

[desk]
every = "10s"

[desk.conditions."queue-short"]
statement = "The queue's oldest item waits under 100 seconds"
severity = "high"
series = "queue_oldest_seconds"
holds = "< 100"
"""


def wait_for(check, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        if v := check():
            return v
        time.sleep(0.5)
    raise AssertionError("timed out")


def start(project):
    orchestra = Path(sys.executable).with_name("orchestra")
    return subprocess.Popen([str(orchestra), "run"], cwd=project.repo_root, env=os.environ.copy(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)


def stop(host):
    host.send_signal(signal.SIGTERM)
    host.wait(timeout=40)


def holds(project):
    p = for_project(project).latest("desk_condition_holds", {"condition": "queue-short", "instrument": "desk.conditions"})
    return p[1] if p else None


def ledger_ids(project) -> list[str]:
    led = Ledger.for_project(project)
    try:
        return [e.id for e in led.entries()]
    finally:
        led.close()


def test_orchestra_run_measures_conditions_and_keeps_the_ledger(make_project):
    project = make_project("", base=TOML)
    queue = project.repo_root / "queue.prom"
    queue.write_text("queue_oldest_seconds 5\n")
    host = start(project)
    try:
        assert wait_for(lambda: holds(project) == 1)
        queue.write_text("queue_oldest_seconds 500\n")
        assert wait_for(lambda: holds(project) == 0)
        assert for_project(project).latest("desk_condition_false_seconds", {"condition": "queue-short"}) is not None

        publish(project, "gate.landed", {"ticket": "T-1", "gate_run": "g1"}, source="merge_gate", id="landing-1")
        assert wait_for(lambda: "landing-1" in ledger_ids(project), timeout=20)

        queue.write_text("queue_oldest_seconds 1\n")
        assert wait_for(lambda: holds(project) == 1)
        started = [e for e in bus(project) if e["type"] == "orchestra.process.started"]
        assert ("desk.reader", "desk") in [(e["data"]["name"], e["data"]["owner"]) for e in started]
    finally:
        stop(host)
    log = (project.logs_dir / "machines" / "desk.reader.log").read_text()
    assert "desk reader: stopped" in log
    events = bus(project)
    assert not [e for e in events if (e.get("source") or "").startswith("desk")]
    assert not [e for e in events if e["type"] == "orchestra.machine.started" and "desk" in str(e.get("data"))]
    kinds = [e for e in ledger_ids(project) if e.startswith("desk:condition:queue-short")]
    assert len(kinds) == 2                          # turned false, held again: the Desk's own entries

    before = sorted(ledger_ids(project))
    host = start(project)                           # a restart reads the bus again from its offset
    try:
        publish(project, "gate.landed", {"ticket": "T-2"}, source="merge_gate", id="landing-2")
        wait_for(lambda: "landing-2" in ledger_ids(project), timeout=20)
    finally:
        stop(host)
    after = ledger_ids(project)
    assert len(after) == len(set(after)) and sorted(set(after) - {"landing-2"}) == before
