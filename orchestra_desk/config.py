"""The Desk's settings: ``[desk]`` in the project's configuration (``project.config.raw``, the
overlay merged), a section Orchestra ignores. The contract is SPEC.md §4; the Supervisor edits it
through ``project.config_edit``, and ``orchestra desk check`` validates it first (``check.py``).

::

    [desk]
    owner = ["person.danroblewis"]   # the sources that are the owner: the ledger's "mine"
    every = "60s"                    # how often the instrument desk.conditions checks every condition
    max_age = "15m"                  # a reading older than this is missing (default for every reading)

    [desk.conditions."reviews-wait"]                   # one series against a bound
    statement = "No PR of mine waits more than a day for review"
    severity = "high"                                  # critical, high, medium (default), low
    link = "https://github.com/pulls/review-requested" # where to act on it
    series = "github_prs_awaiting_review_oldest_seconds"
    labels = { author = "danroblewis" }
    reduce = "max"                                     # several series match: max (default), min, sum, avg, count
    holds = "<= 86400"

    [desk.conditions."few-stuck"]                      # an expression over named readings
    statement = "Under a fifth of tickets in progress are stuck"
    expr = "stuck / max(working, 1)"
    holds = "< 0.2"
    vars = { stuck = "tasks_tickets_stuck", working = { series = "tasks_tickets", labels = { state = "working" } } }

    [desk.conditions."secrets"]                        # a script: prints 1 or 0, then the reason
    statement = "No secret expires within 30 days"
    command = ["scripts/desk/secrets.sh"]
    timeout = "20s"

    [desk.ledger]
    defaults = true                                    # the built-in rules (rules.py); false: only yours
    [desk.ledger.types."jira.issue.transitioned"]
    kind = "jira"
    label = "{subject}"
    link = "https://jira.example.com/browse/{subject}"

Every key is checked and an unknown one is refused, so a typo is caught."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from orchestra.config import ConfigError, parse_duration

from .language import Comparison, Expression, LanguageError, comparison, expression
from .rules import DEFAULTS, Rule, placeholders

SEVERITIES = ("critical", "high", "medium", "low")      # most severe first
REDUCERS = ("max", "min", "sum", "avg", "count")
MISSING = ("unknown", "holds", "false")
DEFAULT_EVERY, MIN_EVERY, MAX_EVERY = 60.0, 10.0, 3600.0
DEFAULT_MAX_AGE = 900.0
DEFAULT_TIMEOUT = 20.0
DESK_KEYS = {"owner", "every", "max_age", "conditions", "ledger"}
CONDITION_KEYS = {"statement", "severity", "link", "series", "labels", "reduce", "max_age", "when_missing",
                  "expr", "vars", "holds", "command", "timeout"}
READING_KEYS = {"series", "labels", "reduce", "max_age"}
LEDGER_KEYS = {"defaults", "types"}
RULE_KEYS = {"kind", "label", "link", "sources", "ignore"}
_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_SERIES = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_VAR = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SOURCE = re.compile(r"^[A-Za-z0-9_.:-]+(/[A-Za-z0-9_.:-]+)?$")
_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Reading:
    series: str
    labels: tuple[tuple[str, str], ...] = ()
    reduce: str = "max"
    max_age: float = DEFAULT_MAX_AGE

    def selector(self) -> str:
        """The reading as a PromQL selector, for evidence and links."""
        lab = ",".join(f'{k}="{v}"' for k, v in self.labels)
        return f"{self.series}{{{lab}}}" if lab else self.series


@dataclass(frozen=True)
class Condition:
    name: str
    statement: str
    check: str                                   # "series", "expr" or "script"
    severity: str = "medium"
    link: str | None = None
    readings: dict[str, Reading] = field(default_factory=dict)
    expr: Expression | None = None
    holds: Comparison | None = None
    when_missing: str = "unknown"
    command: tuple[str, ...] = ()
    timeout: float = DEFAULT_TIMEOUT

    @property
    def rank(self) -> int:
        return SEVERITIES.index(self.severity)


@dataclass
class Settings:
    owner: tuple[str, ...] = ()
    every: float = DEFAULT_EVERY
    max_age: float = DEFAULT_MAX_AGE
    conditions: dict[str, Condition] = field(default_factory=dict)
    rules: dict[str, Rule] = field(default_factory=lambda: dict(DEFAULTS))


def section(raw: dict[str, Any]) -> dict | None:
    """``[desk]`` of the configuration, or None when the project does not configure the Desk."""
    s = raw.get("desk")
    return s if isinstance(s, dict) else None


def _duration(where: str, value: object, default: float, low: float, high: float) -> float:
    try:
        d = parse_duration(value, default)
    except (ConfigError, ValueError, TypeError):
        raise ConfigError(f"{where} must be a duration like \"60s\", \"15m\" or \"2h\", not {value!r}") from None
    if not low <= d <= high:
        raise ConfigError(f"{where} must be between {low:g}s and {high:g}s, not {d:g}s")
    return d


def _link(where: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not (value.startswith(("https://", "http://")) or
                                          (value.startswith("/") and not value.startswith("//"))):
        raise ConfigError(f"{where} link must be an http(s) URL or a path on this Orchestra (/...), not {value!r}")
    return value


def _labels(where: str, value: object) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or not all(isinstance(k, str) and _LABEL.match(k) and isinstance(v, str)
                                              for k, v in value.items()):
        raise ConfigError(f"{where} labels must be a table of label names to strings, like {{ state = \"working\" }}")
    if "project" in value:
        raise ConfigError(f"{where} labels: project is set by the Desk (this project's series only)")
    return tuple(sorted(value.items()))


def reading(where: str, value: object, max_age: float) -> Reading:
    if isinstance(value, str):
        value = {"series": value}
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a series name or a table {{ series, labels, reduce, max_age }}")
    unknown = set(value) - READING_KEYS
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {', '.join(sorted(unknown))} (it takes {', '.join(sorted(READING_KEYS))})")
    series = value.get("series")
    if not isinstance(series, str) or not _SERIES.match(series):
        raise ConfigError(f"{where} series must be a series name (letters, digits, _ and :), not {series!r}")
    reduce = value.get("reduce", "max")
    if reduce not in REDUCERS:
        raise ConfigError(f"{where} reduce must be one of {', '.join(REDUCERS)}, not {reduce!r}")
    age = _duration(f"{where} max_age", value.get("max_age"), max_age, 1, 30 * 86400)
    return Reading(series, _labels(where, value.get("labels")), reduce, age)


def condition(name: str, s: object, every: float, max_age: float) -> Condition:
    where = f'[desk.conditions."{name}"]'
    if not _NAME.match(name):
        raise ConfigError(f"{where}: a condition's name is lowercase letters, digits, . _ and - (reviews-wait)")
    if not isinstance(s, dict):
        raise ConfigError(f"{where} must be a table")
    unknown = set(s) - CONDITION_KEYS
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {', '.join(sorted(unknown))} (it takes {', '.join(sorted(CONDITION_KEYS))})")
    statement = s.get("statement")
    if not isinstance(statement, str) or not statement.strip() or len(statement) > 200:
        raise ConfigError(f"{where} statement must say, in under 200 characters, what should hold")
    severity = s.get("severity", "medium")
    if severity not in SEVERITIES:
        raise ConfigError(f"{where} severity must be one of {', '.join(SEVERITIES)}, not {severity!r}")
    link = _link(where, s.get("link"))
    checks = [k for k in ("series", "expr", "command") if k in s]
    if len(checks) != 1:
        raise ConfigError(f"{where} needs exactly one check: series (one series), expr (an expression over vars) "
                          f"or command (a script){'; it has ' + ', '.join(checks) if checks else ''}")
    base = {"name": name, "statement": statement.strip(), "severity": severity, "link": link}
    if checks == ["command"]:
        for k in ("holds", "labels", "reduce", "max_age", "when_missing", "vars"):
            if k in s:
                raise ConfigError(f"{where} {k} is not for a script condition: the script says whether it holds")
        cmd = s["command"]
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        if not isinstance(cmd, list) or not cmd or not all(isinstance(a, str) and a for a in cmd):
            raise ConfigError(f"{where} command must be a list of arguments (or a string split like a shell would)")
        timeout = _duration(f"{where} timeout", s.get("timeout"), min(DEFAULT_TIMEOUT, every - 5), 1, every - 5)
        return Condition(**base, check="script", command=tuple(cmd), timeout=timeout)
    if "timeout" in s:
        raise ConfigError(f"{where} timeout is only for a script condition")
    try:
        holds = comparison(s.get("holds"))
    except LanguageError as e:
        raise ConfigError(f"{where} {e}") from None
    when_missing = s.get("when_missing", "unknown")
    if when_missing not in MISSING:
        raise ConfigError(f"{where} when_missing must be one of {', '.join(MISSING)}, not {when_missing!r}")
    if checks == ["series"]:
        if "vars" in s:
            raise ConfigError(f"{where} vars is only for an expr condition")
        r = reading(where, {k: s[k] for k in READING_KEYS if k in s}, max_age)
        return Condition(**base, check="series", readings={"value": r}, holds=holds, when_missing=when_missing)
    for k in ("labels", "reduce", "max_age"):
        if k in s:
            raise ConfigError(f"{where} {k} belongs in each of vars, not beside expr")
    try:
        expr = expression(s["expr"])
    except LanguageError as e:
        raise ConfigError(f"{where} {e}") from None
    raw_vars = s.get("vars")
    if not isinstance(raw_vars, dict) or not raw_vars:
        raise ConfigError(f"{where} needs vars: a table naming the reading behind each name in expr")
    readings = {}
    for var, v in raw_vars.items():
        if not _VAR.match(var) or var in ("min", "max", "abs"):
            raise ConfigError(f"{where} vars: {var!r} is not a usable name")
        readings[var] = reading(f"{where} vars.{var}", v, max_age)
    if missing := sorted(expr.names - set(readings)):
        raise ConfigError(f"{where} expr names {', '.join(missing)}, which vars does not define")
    if unused := sorted(set(readings) - expr.names):
        raise ConfigError(f"{where} vars defines {', '.join(unused)}, which expr does not use")
    return Condition(**base, check="expr", readings=readings, expr=expr, holds=holds, when_missing=when_missing)


def rule(type_: str, s: object) -> Rule | None:
    where = f'[desk.ledger.types."{type_}"]'
    if not _TYPE.match(type_):
        raise ConfigError(f"{where}: an event type is letters, digits, . _ and -")
    if not isinstance(s, dict):
        raise ConfigError(f"{where} must be a table")
    unknown = set(s) - RULE_KEYS
    if unknown:
        raise ConfigError(f"{where} has unknown keys: {', '.join(sorted(unknown))} (it takes {', '.join(sorted(RULE_KEYS))})")
    if s.get("ignore") is True:
        if set(s) - {"ignore"}:
            raise ConfigError(f"{where} ignore = true takes no other keys")
        return None
    if "ignore" in s and s["ignore"] is not False:
        raise ConfigError(f"{where} ignore must be true or false")
    kind = s.get("kind")
    if not isinstance(kind, str) or not _KIND.match(kind) or kind == "condition":
        raise ConfigError(f"{where} kind must be a short lowercase word (landed, merged, ...), and not \"condition\" "
                          f"(the Desk's own)")
    label = s.get("label", "{subject}")
    link = s.get("link")
    for key, t in (("label", label), ("link", link)):
        if t is None:
            continue
        if not isinstance(t, str) or not t:
            raise ConfigError(f"{where} {key} must be a non-empty template")
        try:
            placeholders(t)
        except ValueError as e:
            raise ConfigError(f"{where} {key}: {e}") from None
    if link is not None and not link.startswith(("https://", "http://", "/", "{")):
        raise ConfigError(f"{where} link must make an http(s) URL or a path on this Orchestra (/...)")
    sources = s.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(x, str) and _SOURCE.match(x) for x in sources):
        raise ConfigError(f"{where} sources must be a list of sources (person.ana, worker/1)")
    return Rule(type_, kind, label, link, tuple(sources))


def _ledger(s: object, errors: list[str]) -> dict[str, Rule]:
    if s is None:
        return dict(DEFAULTS)
    if not isinstance(s, dict):
        errors.append("[desk.ledger] must be a table")
        return {}
    unknown = set(s) - LEDGER_KEYS
    if unknown:
        errors.append(f"[desk.ledger] has unknown keys: {', '.join(sorted(unknown))} (it takes defaults, types)")
    defaults = s.get("defaults", True)
    if not isinstance(defaults, bool):
        errors.append("[desk.ledger] defaults must be true or false")
        defaults = True
    rules = dict(DEFAULTS) if defaults else {}
    types = s.get("types", {})
    if not isinstance(types, dict):
        errors.append("[desk.ledger.types] must be a table of event types")
        return rules
    for t, v in types.items():
        try:
            r = rule(t, v)
        except ConfigError as e:
            errors.append(str(e))
            continue
        if r is None:
            rules.pop(t, None)
        else:
            rules[t] = r
    return rules


def problems(raw: dict[str, Any]) -> tuple[Settings | None, list[str]]:
    """The settings, and every problem found (each a sentence); settings is None when any."""
    s = section(raw)
    if s is None:
        return None, ["the configuration has no [desk] section"]
    errors: list[str] = []
    unknown = set(s) - DESK_KEYS
    if unknown:
        errors.append(f"[desk] has unknown keys: {', '.join(sorted(unknown))} (it takes {', '.join(sorted(DESK_KEYS))})")
    owner = s.get("owner", [])
    if isinstance(owner, str):
        owner = [owner]
    if not isinstance(owner, list) or not all(isinstance(o, str) and _SOURCE.match(o) for o in owner):
        errors.append("[desk] owner must be a source or a list of sources (person.danroblewis)")
        owner = []
    every = max_age = None
    try:
        every = _duration("[desk] every", s.get("every"), DEFAULT_EVERY, MIN_EVERY, MAX_EVERY)
    except ConfigError as e:
        errors.append(str(e))
    try:
        max_age = _duration("[desk] max_age", s.get("max_age"), DEFAULT_MAX_AGE, 1, 30 * 86400)
    except ConfigError as e:
        errors.append(str(e))
    conditions: dict[str, Condition] = {}
    raw_conditions = s.get("conditions", {})
    if not isinstance(raw_conditions, dict):
        errors.append("[desk.conditions] must be a table of conditions")
        raw_conditions = {}
    for name, v in raw_conditions.items():
        try:
            conditions[name] = condition(name, v, every or DEFAULT_EVERY, max_age or DEFAULT_MAX_AGE)
        except ConfigError as e:
            errors.append(str(e))
    rules = _ledger(s.get("ledger"), errors)
    if errors:
        return None, errors
    return Settings(tuple(owner), every, max_age, conditions, rules), []


def settings(raw: dict[str, Any]) -> Settings:
    got, errors = problems(raw)
    if errors:
        raise ConfigError("; ".join(errors))
    return got
