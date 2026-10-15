"""Retention (D-19): speech text older than retention_days is erased, metadata stays."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

from snow.contracts.events import ReplyFinal, TranscriptFinal, TtsSpoken
from snow.hub.eventlog import EventLog
from tests.conftest import SnowDirs

DAY_NS = 86_400 * 10**9


def _reply(ts_ns: int) -> ReplyFinal:
    return ReplyFinal(
        ts_ns=ts_ns,
        source="brain",
        text="old reply",
        emotion="warm",
        big_moment=False,
        reply_source="llm",
        provider="p",
        model="m",
    )


def test_purge_content_nulls_only_rows_older_than_the_cutoff(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "snow.db")
    now = time.time_ns()
    log.append(TranscriptFinal(ts_ns=now - 40 * DAY_NS, source="dev", text="old words"))
    log.append(_reply(now - 31 * DAY_NS))
    log.append(TranscriptFinal(ts_ns=now - 29 * DAY_NS, source="dev", text="recent"))
    log.append(
        TtsSpoken(ts_ns=now - 40 * DAY_NS, source="voice", engine="cartesia", chars=5)
    )

    erased = log.purge_content(now - 30 * DAY_NS)

    assert erased == 2
    rows = log.rows()
    assert [r["content"] for r in rows] == [None, None, "recent", None]
    assert [r["type"] for r in rows] == [
        "transcript.final",
        "reply.final",
        "transcript.final",
        "tts.spoken",
    ]
    assert log.purge_content(now - 30 * DAY_NS) == 0, "idempotent"
    log.close()


def test_purged_rows_keep_their_metadata_and_replay_does_not_crash(
    tmp_path: Path,
) -> None:
    log = EventLog(tmp_path / "snow.db")
    now = time.time_ns()
    log.append(_reply(now - 40 * DAY_NS))
    log.purge_content(now - 30 * DAY_NS)
    row = log.rows()[0]
    assert json.loads(row["payload"])["provider"] == "p"
    assert row["ts_ns"] == now - 40 * DAY_NS
    assert log.replay(0) == [], "a row without its text is skipped, not fatal"
    log.close()


async def test_a_starting_hub_purges_old_transcripts(snow_dirs: SnowDirs) -> None:
    db = snow_dirs.data / "data" / "snow.db"
    seeded = EventLog(db)
    now = time.time_ns()
    seeded.append(
        TranscriptFinal(ts_ns=now - 45 * DAY_NS, source="dev", text="ancient")
    )
    seeded.append(TranscriptFinal(ts_ns=now - 1 * DAY_NS, source="dev", text="fresh"))
    seeded.close()
    (snow_dirs.config / "snow.toml").write_text(
        "[hub]\nallowed_origins = []\nretention_days = 30\n", encoding="utf-8"
    )
    env = {**os.environ, "SNOW_HUB_MUTEX": f"Local\\SnowHubTest{uuid.uuid4().hex}"}
    hub = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "snow.hub"], env=env, stdout=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            assert hub.poll() is None, "hub exited early"
            assert time.monotonic() < deadline, "old transcript was never purged"
            con = sqlite3.connect(db, timeout=5)
            try:
                contents = [
                    r[0] for r in con.execute("SELECT content FROM events ORDER BY seq")
                ]
            finally:
                con.close()
            if contents[:2] == [None, "fresh"]:
                break
            await asyncio.sleep(0.2)
    finally:
        for p in [
            *psutil.Process(hub.pid).children(recursive=True),
            psutil.Process(hub.pid),
        ]:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        hub.wait(10)
