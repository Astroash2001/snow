"""Durable event log: SQLite WAL with numbered SQL migrations (CORE-03)."""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, get_args

from pydantic import TypeAdapter, ValidationError

from snow.contracts.events import ENVELOPE_FIELDS, Envelope, Event

_EVENT: TypeAdapter[Envelope] = TypeAdapter(Event)  # pyright: ignore[reportInvalidTypeArguments]
# type literal -> payload field that was moved into the `content` column.
_CONTENT_FIELDS: dict[str, str] = {
    str(cls.model_fields["type"].default): cls.content_field
    for cls in get_args(get_args(Event)[0])
    if cls.content_field
}

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

    def replay(self, since_ts_ns: int = 0) -> list[Envelope]:
        """Rebuild stored events with ts_ns >= since_ts_ns; unknown types skipped."""
        out: list[Envelope] = []
        query = "SELECT * FROM events WHERE ts_ns >= ? ORDER BY seq"
        for row in self._db.execute(query, (since_ts_ns,)):
            data: dict[str, Any] = {
                k: row[k] for k in row.keys() if k not in ("payload", "content")
            }  # noqa: SIM118 - sqlite3.Row
            data.update(json.loads(row["payload"]))
            field = _CONTENT_FIELDS.get(row["type"])
            if field:
                data[field] = row["content"]
            try:
                out.append(_EVENT.validate_python(data))
            except ValidationError:
                continue
        return out

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

    def purge_content(self, older_than_ns: int) -> int:
        """Erase speech text older than the cutoff; event metadata stays (D-19)."""
        cur = self._db.execute(
            "UPDATE events SET content = NULL WHERE content IS NOT NULL AND ts_ns < ?",
            (older_than_ns,),
        )
        return cur.rowcount

    def close(self) -> None:
        self._db.close()
