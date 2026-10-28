"""The ledger, from a recorded bus: landings, merges, reviews and sends become entries linked to
their source; a restart reads on without doubling anything; rules filter and relabel; the page's
API filters by day, week, kind and the owner's own acts."""

from datetime import datetime, timedelta

from conftest import publish
from orchestra.events import Events

from orchestra_desk.config import settings
from orchestra_desk.ledger import Ledger
from orchestra_desk.reader import catch_up

MON = datetime(2026, 10, 26, 10, 0)     # a Monday


def at(dt: datetime) -> str:
    return dt.astimezone().isoformat()


def record_a_week(project):
    """A bus as the task system, the GitHub bridge and the Outbox would have written it."""
    publish(project, "orchestra.machine.started", {"kind": "person"}, source="person.owner", time=at(MON))
    publish(project, "gate.landed", {"gate_run": "g1", "ticket": "T-12", "commit": "abc"}, source="merge_gate",
            time=at(MON), id="land-1")
    publish(project, "github.pr.merged", {"repo": "acme/widgets", "number": 7}, source="person.owner",
            subject="acme/widgets#7", time=at(MON + timedelta(hours=1)), id="gh-merge-7")
    publish(project, "github.pr.review_submitted", {"state": "approved"}, source="person.owner",
            subject="acme/widgets#9", time=at(MON + timedelta(days=1)), id="gh-review-9")
    publish(project, "github.pr.review_submitted", {"state": "approved"}, source="person.ana",
            subject="acme/widgets#7", time=at(MON + timedelta(days=1, hours=2)), id="gh-review-7")
    publish(project, "outbox.sent", {"draft": "d1", "kind": "review.request", "to": "worker/1"}, source="outbox",
            subject="d1", time=at(MON + timedelta(days=2)), id="outbox:d1:3")
    publish(project, "task.working", {"ticket": "T-12"}, source="worker/1", time=at(MON), id="noise")
    publish(project, "gate.landed", {"ticket": "T-13"}, source="merge_gate", time=at(MON - timedelta(days=3)),
            id="land-last-week")


def read(project) -> int:
    events, led = Events.for_project(project), Ledger.for_project(project)
    try:
        return catch_up(events, led, settings(project.config.raw).rules)
    finally:
        events.close()
        led.close()


def test_landings_and_merges_from_a_recorded_bus_and_a_restart_doubles_nothing(project):
    record_a_week(project)
    assert read(project) == 6
    led = Ledger.for_project(project)
    by_id = {e.id: e for e in led.entries()}
    assert set(by_id) == {"land-1", "gh-merge-7", "gh-review-9", "gh-review-7", "outbox:d1:3", "land-last-week"}
    land = by_id["land-1"]
    assert (land.kind, land.label, land.link, land.source) == ("landed", "T-12", "/tickets#ticket=T-12", "merge_gate")
    merge = by_id["gh-merge-7"]
    assert (merge.kind, merge.label, merge.link) == ("merged", "acme/widgets#7", "https://github.com/acme/widgets/pull/7")
    assert (by_id["outbox:d1:3"].kind, by_id["outbox:d1:3"].label, by_id["outbox:d1:3"].link) == ("sent", "review.request", "/outbox")
    led.close()

    assert read(project) == 0                         # nothing new: nothing written
    publish(project, "gate.landed", {"ticket": "T-14"}, source="merge_gate", id="land-2")
    assert read(project) == 1                         # a restart (new handles) reads on from where it was
    led = Ledger.for_project(project)
    assert led.count() == 7
    led.record([], {"bus_offset": "0"})               # a lost offset: everything is read again ...
    led.close()
    read(project)
    led = Ledger.for_project(project)
    assert led.count() == 7                           # ... and kept once
    assert sorted(e.id for e in led.entries()).count("land-1") == 1


def test_rules_filter_relabel_and_a_change_of_rules_reads_again(make_project):
    project = make_project("""
[desk.ledger.types."github.pr.review_submitted"]
kind = "reviewed"
sources = ["person.owner"]

[desk.ledger.types."outbox.sent"]
ignore = true

[desk.ledger.types."jira.issue.transitioned"]
kind = "jira"
link = "https://jira.example.com/browse/{subject}"
""")
    record_a_week(project)
    publish(project, "jira.issue.transitioned", {"to": "Done"}, source="person.owner", subject="OPS-3", id="j1")
    read(project)
    led = Ledger.for_project(project)
    ids = {e.id: e for e in led.entries()}
    assert "gh-review-7" not in ids and "gh-review-9" in ids and "outbox:d1:3" not in ids
    assert ids["j1"].link == "https://jira.example.com/browse/OPS-3"
    led.close()

    project = make_project("")                          # back to the built-in rules: read again, nothing doubled
    read(project)
    led = Ledger.for_project(project)
    ids = [e.id for e in led.entries()]
    assert "outbox:d1:3" in ids and "gh-review-7" in ids and len(ids) == len(set(ids))


def test_a_link_that_is_not_http_or_a_path_is_dropped(make_project):
    project = make_project('\n[desk.ledger.types."x.done"]\nkind = "done"\nlink = "{subject}"\n')
    publish(project, "x.done", subject="javascript:alert(1)", id="x1")
    publish(project, "x.done", subject="/tickets#ticket=T-1", id="x2")
    read(project)
    led = Ledger.for_project(project)
    links = {e.id: e.link for e in led.entries()}
    assert links == {"x1": None, "x2": "/tickets#ticket=T-1"}


def test_the_ledger_page_filters_by_day_week_kind_and_mine(project, web):
    record_a_week(project)
    week = web.get("/api/plugins/desk/ledger", params={"period": "week", "at": "2026-10-28"}).json()
    assert week["name"] == "week of 2026-10-26"
    assert [e["id"] for e in week["entries"]] == ["outbox:d1:3", "gh-review-7", "gh-review-9", "gh-merge-7", "land-1"]
    assert week["counts"] == {"sent": 1, "reviewed": 2, "merged": 1, "landed": 1}
    day = web.get("/api/plugins/desk/ledger", params={"period": "day", "at": "2026-10-26"}).json()
    assert [e["id"] for e in day["entries"]] == ["gh-merge-7", "land-1"]
    kinds = web.get("/api/plugins/desk/ledger", params={"period": "all", "kind": "landed"}).json()
    assert [e["id"] for e in kinds["entries"]] == ["land-1", "land-last-week"]
    mine = web.get("/api/plugins/desk/ledger", params={"period": "all", "mine": "true"}).json()
    assert [e["id"] for e in mine["entries"]] == ["gh-review-9", "gh-merge-7"]
    assert web.get("/api/plugins/desk/ledger", params={"period": "month"}).status_code == 400
    page = web.get("/ledger").text
    assert "/plugins/desk/static/ledger.js" in page and "{{v}}" not in page
