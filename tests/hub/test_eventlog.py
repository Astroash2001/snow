"""EventLog: migration, durable append, content column and replay."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from snow.contracts.events import (
    ReplyFinal,
    ReplyInterrupted,
    Tone,
    TranscriptFinal,
    TtsSpoken,
)
from snow.hub.eventlog import EventLog


def test_migration_sets_user_version_and_append_increases_seq(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "snow.db")
    assert log._db.execute("PRAGMA user_version").fetchone()[0] == 1  # noqa: SLF001
    a = log.append(TranscriptFinal(ts_ns=1, source="dev", text="one"))
    b = log.append(TtsSpoken(ts_ns=2, source="voice", engine="cartesia", chars=5))
    assert (a, b) == (1, 2)
    assert log.last_seq() == 2
    log.close()


def test_speech_text_goes_to_content_never_payload(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "snow.db")
    log.append(TranscriptFinal(ts_ns=1, source="dev", text="secret words"))
    log.append(ReplyInterrupted(ts_ns=2, source="voice", spoken_text="half a sen"))
    first, second = log.rows()
    assert first["content"] == "secret words"
    assert second["content"] == "half a sen"
    for row in (first, second):
        assert "secret" not in row["payload"]
        assert "half" not in row["payload"]
    log.close()


def test_replay_rebuilds_the_stored_events(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "snow.db")
    tone = Tone(pace="fast", loudness="loud", words_per_min=180.0, loudness_dbfs=-12.0)
    sent = [
        TranscriptFinal(
            ts_ns=10, source="voice", text="hi", stt_source="groq", tone=tone
        ),
        ReplyFinal(
            ts_ns=20,
            source="brain",
            text="hello",
            emotion="warm",
            big_moment=False,
            reply_source="llm",
            provider="p",
            model="m",
        ),
        ReplyInterrupted(ts_ns=30, source="voice", spoken_text="hel"),
    ]
    for e in sent:
        log.append(e)
    got = log.replay()
    assert [e.model_dump() | {"seq": None} for e in got] == [
        e.model_dump() | {"seq": None} for e in sent
    ]
    assert [e.seq for e in got] == [1, 2, 3]
    assert [e.ts_ns for e in log.replay(since_ts_ns=20)] == [20, 30]
    log.close()


def test_replay_skips_unknown_event_types(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "snow.db")
    log.append(TranscriptFinal(ts_ns=1, source="dev", text="ok"))
    log._db.execute(  # noqa: SLF001
        "INSERT INTO events (ts_ns, type, source, payload) VALUES (2, 'x.y', 'hub', ?)",
        (json.dumps({}),),
    )
    assert len(log.replay()) == 1
    log.close()


def test_event_with_unknown_extra_field_fails_validation() -> None:
    with pytest.raises(ValidationError):
        TranscriptFinal.model_validate(
            {"ts_ns": 1, "source": "dev", "text": "x", "surprise": 1}
        )
