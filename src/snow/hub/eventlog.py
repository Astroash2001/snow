"""Durable event log: SQLite WAL with numbered SQL migrations (CORE-03)."""

import json
import re
import sqlite3
from pathlib import Path

from snow.contracts.events import ENVELOPE_FIELDS, Envelope

_MIGRATIONS = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d+)_.*\.sql$")


class EventLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: autocommit, each append is its own transaction.
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        current = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        numbered: list[tuple[int, Path]] = []
        for f in _MIGRATIONS.glob("*.sql"):
            m = _MIGRATION_NAME.match(f.name)
            if m:
                numbered.append((int(m.group(1)), f))
        for number, f in sorted(numbered):
            if number > current:
                self._db.executescript(f.read_text(encoding="utf-8"))
                self._db.execute(f"PRAGMA user_version={number}")

    def append(self, event: Envelope) -> int:
        """Store a durable event and return its seq.

        Speech text lives only in `content` (D-18: text transcripts, never audio);
        every other non-envelope field goes into the JSON `payload`.
        """
        dumped = event.model_dump()
        type_ = str(dumped.pop("type"))
        content_field = type(event).content_field
        content = dumped.pop(content_field) if content_field else None
        payload = {k: v for k, v in dumped.items() if k not in ENVELOPE_FIELDS}
        cur = self._db.execute(
            "INSERT INTO events (ts_ns, type, source, correlation_id, turn_id,"
            " causation_id, user_id, risk_tier, reason, result, payload, content)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event.ts_ns,
                type_,
                event.source,
                event.correlation_id,
                event.turn_id,
                event.causation_id,
                event.user_id,
                event.risk_tier,
                event.reason,
                event.result,
                json.dumps(payload),
                content,
            ),
        )
        seq = cur.lastrowid
        assert seq is not None  # noqa: S101 - INSERT always yields a rowid
        return seq

    def rows(self, types: list[str] | None = None) -> list[sqlite3.Row]:
        if not types:
            return self._db.execute("SELECT * FROM events ORDER BY seq").fetchall()
        marks = ",".join("?" * len(types))
        return self._db.execute(
            f"SELECT * FROM events WHERE type IN ({marks}) ORDER BY seq",  # noqa: S608 - placeholders only
            types,
        ).fetchall()

    def last_seq(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
        return int(row[0])

    def get_state(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_state(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def close(self) -> None:
        self._db.close()
