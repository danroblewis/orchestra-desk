"""The ledger's rules: which event types on the bus become ledger entries, of which kind, with which
label and link. A rule reads the envelope (type, source, subject, id, time) and, for the event
types other packages publish as a protocol for listeners, the ``data`` keys its templates name,
nothing else (Orchestra's rule 3 and PLUGINS.md §7).

A template is text with placeholders in braces: ``{type}``, ``{source}``, ``{subject}``, ``{id}``,
``{repo}`` and ``{number}`` (from a subject shaped ``owner/name#7``, as the GitHub bridge names a
pull request or issue), and ``{data.<key>}`` (a string or number in the event's data). A template
with a placeholder the event cannot fill renders to nothing: the entry then has no link, or its
label falls back to the subject or the type."""

from __future__ import annotations

import re
from dataclasses import dataclass

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_DATA_KEY = re.compile(r"^data\.[A-Za-z_][A-Za-z0-9_]*$")
_ITEM = re.compile(r"^([^/#\s]+/[^#\s]+)#(\d+)$")
ENVELOPE = ("type", "source", "subject", "id", "repo", "number")


@dataclass(frozen=True)
class Rule:
    type: str
    kind: str
    label: str = "{subject}"
    link: str | None = None
    sources: tuple[str, ...] = ()       # empty: any source


GH = "https://github.com/{repo}/pull/{number}"
GH_ISSUE = "https://github.com/{repo}/issues/{number}"
TICKET = "/tickets#ticket={data.ticket}"

# The built-in rules, for the event types the other plugins publish (their SPECs): the task
# system's landings, tickets and approvals, the GitHub bridge's pull requests, reviews and issues,
# and the Outbox's sends. ``[desk.ledger] defaults = false`` drops them all; a rule in
# ``[desk.ledger.types]`` replaces the built-in rule for its type, and ``ignore = true`` drops it.
DEFAULTS: dict[str, Rule] = {r.type: r for r in (
    Rule("gate.landed", "landed", "{data.ticket}", TICKET),
    Rule("ticket.created", "ticket", "{data.ticket}", TICKET),
    Rule("review.approved", "reviewed", "{data.ticket}", TICKET),
    Rule("github.pr.opened", "opened", "{subject}", GH),
    Rule("github.pr.merged", "merged", "{subject}", GH),
    Rule("github.pr.review_submitted", "reviewed", "{subject}", GH),
    Rule("github.issue.closed", "closed", "{subject}", GH_ISSUE),
    Rule("outbox.sent", "sent", "{data.kind}", "/outbox"),
)}


def placeholders(template: str) -> list[str]:
    """The placeholders of a template; raises ``ValueError`` for one that is not known."""
    if template.count("{") != template.count("}"):
        raise ValueError(f"unbalanced braces in {template!r}")
    names = _PLACEHOLDER.findall(template)
    for n in names:
        if n not in ENVELOPE and not _DATA_KEY.match(n):
            raise ValueError(f"unknown placeholder {{{n}}} in {template!r} "
                             f"(use {', '.join('{' + e + '}' for e in ENVELOPE)} or {{data.<key>}})")
    return names


def fields(ev: dict) -> dict[str, str]:
    """What an event offers the templates: its envelope, and its subject's repo and number."""
    out = {k: str(ev[k]) for k in ("type", "source", "subject", "id") if isinstance(ev.get(k), str) and ev[k]}
    if m := _ITEM.match(out.get("subject", "")):
        out["repo"], out["number"] = m.group(1), m.group(2)
    return out


def safe_link(url: str | None) -> str | None:
    """A link the pages may follow: http(s), or a path on this Orchestra; anything else is dropped."""
    if url and (url.startswith(("https://", "http://")) or (url.startswith("/") and not url.startswith("//"))):
        return url
    return None


def render(template: str | None, ev: dict) -> str | None:
    """The template filled from the event, or None when a placeholder cannot be filled."""
    if not template:
        return None
    env = fields(ev)
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    missing = False

    def one(m: re.Match) -> str:
        nonlocal missing
        name = m.group(1)
        if name.startswith("data."):
            v = data.get(name[5:])
            if isinstance(v, bool) or not isinstance(v, str | int | float) or v == "":
                missing = True
                return ""
            return str(v)
        if name not in env:
            missing = True
            return ""
        return env[name]

    out = _PLACEHOLDER.sub(one, template)
    return None if missing else out
