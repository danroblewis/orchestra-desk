"""The board ranks: false first (most severe, then longest false), then unknown, then holding."""

import time

from conftest import put

from orchestra_desk.board import ranked
from orchestra_desk.config import settings
from orchestra_desk.instrument import measure

TOML = """
[desk.conditions."low-old"]
statement = "low, false for long"
severity = "low"
series = "a"
holds = "== 0"

[desk.conditions."high-new"]
statement = "high, false since now"
severity = "high"
series = "b"
holds = "== 0"

[desk.conditions."high-old"]
statement = "high, false for long"
severity = "high"
series = "c"
holds = "== 0"

[desk.conditions."critical-holds"]
statement = "critical, holds"
severity = "critical"
series = "d"
holds = "== 0"

[desk.conditions."medium-unknown"]
statement = "medium, nothing measured"
series = "e"
holds = "== 0"

[desk.conditions."critical-unknown"]
statement = "critical, nothing measured"
severity = "critical"
series = "f"
holds = "== 0"
"""


def test_false_conditions_are_ranked_by_severity_then_age(make_project, web):
    project = make_project(TOML)
    t0 = time.time() - 600
    for s in ("a", "c"):
        put(project, s, 1, ts=t0)
    put(project, "b", 0, ts=t0)
    put(project, "d", 0, ts=t0)
    measure(project, now=t0)
    t1 = t0 + 300
    for s in ("a", "b", "c"):
        put(project, s, 1, ts=t1)
    put(project, "d", 0, ts=t1)
    measure(project, now=t1)

    d = web.get("/api/plugins/desk/board").json()
    order = [c["name"] for c in d["conditions"]]
    assert order == ["high-old", "high-new", "low-old", "critical-unknown", "medium-unknown", "critical-holds"]
    assert d["counts"] == {"false": 3, "unknown": 2, "holds": 1}
    ages = {c["name"]: c["false_for"] for c in d["conditions"]}
    assert ages["high-old"] > ages["high-new"] and ages["critical-holds"] is None


def test_a_condition_not_checked_yet_is_unknown_and_says_so(make_project):
    project = make_project(TOML)
    items = ranked(settings(project.config.raw), {"conditions": {}}, time.time())
    assert {i["state"] for i in items} == {"unknown"}
    assert [i["name"] for i in items][:2] == ["critical-holds", "critical-unknown"]       # by severity, then name
    assert "not checked yet" in items[0]["evidence"]


def test_the_board_says_when_the_desk_is_not_configured_or_broken(make_project, web):
    make_project("", base='[events]\nurl = "file"\n\n[metrics]\nurl = "file"\n')
    d = web.get("/api/plugins/desk/board").json()
    assert not d["configured"] and d["conditions"] == [] and d["error"] is None
    make_project('\n[desk.conditions."x"]\nstatement = "x"\nseries = "a"\nholds = "about 3"\n')
    d = web.get("/api/plugins/desk/board").json()
    assert d["configured"] and "holds must be an operator and a number" in d["error"]
