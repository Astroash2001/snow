"""Hard mute (D-10, VOIC-03): the stream is closed and only a click reopens it."""

import asyncio
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]
from websockets.asyncio.client import connect

from snow.common.hubclient import HubClient
from snow.contracts.events import (
    ConversationEnded,
    MuteChanged,
    PresenceState,
    TranscriptFinal,
    TurnCancelled,
)
from snow.voice import sources
from snow.voice.sources import FileSource, Frame, MicSource, OnFrame
from tests.conftest import HubHandle
from tests.voice.conftest import (
    FakeGroq,
    FakeHub,
    RunFixture,
    StubSource,
    make_pipeline,
    until,
)


class RecordingFile(FileSource):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.calls: list[str] = []

    def open(self, on_frame: OnFrame) -> None:
        self.calls.append("open")
        super().open(on_frame)

    def close(self) -> None:
        self.calls.append("close")
        super().close()


# --- the spoken command -----------------------------------------------------------


async def test_say_mute_closes_the_source_and_reaches_the_brain_never(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    run = await run_fixture(
        "phrase_mute", "Hey Jarvis, mute.", source_factory=RecordingFile
    )
    assert isinstance(run.source, RecordingFile)
    assert run.source.calls == ["open", "close", "close"]  # mute, then stop()
    changed = [e for e in run.hub.events if isinstance(e, MuteChanged)]
    assert [(e.muted, e.by) for e in changed] == [(True, "voice")]
    presence = [e.state for e in run.hub.events if isinstance(e, PresenceState)]
    assert presence[-1] == "muted"
    ended = [e for e in run.hub.events if isinstance(e, ConversationEnded)]
    assert [e.end_reason for e in ended] == ["mute"]
    assert not any(isinstance(e, TranscriptFinal) for e in run.hub.events)
    assert not any(isinstance(e, TurnCancelled) for e in run.hub.events)
    run.engine.drain()  # the audio thread would, on its next frame
    assert run.engine.state.value == "muted"


async def test_mute_inside_a_sentence_does_not_mute(
    run_fixture: RunFixture,
) -> None:
    run = await run_fixture(
        "phrase_mute_substring",
        "Hey Jarvis, mute the speaker in the call.",
        source_factory=RecordingFile,
    )
    assert isinstance(run.source, RecordingFile)
    assert run.source.calls == ["open", "close"]  # only stop()
    assert "mute.changed" not in run.hub.types()
    assert [e.text for e in run.hub.events if isinstance(e, TranscriptFinal)] == [
        "mute the speaker in the call."
    ]


# --- hub commands and the startup rule (real in-process hub) ----------------------


async def test_hud_commands_close_and_reopen_the_source(
    hub: HubHandle, wake_models: None
) -> None:
    source = StubSource()
    client = HubClient(hub.url, hub.token, role="voice")
    pipeline = make_pipeline(client, source)
    client.on_command = pipeline.on_command
    client.on_snapshot = pipeline.on_snapshot
    client.on_event = pipeline.on_hub_event
    await pipeline.start(listen=False)
    assert source.calls == []  # never before a snapshot
    runner = asyncio.create_task(client.run())
    async with connect(hub.url) as hud:
        await hud.send(json.dumps({"kind": "hello", "role": "hud", "token": hub.token}))
        await until(lambda: source.calls == ["open"])  # unmuted snapshot opens it

        async def command(muted: bool) -> None:
            body = {"type": "cmd.mute.set", "muted": muted, "by": "hud"}
            await hud.send(json.dumps({"kind": "command", "command": body}))

        await command(True)
        await until(lambda: source.calls == ["open", "close"])
        await until(lambda: hub.log.get_state("mute") == "1")
        await command(False)
        await until(lambda: source.calls == ["open", "close", "open"])
        await until(lambda: hub.log.get_state("mute") == "0")
        changes: list[dict[str, Any]] = []
        async with asyncio.timeout(5):
            while len(changes) < 2:
                msg = json.loads(await hud.recv())
                if msg["kind"] == "event" and msg["event"]["type"] == "mute.changed":
                    changes.append(msg["event"])
    # The HUD was told both times, and who asked.
    assert [(c["muted"], c["by"]) for c in changes] == [(True, "hud"), (False, "hud")]
    runner.cancel()
    await pipeline.stop()


async def test_restart_while_muted_never_opens_the_mic(
    hub: HubHandle, wake_models: None
) -> None:
    # What an earlier session left behind; the hub restores it at start (D-10).
    hub.log.set_state("mute", "1")
    hub.hub._projection.set_muted(True)  # pyright: ignore[reportPrivateUsage]
    source = StubSource()
    client = HubClient(hub.url, hub.token, role="voice")
    pipeline = make_pipeline(client, source)
    client.on_snapshot = pipeline.on_snapshot
    await pipeline.start(listen=False)
    runner = asyncio.create_task(client.run())
    await until(lambda: pipeline._seen_snapshot)  # pyright: ignore[reportPrivateUsage]
    assert "open" not in source.calls
    runner.cancel()
    await pipeline.stop()


async def test_no_hub_connection_keeps_the_mic_closed(wake_models: None) -> None:
    source = StubSource()
    pipeline = make_pipeline(FakeHub(), source)
    await pipeline.start(listen=False)
    await asyncio.sleep(0.2)
    assert source.calls == []
    await pipeline.stop()


async def test_a_lost_mute_report_is_resent_not_silently_undone(
    wake_models: None,
) -> None:
    from snow.contracts.wire import Snapshot

    hub, source = FakeHub(), StubSource()
    pipeline = make_pipeline(hub, source)
    await pipeline.start(listen=False)
    await pipeline.on_snapshot(Snapshot())
    await pipeline._set_muted(True, "voice")  # pyright: ignore[reportPrivateUsage]
    await pipeline.wait_done()  # flush the first report
    hub.events.clear()
    await pipeline.on_snapshot(Snapshot(muted=False))  # reconnect: hub missed it
    await pipeline.wait_done()
    assert source.calls == ["open", "close"]  # still closed
    assert [(e.muted, e.by) for e in hub.events if isinstance(e, MuteChanged)] == [
        (True, "voice")
    ]
    await pipeline.stop()


# --- health rows ------------------------------------------------------------------


async def test_health_rows_for_wake_word_and_speech_to_text(wake_models: None) -> None:
    hub = FakeHub()
    pipeline = make_pipeline(hub, StubSource(), key=False)
    await pipeline.start(listen=False)
    await pipeline.wait_done()
    rows = {h.name: (h.status, h.detail, h.label, h.owner) for h in hub.health}
    assert rows["speech_to_text"] == (
        "down",
        "No Groq key. Run snow setup.",
        "Speech to text",
        "voice",
    )
    assert rows["wake_word"] == ("running", None, "Wake word", "voice")
    pipeline.mic_health(False)
    pipeline.mic_health(True)
    await asyncio.sleep(0.05)
    await pipeline.wait_done()
    wake = [(h.status, h.detail) for h in hub.health if h.name == "wake_word"]
    assert wake[-2:] == [("restarting", "Microphone unavailable"), ("running", None)]
    await pipeline.stop()


# --- the microphone itself (Pitfall 10) -------------------------------------------


class FakeStream:
    """sounddevice.InputStream stand-in: fails to start `fail` times, then works."""

    fail = 0
    live: "FakeStream | None" = None

    def __init__(self, **kw: Any) -> None:
        self.callback = kw["callback"]
        self.finished = kw["finished_callback"]

    def start(self) -> None:
        if FakeStream.fail > 0:
            FakeStream.fail -= 1
            raise sd.PortAudioError("Invalid device")
        FakeStream.live = self

    def stop(self) -> None: ...

    def close(self) -> None: ...


def wait_for(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_mic_reopens_with_backoff_after_open_failure_and_unplug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources.sd, "InputStream", FakeStream)
    monkeypatch.setattr(sources, "_wasapi_input", lambda _name: None)
    monkeypatch.setattr(sources, "_REOPEN_START_S", 0.01)
    FakeStream.fail, FakeStream.live = 2, None
    health: list[bool] = []
    frames: list[Frame] = []
    done = threading.Event()
    mic = MicSource()
    mic.on_health = health.append
    mic.open(lambda f: (frames.append(f), done.set()))
    try:
        wait_for(lambda: FakeStream.live is not None)
        assert health == [False, False, True]  # two failed opens, then it runs
        live = FakeStream.live
        assert live is not None
        live.callback(np.ones((1280, 1), dtype=np.int16))
        wait_for(lambda: len(frames) == 1)
        # Unplugged: PortAudio ends the stream on its own.
        FakeStream.live = None
        live.finished()
        wait_for(lambda: FakeStream.live is not None)
        assert health == [False, False, True, False, True]
        FakeStream.live.callback(np.ones((1280, 1), dtype=np.int16))
        wait_for(lambda: len(frames) == 2)
    finally:
        mic.close()
    assert not mic.is_open
