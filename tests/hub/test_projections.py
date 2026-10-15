"""Projection reducer and the hub's snapshot-first / mute-persistence behaviour."""

import json
import time
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from snow.contracts.events import (
    ConversationEnded,
    ConversationStarted,
    HealthProvider,
    LlmSwitch,
    MuteChanged,
    PresenceState,
    ReplyFinal,
    ReplyInterrupted,
    TranscriptFinal,
    TtsSpoken,
)
from snow.hub.eventlog import EventLog
from snow.hub.projections import Projection
from snow.hub.server import Hub

NOW = time.time_ns()


def _reply(text: str, turn: str | None = "t1", seq: int | None = None) -> ReplyFinal:
    return ReplyFinal(
        seq=seq,
        ts_ns=NOW,
        source="brain",
        turn_id=turn,
        text=text,
        emotion="neutral",
        big_moment=False,
        reply_source="llm",
    )


def test_rows_follow_the_conversation_and_clear_on_end() -> None:
    p = Projection()
    p.apply(
        ConversationStarted(
            seq=1, ts_ns=NOW, source="voice", trigger="wake", correlation_id="c1"
        )
    )
    p.apply(TranscriptFinal(seq=2, ts_ns=NOW, source="voice", turn_id="t1", text="hi"))
    p.apply(_reply("hello", seq=3))
    snap = p.snapshot()
    assert snap.conversation_id == "c1"
    assert [(r.kind, r.text) for r in snap.rows] == [("user", "hi"), ("snow", "hello")]
    p.apply(ConversationEnded(seq=4, ts_ns=NOW, source="voice", end_reason="silence"))
    snap = p.snapshot()
    assert snap.rows == []
    assert snap.conversation_id is None
    assert snap.last_seq == 4


def test_empty_reply_adds_no_row() -> None:
    p = Projection()
    p.apply(_reply(""))
    assert p.snapshot().rows == []


def test_interrupted_reply_keeps_only_the_spoken_text() -> None:
    p = Projection()
    p.apply(_reply("a long answer here", seq=1))
    p.apply(
        ReplyInterrupted(
            seq=2, ts_ns=NOW, source="voice", turn_id="t1", spoken_text="a long"
        )
    )
    (row,) = p.snapshot().rows
    assert (row.text, row.interrupted, row.kind) == ("a long", True, "snow")


def test_llm_switch_becomes_a_system_row() -> None:
    p = Projection()
    p.apply(
        LlmSwitch(
            seq=1,
            ts_ns=NOW,
            source="brain",
            role="brain",
            from_provider="a",
            from_model="m1",
            to_provider="b",
            to_model="m2",
            switch_reason="rate_limit",
        )
    )
    (row,) = p.snapshot().rows
    assert row.kind == "system"
    assert row.system_event == "llm.switch"
    assert "reason=rate_limit" in row.text


def test_health_replaces_in_place_and_cartesia_chars_sum() -> None:
    p = Projection()
    for status in ("ready", "failing"):
        p.apply(
            HealthProvider(
                ts_ns=NOW, source="brain", provider="groq", label="Groq", status=status
            )
        )
    p.apply(
        HealthProvider(
            ts_ns=NOW, source="brain", provider="nim", label="NIM", status="ready"
        )
    )
    p.apply(TtsSpoken(ts_ns=NOW, source="voice", engine="cartesia", chars=40))
    p.apply(TtsSpoken(ts_ns=NOW, source="voice", engine="pocket_tts", chars=999))
    p.apply(TtsSpoken(ts_ns=NOW, source="voice", engine="cartesia", chars=2))
    old = NOW - 3 * 86_400 * 10**9
    p.apply(TtsSpoken(ts_ns=old, source="voice", engine="cartesia", chars=7))
    snap = p.snapshot()
    assert [(h.provider, h.status) for h in snap.providers] == [
        ("groq", "failing"),
        ("nim", "ready"),
    ]
    assert snap.cartesia_chars_today == 42


def test_presence_and_mute() -> None:
    p = Projection()
    p.apply(
        PresenceState(ts_ns=NOW, source="voice", state="thinking", mode="soft_sleep")
    )
    p.apply(MuteChanged(ts_ns=NOW, source="voice", muted=True, by="voice"))
    snap = p.snapshot()
    assert (snap.presence, snap.mode, snap.muted) == ("thinking", "soft_sleep", True)


# --- hub behaviour -------------------------------------------------------------


async def _connect(hub: Hub, run_dir: Path, role: str) -> ClientConnection:
    info: dict[str, Any] = json.loads(
        (run_dir / "hub.json").read_text(encoding="utf-8")
    )
    ws = await connect(f"ws://127.0.0.1:{hub.port}")
    await ws.send(json.dumps({"kind": "hello", "role": role, "token": info["token"]}))
    return ws


def _mute_cmd(by: str) -> str:
    cmd = {"type": "cmd.mute.set", "muted": True, "by": by}
    return json.dumps({"kind": "command", "command": cmd})


async def test_mute_without_voice_worker_persists_and_survives_restart(
    tmp_path: Path,
) -> None:
    db, run_dir = tmp_path / "snow.db", tmp_path / "run"
    log = EventLog(db)
    hub = Hub(log, allowed_origins=[], run_dir=run_dir)
    await hub.start()
    ws = await _connect(hub, run_dir, "hud")
    assert json.loads(await ws.recv())["snapshot"]["muted"] is False
    await ws.send(_mute_cmd("hud"))
    event = json.loads(await ws.recv())["event"]
    assert (event["type"], event["by"], event["source"], event["muted"]) == (
        "mute.changed",
        "hud",
        "hub",
        True,
    )
    assert log.get_state("mute") == "1"
    await ws.close()
    await hub.stop()
    log.close()

    log2 = EventLog(db)
    hub2 = Hub(log2, allowed_origins=[], run_dir=run_dir)
    await hub2.start()
    late = await _connect(hub2, run_dir, "hud")
    snap = json.loads(await late.recv())["snapshot"]
    assert snap["muted"] is True
    assert snap["last_seq"] == 1
    await late.close()
    await hub2.stop()
    log2.close()


async def test_mute_command_is_routed_to_the_voice_worker(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    log = EventLog(tmp_path / "snow.db")
    hub = Hub(log, allowed_origins=[], run_dir=run_dir)
    await hub.start()
    voice = await _connect(hub, run_dir, "voice")
    hud = await _connect(hub, run_dir, "hud")
    await voice.recv()
    await hud.recv()
    await hud.send(_mute_cmd("tray"))
    routed = json.loads(await voice.recv())
    assert routed["command"] == {"type": "cmd.mute.set", "muted": True, "by": "tray"}
    assert log.rows(["mute.changed"]) == []  # the voice worker, not the hub, reports it
    await voice.close()
    await hud.close()
    await hub.stop()
    log.close()


async def test_snapshot_replays_todays_rows_and_cmd_snapshot_refreshes(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    log = EventLog(tmp_path / "snow.db")
    log.append(
        TranscriptFinal(
            ts_ns=time.time_ns(), source="voice", turn_id="t", text="earlier"
        )
    )
    hub = Hub(log, allowed_origins=[], run_dir=run_dir)
    await hub.start()
    dev = await _connect(hub, run_dir, "dev")
    first = json.loads(await dev.recv())
    assert first["kind"] == "snapshot"
    assert [r["text"] for r in first["snapshot"]["rows"]] == ["earlier"]
    say = {"type": "cmd.dev.say", "text": "now"}
    await dev.send(json.dumps({"kind": "command", "command": say}))
    await dev.recv()  # live event
    await dev.send(json.dumps({"kind": "command", "command": {"type": "cmd.snapshot"}}))
    fresh = json.loads(await dev.recv())
    assert [r["text"] for r in fresh["snapshot"]["rows"]] == ["earlier", "now"]
    assert fresh["snapshot"]["last_seq"] == 2
    await dev.close()
    await hub.stop()
    log.close()
