"""The configuration contract: what is refused, and why; the check as the Supervisor's tools call
it (CLI, exit codes, JSON, warnings); and SPEC.md's example, which must stay valid."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from orchestra_desk.cli import main
from orchestra_desk.config import problems, settings

SPEC = Path(__file__).parents[2] / "SPEC.md"


def errors(desk_toml: str) -> list[str]:
    """Problems of ``[desk]`` written as if inside it: ``[conditions.x]`` means ``[desk.conditions.x]``."""
    text = re.sub(r"^\[(conditions|ledger)", r"[desk.\1", desk_toml, flags=re.MULTILINE)
    return problems(tomllib.loads("[desk]\n" + text))[1]


@pytest.mark.parametrize("toml,why", [
    ('colour = "blue"', "[desk] has unknown keys: colour"),
    ('every = "1s"', "[desk] every must be between 10s and 3600s"),
    ('every = "soon"', "[desk] every must be a duration"),
    ("owner = [3]", "[desk] owner must be a source"),
    ('[conditions."A b"]\nstatement = "x"\nseries = "a"\nholds = "> 1"', "a condition's name is lowercase"),
    ('[conditions.x]\nseries = "a"\nholds = "> 1"', "statement must say"),
    ('[conditions.x]\nstatement = "x"\nholds = "> 1"', "needs exactly one check"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nexpr = "a"\nholds = "> 1"', "needs exactly one check"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"', "holds must be an operator and a number"),
    ('[conditions.x]\nstatement = "x"\nseries = "a b"\nholds = "> 1"', "series must be a series name"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\nseverity = "urgent"', "severity must be one of"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\nreduce = "median"', "reduce must be one of"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\nlabels = { project = "p" }', "project is set by the Desk"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\nlink = "javascript:alert(1)"', "link must be an http(s) URL"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\nwhen_missing = "maybe"', "when_missing must be one of"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\ntimeout = "3s"', "timeout is only for a script"),
    ('[conditions.x]\nstatement = "x"\nseries = "a"\nholds = "> 1"\nthreshold = 3', "has unknown keys: threshold"),
    ('[conditions.x]\nstatement = "x"\nexpr = "a / b"\nholds = "> 1"\nvars = { a = "s" }', "expr names b, which vars does not define"),
    ('[conditions.x]\nstatement = "x"\nexpr = "a"\nholds = "> 1"\nvars = { a = "s", b = "t" }', "vars defines b, which expr does not use"),
    ('[conditions.x]\nstatement = "x"\nexpr = "a.real"\nholds = "> 1"\nvars = { a = "s" }', "Attribute is not allowed"),
    ('[conditions.x]\nstatement = "x"\nexpr = "a"\nholds = "> 1"', "needs vars"),
    ('[conditions.x]\nstatement = "x"\nexpr = "a"\nholds = "> 1"\nvars = { a = { series = "s", lables = {} } }', "has unknown keys: lables"),
    ('[conditions.x]\nstatement = "x"\ncommand = []', "command must be a list"),
    ('[conditions.x]\nstatement = "x"\ncommand = ["a.sh"]\nholds = "> 1"', "holds is not for a script condition"),
    ('[conditions.x]\nstatement = "x"\ncommand = ["a.sh"]\ntimeout = "2m"', "timeout must be between 1s and 55s"),
    ('[ledger]\nrules = 1', "[desk.ledger] has unknown keys: rules"),
    ('[ledger.types."gate.landed"]\nkind = "Landed!"', "kind must be a short lowercase word"),
    ('[ledger.types."gate.landed"]\nkind = "condition"', "not \"condition\""),
    ('[ledger.types."gate.landed"]\nkind = "landed"\nlink = "{data.ticket.name}"', "unknown placeholder"),
    ('[ledger.types."gate.landed"]\nkind = "landed"\nlabel = "{title}"', "unknown placeholder {title}"),
    ('[ledger.types."gate.landed"]\nkind = "landed"\nlink = "ftp://x/{subject}"', "link must make an http(s) URL"),
    ('[ledger.types."gate.landed"]\nignore = true\nkind = "x"', "ignore = true takes no other keys"),
    ('[ledger.types."gate.landed"]\nkind = "landed"\nsources = "me"', "sources must be a list"),
])
def test_an_invalid_configuration_is_refused_with_the_reason(toml, why):
    errs = errors(toml)
    assert any(why in e for e in errs), errs


def test_every_problem_is_reported_at_once():
    errs = errors('colour = 1\n[conditions.a]\nstatement = "a"\n[conditions.b]\nstatement = "b"\nseries = "x"')
    assert len(errs) == 3


def test_a_minimal_desk_has_the_built_in_ledger_rules_and_no_conditions():
    s = settings({"desk": {}})
    assert s.conditions == {} and s.every == 60 and s.rules["gate.landed"].kind == "landed"
    assert settings({"desk": {"ledger": {"defaults": False}}}).rules == {}


def spec_example() -> str:
    m = re.search(r"<!-- spec-example -->\s*```toml\n(.*?)```", SPEC.read_text(), re.DOTALL)
    assert m, "SPEC.md has no example marked <!-- spec-example -->"
    return m.group(1)


def test_the_specs_example_is_valid():
    s = settings(tomllib.loads(spec_example()))
    assert {c.check for c in s.conditions.values()} == {"series", "expr", "script"}


def test_the_check_cli(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    good = tmp_path / "good.toml"
    good.write_text(spec_example())
    assert main(["check", "--file", str(good), "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "warning: [desk.conditions.\"secrets\"] command 'scripts/desk/secrets.sh' is not a file" in out
    assert out.strip().endswith("ledger kinds closed, jira, landed, merged, opened, reviewed, sent, ticket")

    bad = tmp_path / "bad.toml"
    bad.write_text('[desk]\nevery = "1s"\n')
    assert main(["check", "--file", str(bad), "--json"]) == 1
    d = json.loads(capsys.readouterr().out)
    assert not d["ok"] and "every must be between" in d["errors"][0]

    assert main(["check", "--file", str(tmp_path / "missing.toml")]) == 2
    (tmp_path / "broken.toml").write_text("[desk\n")
    assert main(["check", "--file", str(tmp_path / "broken.toml"), "--json"]) == 2


def test_the_check_of_a_repository_reads_its_configuration_and_its_store(make_project, capsys):
    from conftest import put
    project = make_project()
    assert main(["check", "--repo", str(project.repo_root), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["warnings"] == [('[desk.conditions."reviews-wait"] series github_prs_review_request_oldest_seconds '
                              "is not in this project's metrics store yet")]
    put(project, "github_prs_review_request_oldest_seconds", 1)
    assert main(["check", "--repo", str(project.repo_root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == []


def test_the_installed_command(tmp_path):
    r = subprocess.run([sys.executable, "-m", "orchestra", "desk", "check", "--file", "-", "--json"],
                       input='[desk]\nevery = "2s"\n', capture_output=True, text=True, check=False)
    assert r.returncode == 1 and not json.loads(r.stdout)["ok"]


def test_no_desk_section_is_no_problem_for_the_plugin_check(project):
    """Plugin.check judges only [desk], and its absence is fine: config_edit may remove it."""
    from orchestra import config_edit
    from orchestra.config import ConfigError

    from orchestra_desk.plugin import plugin

    assert problems({}) == (None, [])
    with pytest.raises(ConfigError, match="no \\[desk\\] section"):
        settings({})
    check = plugin(project).check
    assert check({}, project.repo_root) == [] and check({"desk": {"colour": 1}}, None)
    config_edit._LOADED.clear()
    with pytest.raises(ConfigError, match="desk: \\[desk\\] has unknown keys: colour"):
        project.config_edit.set("desk.colour", "blue")
    project.config_edit.unset("desk")
    assert "desk" not in project.config.raw
    config_edit._LOADED.clear()
