"""A script condition: a command run in the repository root, under its timeout, by the instrument.

The contract (SPEC §3.3): the first line of its standard output is ``1`` (the condition holds) or
``0`` (it does not); ``true``/``false`` and ``ok``/``fail`` are read the same. The rest of the output,
up to 500 characters, is the reason the board shows. Exit 0 is required: any other exit, a
timeout, or a first line that is none of these makes the condition unknown, with that error.

The reason stays in the Desk's state and on its board: it is never put on the bus or in a metric.
The script gets ``ORCHESTRA_REPO`` and the instrument's environment, so it may read the metrics
store or the bus through Orchestra, as any program may."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Condition

MAX_REASON = 500
HOLDS = {"1": True, "true": True, "ok": True, "0": False, "false": False, "fail": False}


@dataclass(frozen=True)
class Ran:
    holds: bool | None                # None: unknown
    reason: str | None = None         # the script's own words (only when it answered)
    error: str | None = None          # why it is unknown


def argv(command: tuple[str, ...], repo_root: Path) -> list[str]:
    """The command with its program found: a path with a slash is the repository's (or absolute),
    a bare name is looked up on PATH."""
    first = command[0]
    if "/" in first:
        path = Path(first).expanduser()
        return [str(path if path.is_absolute() else repo_root / path), *command[1:]]
    return [shutil.which(first) or first, *command[1:]]


def parse(out: str) -> Ran:
    lines = out.strip().splitlines()
    if not lines:
        return Ran(None, error="printed nothing (the first line must be 1 or 0)")
    first = lines[0].strip().lower()
    if first not in HOLDS:
        return Ran(None, error=f"first line must be 1 or 0, not {lines[0].strip()[:40]!r}")
    reason = "\n".join(lines[1:]).strip()[:MAX_REASON] or None
    return Ran(HOLDS[first], reason)


def run(c: Condition, repo_root: Path) -> Ran:
    cmd = argv(c.command, repo_root)
    env = {**os.environ, "ORCHESTRA_REPO": str(repo_root), "DESK_CONDITION": c.name}
    try:
        p = subprocess.Popen(cmd, cwd=repo_root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, text=True)
    except OSError as e:
        return Ran(None, error=f"cannot run {c.command[0]}: {e.strerror or e}")
    try:
        out, err = p.communicate(timeout=c.timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.communicate()
        return Ran(None, error=f"took longer than {c.timeout:g}s; stopped")
    if p.returncode != 0:
        tail = (err or "").strip().splitlines()[-1:] or [""]
        return Ran(None, error=f"exited {p.returncode}" + (f": {tail[0][:200]}" if tail[0] else ""))
    return parse(out)
