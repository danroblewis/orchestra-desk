"""Conditions over the metrics store: they turn false and true as the data changes, the instrument
reports it, an expression reads several series, missing and stale readings are unknown (or what
the condition says), and a script's reason reaches the board."""

import time

from conftest import put, script

from orchestra_desk import record as R
from orchestra_desk.instrument import measure
from orchestra_desk.ledger import Ledger


def holds_line(text: str, name: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f'desk_condition_holds{{condition="{name}"}}'):
            return line.split()[-1]
    return None


def false_seconds(text: str, name: str) -> float | None:
    for line in text.splitlines():
        if line.startswith(f'desk_condition_false_seconds{{condition="{name}"}}'):
            return float(line.split()[-1])
    return None


def test_a_series_condition_turns_false_and_true_and_its_instrument_reports_it(project, web):
    t0 = time.time() - 10_000                       # in the past: the store refuses points stamped ahead
    put(project, "github_prs_review_request_oldest_seconds", 3600, ts=t0)
    out = measure(project, now=t0)
    assert holds_line(out, "reviews-wait") == "1" and false_seconds(out, "reviews-wait") == 0
    assert 'desk_conditions{state="holds"} 1' in out

    put(project, "github_prs_review_request_oldest_seconds", 2 * 86400, ts=t0 + 10)
    out = measure(project, now=t0 + 10)
    assert holds_line(out, "reviews-wait") == "0" and false_seconds(out, "reviews-wait") == 0
    out = measure(project, now=t0 + 70)
    assert false_seconds(out, "reviews-wait") == 60               # how long false, counted from the turn
    assert 'desk_conditions{state="false"} 1' in out

    [c] = web.get("/api/plugins/desk/board").json()["conditions"]
    assert c["state"] == "false" and c["value"] == 2 * 86400 and c["severity"] == "high"
    assert "github_prs_review_request_oldest_seconds = 172800" in c["evidence"] and "<= 86400" in c["evidence"]
    assert c["link"] == "https://github.com/pulls/review-requested"
    assert c["evidence_link"].startswith("/api/core/metrics/query?q=github_prs_review_request_oldest_seconds")

    put(project, "github_prs_review_request_oldest_seconds", 60, ts=t0 + 80)
    out = measure(project, now=t0 + 80)
    assert holds_line(out, "reviews-wait") == "1" and false_seconds(out, "reviews-wait") == 0

    # each turn is in the ledger, as the Desk's own entry
    led = Ledger.for_project(project)
    changes = [(e.type, e.subject, e.origin) for e in reversed(led.entries())]
    assert changes == [("desk.condition.false", "reviews-wait", "desk"), ("desk.condition.holds", "reviews-wait", "desk")]
    assert "after 0.0h" in led.entries()[0].label


def test_an_unknown_check_does_not_reset_how_long_it_has_been_false(project):
    t0 = time.time() - 10_000
    put(project, "github_prs_review_request_oldest_seconds", 2 * 86400, ts=t0)
    measure(project, now=t0)
    out = measure(project, now=t0 + 3600)            # the reading is now an hour old: older than max_age
    assert holds_line(out, "reviews-wait") is None and 'desk_conditions{state="unknown"} 1' in out
    put(project, "github_prs_review_request_oldest_seconds", 2 * 86400, ts=t0 + 3700)
    out = measure(project, now=t0 + 3700)
    assert false_seconds(out, "reviews-wait") == 3700
    rec = R.load(R.path_for(project.state_dir))["conditions"]["reviews-wait"]
    assert rec["false_since"] == t0 and rec["since"] == t0 + 3700


def test_labels_reduce_and_this_projects_series_only(make_project):
    project = make_project("""
[desk.conditions."stuck"]
statement = "No ticket of the desk team is stuck"
series = "tickets_stuck"
labels = { team = "desk" }
reduce = "sum"
holds = "== 0"
""")
    now = time.time()
    put(project, "tickets_stuck", 0, {"team": "desk", "repo": "a"}, ts=now)
    put(project, "tickets_stuck", 0, {"team": "desk", "repo": "b"}, ts=now)
    put(project, "tickets_stuck", 5, {"team": "other"}, ts=now)
    put(project, "tickets_stuck", 7, {"team": "desk", "project": "another-project"}, ts=now)
    assert holds_line(measure(project, now=now), "stuck") == "1"
    put(project, "tickets_stuck", 2, {"team": "desk", "repo": "b"}, ts=now + 1)
    out = measure(project, now=now + 1)
    assert holds_line(out, "stuck") == "0"
    rec = R.load(R.path_for(project.state_dir))["conditions"]["stuck"]
    assert rec["value"] == 2 and "sum of 2 series" in rec["evidence"]


def test_an_expression_over_several_series(make_project):
    project = make_project("""
[desk.conditions."few-stuck"]
statement = "Under a fifth of the tickets in progress are stuck"
expr = "stuck / max(working, 1)"
holds = "< 0.2"
vars = { stuck = "tickets_stuck", working = { series = "tickets", labels = { state = "working" } } }
""")
    now = time.time()
    put(project, "tickets", 10, {"state": "working"}, ts=now)
    put(project, "tickets", 99, {"state": "done"}, ts=now)
    put(project, "tickets_stuck", 1, ts=now)
    assert holds_line(measure(project, now=now), "few-stuck") == "1"
    put(project, "tickets_stuck", 3, ts=now + 1)
    assert holds_line(measure(project, now=now + 1), "few-stuck") == "0"
    rec = R.load(R.path_for(project.state_dir))["conditions"]["few-stuck"]
    assert rec["value"] == 0.3 and rec["evidence"].startswith("stuck / max(working, 1) = 0.3 from ")


def test_missing_readings_are_unknown_unless_the_condition_says_otherwise(make_project):
    project = make_project("""
[desk.conditions."no-alerts"]
statement = "No alert is firing"
series = "alerts_firing"
holds = "== 0"
when_missing = "holds"

[desk.conditions."rate"]
statement = "Error rate is low"
expr = "errors / requests"
holds = "< 0.01"
vars = { errors = "errors_total", requests = "requests_total" }

[desk.conditions."never-seen"]
statement = "Something nobody measures yet"
series = "not_measured"
holds = "> 0"
""")
    now = time.time()
    put(project, "errors_total", 1, ts=now)
    put(project, "requests_total", 0, ts=now)
    out = measure(project, now=now)
    assert holds_line(out, "no-alerts") == "1"
    assert holds_line(out, "rate") is None and holds_line(out, "never-seen") is None
    recs = R.load(R.path_for(project.state_dir))["conditions"]
    assert recs["rate"]["state"] == "unknown" and "division by zero" in recs["rate"]["evidence"]
    assert recs["never-seen"]["evidence"] == "missing: not_measured: no such series"
    assert "when_missing = holds" in recs["no-alerts"]["evidence"]


def test_a_script_conditions_reason_is_shown_on_the_board(make_project, web):
    project = make_project("")
    ok = script(project, "secrets.sh", 'echo 0\necho "the deploy key expires in 12 days"\necho "rotate it in Vault"\n')
    bad = script(project, "broken.sh", "echo maybe\n")
    fails = script(project, "fails.sh", "echo boom >&2\nexit 3\n")
    slow = script(project, "slow.sh", "sleep 30\necho 1\n")
    project = make_project(f"""
[desk.conditions."secrets"]
statement = "No secret expires within 30 days"
severity = "critical"
command = ["{ok}"]

[desk.conditions."bad"]
statement = "A script that answers nonsense"
command = ["{bad}"]

[desk.conditions."fails"]
statement = "A script that fails"
command = "{fails} --flag"

[desk.conditions."slow"]
statement = "A script that is too slow"
command = ["{slow}"]
timeout = "1s"
""")
    out = measure(project)
    assert holds_line(out, "secrets") == "0"
    board = {c["name"]: c for c in web.get("/api/plugins/desk/board").json()["conditions"]}
    assert board["secrets"]["state"] == "false"
    assert board["secrets"]["reason"] == "the deploy key expires in 12 days\nrotate it in Vault"
    assert board["bad"]["state"] == "unknown" and "first line must be 1 or 0" in board["bad"]["evidence"]
    assert board["fails"]["state"] == "unknown" and "exited 3: boom" in board["fails"]["evidence"]
    assert board["slow"]["state"] == "unknown" and "took longer than 1s" in board["slow"]["evidence"]
    page = web.get("/desk").text
    assert "/plugins/desk/static/board.js" in page and "{{v}}" not in page


def test_a_reason_is_never_a_measurement(make_project):
    project = make_project("")
    s = script(project, "s.sh", 'echo 0\necho "REASON-CANARY"\n')
    project = make_project(f'\n[desk.conditions."s"]\nstatement = "s"\ncommand = ["{s}"]\n')
    out = measure(project)
    assert "REASON-CANARY" not in out and "statement" not in out
