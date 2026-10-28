"""A condition's readings, taken from Orchestra's metrics store (``orchestra.metrics``, never its
files): every series of this project with the reading's name and labels, the latest point of each,
the points older than ``max_age`` left out, and what is left reduced to one number."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Reading


@dataclass(frozen=True)
class Taken:
    value: float | None               # None: missing (no series, or none fresh enough)
    evidence: str                     # what was read, in a line, for the board


def _ago(seconds: float) -> str:
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= n:
            return f"{seconds / n:.0f}{unit}"
    return f"{seconds:.0f}s"


def take(store, project_key: str, r: Reading, now: float) -> Taken:
    labels = {**dict(r.labels), "project": project_key}
    found = [(n, lab) for n, lab in store.series(r.series, labels) if n == r.series]
    fresh: list[float] = []
    newest: float | None = None
    for n, lab in found:
        p = store.latest(n, lab)
        if p is None:
            continue
        newest = p[0] if newest is None else max(newest, p[0])
        if now - p[0] <= r.max_age:
            fresh.append(p[1])
    sel = r.selector()
    if r.reduce == "count":
        return Taken(float(len(fresh)), f"{sel}: {len(fresh)} series with a point within {_ago(r.max_age)}")
    if not fresh:
        if newest is None:
            return Taken(None, f"{sel}: no such series")
        return Taken(None, f"{sel}: last point {_ago(now - newest)} ago, older than {_ago(r.max_age)}")
    value = {"max": max, "min": min, "sum": sum, "avg": lambda v: sum(v) / len(v)}[r.reduce](fresh)
    many = f" ({r.reduce} of {len(fresh)} series)" if len(fresh) > 1 else ""
    return Taken(float(value), f"{sel} = {value:g}{many}")
