"""The Desk as an Orchestra plugin (``orchestra/plugins.py``): its two pages and their API, and, only
in a project whose configuration has ``[desk]``, the reader process ``orchestra run`` keeps running
for the ledger and the instrument it runs for the conditions.

It declares no machine: the reader never announces and never publishes, and the instrument
measures. Orchestra calls ``plugin(project)`` in the web server once, and in ``orchestra run`` each
time the configuration changes, so it does no work and opens nothing."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from orchestra.collect.spec import Collector
from orchestra.config import ConfigError, parse_duration
from orchestra.launcher import Process
from orchestra.plugins import Page, Plugin

from . import PACKAGE
from .config import DEFAULT_EVERY, MAX_EVERY, MIN_EVERY, problems, section

STATIC = Path(__file__).parent / "static"


def every(s: dict) -> float:
    """``[desk] every`` as the instrument's interval; a bad value falls back to the default (the
    instrument then reports the configuration's error itself)."""
    try:
        e = parse_duration(s.get("every"), DEFAULT_EVERY)
    except (ConfigError, ValueError, TypeError):
        return DEFAULT_EVERY
    return e if MIN_EVERY <= e <= MAX_EVERY else DEFAULT_EVERY


def processes(project) -> list[Process]:
    if section(project.config.raw) is None:
        return []
    return [Process("reader", [sys.executable, "-m", "orchestra_desk", "read"], stop_grace_s=5)]


def collectors(project) -> list[Collector]:
    s = section(project.config.raw)
    if s is None:
        return []
    e = every(s)
    return [Collector.collect("conditions", f"{shlex.quote(sys.executable)} -m orchestra_desk measure",
                              every_s=e, timeout_s=e)]


def plugin(project) -> Plugin:
    from .web import router  # FastAPI only where a router is wanted

    return Plugin(
        PACKAGE,
        pages=[Page("/desk", "Desk", STATIC / "desk.html"), Page("/ledger", "Ledger", STATIC / "ledger.html")],
        static=STATIC,
        router=router(project),
        processes=processes(project),
        collectors=collectors(project),
        guide=Path(__file__).parent / "guide.md",   # how to configure it, for an AI operator (/api/guides)
        check=lambda raw, repo_root: problems(raw)[1],   # what project.config_edit refuses in [desk]; none without it
    )
