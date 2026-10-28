"""The ledger: a record of what happened, in SQLite under ``<state>/desk/ledger.db``.

An entry is one event read from the bus that a rule names (``rules.py``), or a change of a
condition (the Desk's own). Its id is the event's id (or ``desk:condition:<name>:<time>``), so
reading the same event twice, after a restart or by two readers at once, keeps one entry. The
reader's place on the bus and the rules it read with are kept beside the entries (``meta``).

The reader (``reader.py``, in the ``desk.reader`` process and in the web server) and the
instrument (a condition's change) write it; every write is one ``BEGIN IMMEDIATE`` transaction."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from . import STATE

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, type TEXT NOT NULL, source TEXT,
  subject TEXT, label TEXT, link TEXT, origin TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_at ON entries (at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Entry:
    id: str
    at: float                         # when it happened (the event's time)
    kind: str                         # landed, merged, reviewed, sent, condition, ...
    type: str                         # the event type, or desk.condition.false / desk.condition.holds
    source: str | None = None         # who acted: the event's source
    subject: str | None = None
    label: str | None = None
    link: str | None = None
    origin: str = "bus"               # "bus", or "desk" for a condition's change

    def view(self, owner: tuple[str, ...] = ()) -> dict:
        return {**asdict(self), "mine": bool(self.source) and self.source.split("/")[0] in owner}


def path_for(state_dir: Path) -> Path:
    return state_dir / STATE / "ledger.db"


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        new = not self.path.exists()
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        if new:
            os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)

    @classmethod
    def for_project(cls, project) -> Ledger:
        return cls(path_for(project.state_dir))

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def record(self, entries: list[Entry], meta: dict[str, str] | None = None, replace: bool = False) -> int:
        """Add the entries (an id already there is kept, or replaced with ``replace``) and set the
        meta keys, in one transaction; returns how many rows were written."""
        verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
        n = 0
        with self.tx() as db:
            for e in entries:
                n += db.execute(f"{verb} INTO entries (id, at, kind, type, source, subject, label, link, origin) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (e.id, e.at, e.kind, e.type, e.source, e.subject, e.label, e.link, e.origin)).rowcount
            for k, v in (meta or {}).items():
                db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (k, v))
        return n

    def entries(self, start: float | None = None, end: float | None = None, kinds: list[str] | None = None,
                limit: int = 2000) -> list[Entry]:
        """Entries in ``[start, end)``, newest first."""
        where, args = [], []
        if start is not None:
            where.append("at >= ?")
            args.append(start)
        if end is not None:
            where.append("at < ?")
            args.append(end)
        if kinds:
            where.append(f"kind IN ({','.join('?' * len(kinds))})")
            args.extend(kinds)
        sql = ("SELECT id, at, kind, type, source, subject, label, link, origin FROM entries"
               + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY at DESC, id LIMIT ?")
        return [Entry(*row) for row in self.db.execute(sql, (*args, limit))]

    def kinds(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT kind FROM entries ORDER BY kind")]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def close(self) -> None:
        self.db.close()
