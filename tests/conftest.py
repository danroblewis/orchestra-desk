"""What the tests share: a project in a fresh git repository under a temporary ORCHESTRATOR_HOME
with ``[desk]`` configured, a way to put points in its metrics store and events on its bus (as an
instrument and machines would; the Desk itself never does either), and the web app with the
plugin mounted."""

import subprocess
import time

import pytest
from orchestra.config import load_project
from orchestra.events import Events
from orchestra.metrics import Point, ProjectStore, for_project

BASE_TOML = """[events]
url = "file"

[metrics]
url = "file"

[desk]
owner = ["person.owner"]
every = "10s"
"""

CONDITIONS = """
[desk.conditions."reviews-wait"]
statement = "No pull request waits more than a day for a review asked of someone"
severity = "high"
link = "https://github.com/pulls/review-requested"
series = "github_prs_review_request_oldest_seconds"
holds = "<= 86400"
"""


@pytest.fixture
def make_project(tmp_path, monkeypatch):
    """make_project(extra_toml=""): a project with [desk] and the extra configuration."""
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCHESTRA_EVENTS_URL", raising=False)
    monkeypatch.delenv("ORCHESTRA_METRICS_URL", raising=False)
    monkeypatch.delenv("ORCHESTRA_CONFIG_OVERLAY", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    monkeypatch.setenv("ORCHESTRA_REPO", str(repo))

    def make(extra: str = CONDITIONS, base: str = BASE_TOML):
        (repo / "orchestra.toml").write_text(base + extra)
        return load_project(repo)
    return make


@pytest.fixture
def project(make_project):
    return make_project()


@pytest.fixture
def web(project):
    from fastapi.testclient import TestClient
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    return TestClient(create_app(project), headers=bearer(project))


def put(project, series: str, value: float, labels: dict | None = None, ts: float | None = None) -> None:
    """A point in the project's store, as an instrument would write it."""
    store = ProjectStore(for_project(project), project.key)
    store.write([Point(series, value, time.time() if ts is None else ts, labels or {})])
    store.close()


def publish(project, type_: str, data=None, **ext) -> dict:
    """An event on the project's bus, as a machine would publish it."""
    ev = Events.for_project(project, source=ext.pop("source", "someone"))
    try:
        return ev.publish(type_, data, **ext)
    finally:
        ev.close()


def bus(project) -> list[dict]:
    return Events.for_project(project).after(0)[0]


def script(project, name: str, body: str) -> str:
    """An executable script in the repository; its path relative to the root."""
    d = project.repo_root / "scripts"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(0o755)
    return f"scripts/{name}"
