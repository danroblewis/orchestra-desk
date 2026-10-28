"""The plugin's declaration, and Orchestra finding and serving it."""

import shlex
import sys
from pathlib import Path

from orchestra.config import Config, Project
from orchestra.plugins import load

from orchestra_desk.plugin import plugin


def proj(toml: str) -> Project:
    return Project("k", Path("/repo"), Config.from_toml(toml))


def test_it_runs_only_where_it_is_configured_and_declares_no_machine():
    off = plugin(proj('[events]\nurl = "file"\n'))
    assert (off.name, off.processes, off.machines, off.collectors) == ("desk", [], [], [])
    assert [p.path for p in off.pages] == ["/desk", "/ledger"]
    on = plugin(proj('[desk]\nevery = "30s"\n'))
    [p] = on.processes
    assert (p.name, p.argv(), p.restart) == ("reader", [sys.executable, "-m", "orchestra_desk", "read"], "always")
    [c] = on.collectors
    assert (c.name, c.kind, c.argv(), c.every_s) == ("conditions", "collect",
                                                    [sys.executable, "-m", "orchestra_desk", "measure"], 30)
    assert on.machines == [] and on.scripts == [] and on.stylesheets == []
    assert plugin(proj('[desk]\nevery = "never"\n')).collectors[0].every_s == 60     # the instrument says why
    assert shlex.split(c.target)[0] == sys.executable


def test_orchestra_finds_the_installed_plugin():
    loaded = load(proj("[desk]\n"))
    assert "desk" in [p.name for p in loaded.plugins] and not loaded.errors


def test_the_web_app_serves_both_pages(web):
    d = web.get("/api/plugins").json()
    assert {"plugin": "desk", "path": "/desk", "title": "Desk"} in d["pages"]
    assert {"plugin": "desk", "path": "/ledger", "title": "Ledger"} in d["pages"] and d["errors"] == []
    for f in ("board.js", "ledger.js", "desk.css"):
        assert web.get(f"/plugins/desk/static/{f}").status_code == 200
    assert web.get("/api/plugins/desk/board").json()["configured"]


def test_the_state_is_the_owners_alone(project, web):
    import stat
    web.get("/api/plugins/desk/ledger")
    db = project.state_dir / "desk" / "ledger.db"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700


def test_the_pages_and_api_are_behind_orchestras_login(project, web):
    """The ledger is the owner's: without the web token nothing of the Desk answers."""
    from fastapi.testclient import TestClient
    from orchestra.web.app import create_app

    anyone = TestClient(create_app(project))
    for path in ("/api/plugins/desk/board", "/api/plugins/desk/ledger", "/plugins/desk/static/board.js"):
        assert anyone.get(path).status_code == 401, path
    assert anyone.get("/desk", headers={"Accept": "text/html"}, follow_redirects=False).headers["location"] == "/login?next=%2Fdesk"
    assert web.get("/api/plugins/desk/board").status_code == 200
