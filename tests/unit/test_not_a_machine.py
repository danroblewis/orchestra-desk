"""The Desk is no machine: it never publishes an event, under its own name or any other, and never
writes the metrics store. Its measurements reach the store only through the instrument that
``orchestra run`` runs (see the e2e test)."""

import ast
import time
from pathlib import Path

from conftest import bus, publish, put, script
from orchestra.metrics import for_project

from orchestra_desk.instrument import measure

PACKAGE = Path(__file__).parents[2] / "orchestra_desk"


def test_a_whole_round_publishes_nothing_and_writes_no_metric(make_project, web):
    project = make_project("")
    s = script(project, "s.sh", "echo 0\necho why\n")
    project = make_project(f"""
[desk.conditions."reviews-wait"]
statement = "No PR waits"
series = "github_prs_review_request_oldest_seconds"
holds = "<= 86400"

[desk.conditions."s"]
statement = "s"
command = ["{s}"]
""")
    put(project, "github_prs_review_request_oldest_seconds", 5)
    publish(project, "gate.landed", {"ticket": "T-1"}, source="merge_gate")
    before_events = bus(project)
    store = for_project(project)
    before_series = store.series("")
    t = time.time()
    for i in range(3):
        put(project, "github_prs_review_request_oldest_seconds", 5 if i % 2 else 10 ** 6, ts=t + i)
        measure(project, now=t + i)
        web.get("/api/plugins/desk/board")
        web.get("/api/plugins/desk/ledger", params={"period": "all"})
    assert bus(project) == before_events
    assert store.series("desk") == [] and len(store.series("")) == len(before_series)


def test_the_package_has_no_way_to_publish_or_write_metrics():
    """No call to publish or emit, no metric point or store write, no announcement: in any module."""
    forbidden_calls = {"publish", "emit", "write"}
    forbidden_names = {"Point", "ProjectStore", "for_repo"}
    for f in PACKAGE.rglob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            call = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            if call and node.func.attr in forbidden_calls:
                # sys.stdout.write is how the instrument prints its measurements
                assert ast.unparse(node.func.value) == "sys.stdout", f"{f.name}: {ast.unparse(node)}"
            if isinstance(node, ast.Name | ast.alias):
                name = node.id if isinstance(node, ast.Name) else node.name
                assert name not in forbidden_names, f"{f.name}: uses {name}"
        assert "orchestra.machine.started" not in f.read_text(), f.name
