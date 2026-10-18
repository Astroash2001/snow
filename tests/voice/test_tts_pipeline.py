"""Speech output through the pipeline (SPCH-03/04): fake engine, fake speaker, no sound.

No test here opens a real output device or writes audio anywhere. The one real-model
test is marked `slow`: it synthesizes in memory and plays nothing.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np
import pytest

from snow.config.settings import load_config
from snow.contracts.events import (
    AudioLevel,
    Event,
    HealthSubsystem,
    PresenceState,
    ReplyDelta,
    ReplyFinal,
    TtsSpoken,
    VoiceStatus,
)
from snow.voice import playout
from snow.voice.pipeline import VoicePipeline
from snow.voice.playout import Playout
from snow.voice.tts.base import EngineLoadError, Samples
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.router import VoiceRouter
from tests.voice.conftest import FakeHub, StubSource, make_pipeline, until

RATE = 24000
TTS_CFG = load_config("tts.toml", TtsConfig)


class FakeEngine:
    name = "pocket_tts"
    sample_rate = RATE
    voice_name = "marius"

    def __init__(
        self, *, seconds_per_text: float = 0.5, fail_load: bool = False
    ) -> None:
        self.texts: list[str] = []
        self.emotions: list[str] = []
        self.cancelled = 0
        self._seconds = seconds_per_text
        self._fail_load = fail_load

    def load(self) -> None:
        if self._fail_load:
            raise EngineLoadError

    def cancel(self) -> None:
        self.cancelled += 1

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        self.texts.append(text)
        self.emotions.append(emotion)
        block = np.full(int(RATE * self._seconds / 5), 0.3, dtype=np.float32)
        for _ in range(5):
            await asyncio.sleep(0)
            yield block


class FakeStream:
    def __init__(self, callback: Callable[..., None]) -> None:
        self.callback = callback
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def abort(self) -> None:
        self.calls.append("abort")

    def close(self) -> None:
        self.calls.append("close")

    def pump(self, blocks: int = 1) -> None:
        for _ in range(blocks):
            out = np.zeros((int(RATE * 0.02), 1), dtype=np.float32)
            self.callback(out, len(out), None, None)


class Speaker:
    """The fake output device; `pump` plays 20 ms blocks as a real one would."""

    def __init__(self) -> None:
        self.stream: FakeStream | None = None

    def factory(
        self, rate: int, block: int, callback: Callable[..., None]
    ) -> FakeStream:
        assert rate == RATE
        self.stream = FakeStream(callback)
        return self.stream


class StubTurnEngine:
    """Stands in for TurnEngine: reply_finished leads to the listening state."""

    def __init__(self, pipeline: VoicePipeline) -> None:
        self.pipeline = pipeline
        self.finished = 0
        self.waiting = True

    def reply_finished(self) -> None:
        self.finished += 1
        if self.waiting:
            self.pipeline.on_presence("listening")

    def mute(self) -> None: ...

    def unmute(self) -> None: ...

    def set_speaking(self, speaking: bool) -> None: ...

    def drain(self) -> None: ...


async def setup(
    engine: FakeEngine | None = None, *, waiting: bool = True
) -> tuple[VoicePipeline, FakeHub, FakeEngine, Speaker, StubTurnEngine]:
    engine = engine or FakeEngine()
    hub, speaker = FakeHub(), Speaker()
    pipeline = make_pipeline(hub, StubSource())
    pipeline._tts = VoiceRouter({"pocket_tts": engine}, TTS_CFG, pipeline._emit)  # noqa: SLF001
    pipeline._tts_cfg = TTS_CFG  # noqa: SLF001
    pipeline._stream_factory = speaker.factory  # noqa: SLF001
    turn = StubTurnEngine(pipeline)
    turn.waiting = waiting
    pipeline._engine = turn  # type: ignore[assignment]  # noqa: SLF001
    await pipeline.start()
    if waiting:
        pipeline._pending = "t1"  # noqa: SLF001 - a turn is waiting for this reply
    await until(pipeline._tts_ready.is_set)  # noqa: SLF001
    return pipeline, hub, engine, speaker, turn


def delta(text: str, turn: str | None = "t1") -> ReplyDelta:
    return ReplyDelta(ts_ns=0, source="brain", turn_id=turn, text=text)


def final(text: str, turn: str | None = "t1", source: str = "llm") -> ReplyFinal:
    return ReplyFinal(
        ts_ns=0,
        source="brain",
        turn_id=turn,
        text=text,
        emotion="calm",
        big_moment=False,
        reply_source=source,  # type: ignore[arg-type]
    )


async def play_out(pipeline: VoicePipeline, hub: FakeHub, speaker: Speaker) -> None:
    """Pump the fake speaker until the reply has drained."""
    async with asyncio.timeout(5):
        while pipeline._reply is not None:  # noqa: SLF001
            await asyncio.sleep(0.001)
            if speaker.stream is not None:
                speaker.stream.pump()
    await pipeline._q.join()  # noqa: SLF001


def of(hub: FakeHub, cls: type[Event]) -> list[Any]:
    return [e for e in hub.events if isinstance(e, cls)]


async def test_a_reply_is_spoken_and_the_orb_follows() -> None:
    pipeline, hub, engine, speaker, turn = await setup()
    await pipeline.on_hub_event(delta("Sure, I can do that. "))
    await pipeline.on_hub_event(delta("Second sentence here."))
    await pipeline.on_hub_event(final("Sure, I can do that. Second sentence here."))
    await play_out(pipeline, hub, speaker)

    assert engine.texts == ["Sure, I can do that.", "Second sentence here."]
    assert engine.emotions[-1] == "calm"
    states = [e.state for e in of(hub, PresenceState)]
    assert states == ["speaking", "listening"]
    spoken = of(hub, TtsSpoken)
    assert len(spoken) == 1
    assert spoken[0].engine == "pocket_tts"
    assert spoken[0].chars == sum(len(t) for t in engine.texts)
    assert spoken[0].first_audio_ms is not None
    assert turn.finished == 1  # the wait ends at the end of playback, once
    assert pipeline._pending is None  # noqa: SLF001


async def test_tts_levels_flow_only_while_speaking() -> None:
    pipeline, hub, _engine, speaker, _turn = await setup()
    await pipeline.on_hub_event(delta("Hello there, my friend."))
    await pipeline.on_hub_event(final("Hello there, my friend."))
    await play_out(pipeline, hub, speaker)
    speaker.stream.pump(5)  # type: ignore[union-attr] - after the drain
    await pipeline._q.join()  # noqa: SLF001

    order = [e.type for e in hub.events if e.type in ("presence.state", "audio.level")]
    first, last = (
        order.index("presence.state"),
        len(order) - 1 - order[::-1].index("presence.state"),
    )
    assert order[:first] == [] and order[last + 1 :] == []
    levels = of(hub, AudioLevel)
    assert levels
    assert all(e.channel == "tts" and 0.0 < e.level <= 1.0 for e in levels)


async def test_an_empty_reply_stays_silent() -> None:
    pipeline, hub, engine, speaker, turn = await setup()
    await pipeline.on_hub_event(final(""))
    await pipeline._q.join()  # noqa: SLF001

    assert engine.texts == []
    assert speaker.stream is None  # the speaker was never even opened
    assert of(hub, PresenceState) == []
    assert of(hub, TtsSpoken) == []
    assert turn.finished == 1  # the engine listens at once


async def test_markdown_code_and_links_are_never_spoken() -> None:
    pipeline, hub, engine, speaker, _turn = await setup()
    await pipeline.on_hub_event(delta("**Done.** Open https://example.com/x now. "))
    await pipeline.on_hub_event(delta("```py\nprint(1)\n``` \U0001f600 All set."))
    await pipeline.on_hub_event(final("x"))
    await play_out(pipeline, hub, speaker)

    spoken = " ".join(engine.texts)
    assert spoken == "Done. Open now. All set."
    assert of(hub, TtsSpoken)[0].chars == sum(len(t) for t in engine.texts)


async def test_a_wake_acknowledgement_has_no_deltas_and_is_still_spoken() -> None:
    pipeline, hub, engine, speaker, turn = await setup(waiting=False)
    await pipeline.on_hub_event(final("Yes?", turn=None, source="ack_pool"))
    await play_out(pipeline, hub, speaker)

    assert engine.texts == ["Yes?"]
    assert [e.state for e in of(hub, PresenceState)] == ["speaking", "listening"]
    assert turn.finished == 1


async def test_muting_mid_reply_silences_it_at_once() -> None:
    pipeline, hub, engine, speaker, turn = await setup()
    await pipeline.on_hub_event(delta("A long answer, with many words. "))
    await until(lambda: speaker.stream is not None and bool(engine.texts))
    await pipeline._set_muted(True, "hud")  # noqa: SLF001
    await pipeline._q.join()  # noqa: SLF001

    assert speaker.stream is not None and "abort" in speaker.stream.calls
    assert engine.cancelled >= 1
    assert pipeline._reply is None  # noqa: SLF001
    assert of(hub, TtsSpoken) == []
    assert turn.finished == 0


async def test_a_voice_that_fails_to_load_is_reported_and_replies_stay_silent() -> None:
    pipeline, hub, engine, speaker, turn = await setup(FakeEngine(fail_load=True))
    await pipeline.on_hub_event(delta("Hello there, my friend."))
    await pipeline.on_hub_event(final("Hello there, my friend."))
    await until(lambda: turn.finished == 1)
    await pipeline._q.join()  # noqa: SLF001

    rows = [h for h in hub.health if h.name == "speech_output"]
    assert rows[0].status == "starting" and rows[-1].status == "down"
    assert engine.texts == [] and speaker.stream is None
    assert [e.state for e in of(hub, PresenceState)] == ["listening"]  # never speaking


async def test_voice_status_and_health_are_published_at_start() -> None:
    pipeline, hub, _engine, _speaker, _turn = await setup()
    await pipeline._q.join()  # noqa: SLF001

    status = of(hub, VoiceStatus)
    assert status
    assert (status[0].engine, status[0].voice_name) == ("pocket_tts", "marius")
    assert (status[0].voice_role, status[0].cartesia_available) == ("everyday", False)
    row = [h for h in hub.health if h.name == "speech_output"][-1]
    assert isinstance(row, HealthSubsystem)
    assert (row.label, row.owner, row.status) == ("Speech output", "voice", "running")


async def test_playout_waits_for_the_prebuffer_and_drains_exactly() -> None:
    speaker, log = Speaker(), []
    cfg = TTS_CFG.playout  # 300 ms
    playout = Playout(
        RATE,
        cfg,
        on_first_audio=lambda ts: log.append("first"),
        on_level=lambda level: log.append("level"),
        on_drained=lambda: log.append("drained"),
        stream_factory=speaker.factory,
    )
    playout.start_utterance()
    assert speaker.stream is not None
    playout.push(np.full(int(RATE * 0.2), 0.5, dtype=np.float32))
    speaker.stream.pump(5)
    assert log == []  # 200 ms is under the 300 ms prebuffer: nothing plays
    playout.push(np.full(int(RATE * 0.2), 0.5, dtype=np.float32))
    speaker.stream.pump(5)
    assert log[0] == "first" and "drained" not in log
    playout.end_utterance()
    speaker.stream.pump(20)  # 400 ms in total, 100 ms already played
    assert log.count("drained") == 1 and log.count("first") == 1
    playout.abort()
    assert speaker.stream.calls[-2:] == ["abort", "start"]


@pytest.mark.slow
def test_speaker_stream_opens_on_the_wasapi_default_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PortAudio's default output is MME; WasapiSettings there fails with -9984.
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        playout.sd,
        "query_hostapis",
        lambda: [
            {"name": "MME", "default_output_device": 3},
            {"name": "Windows WASAPI", "default_output_device": 11},
        ],
    )
    monkeypatch.setattr(playout.sd, "OutputStream", lambda **kw: seen.update(kw))
    playout._device_stream(RATE, 480, lambda *_: None)  # pyright: ignore[reportPrivateUsage]
    assert seen["device"] == 11
    assert seen["extra_settings"] is not None
    monkeypatch.setattr(playout.sd, "query_hostapis", lambda: [{"name": "MME"}])
    playout._device_stream(RATE, 480, lambda *_: None)  # pyright: ignore[reportPrivateUsage]
    assert (seen["device"], seen["extra_settings"]) == (None, None)


async def test_real_pocket_tts_speaks_one_sentence_on_the_cpu(
    record_property: Any,
) -> None:
    from snow.voice.tts.pocket import PocketEngine  # noqa: PLC0415

    engine = PocketEngine(TTS_CFG.engines.pocket_tts)
    started = time.perf_counter()
    await asyncio.to_thread(engine.load)
    load_s = time.perf_counter() - started
    for label in ("cold", "warm"):
        started = time.perf_counter()
        first_s, samples = None, 0
        async for chunk in engine.stream(
            "The build finished, and every test passed.", "neutral"
        ):
            first_s = first_s or time.perf_counter() - started
            samples += len(chunk)
            assert chunk.dtype == np.float32 and chunk.ndim == 1
        total_s = time.perf_counter() - started
        audio_s = samples / engine.sample_rate
        rtf = total_s / audio_s
        print(  # noqa: T201 - the measurement is the point of this test
            f"pocket_tts {label}: load={load_s:.1f}s first_chunk={first_s:.3f}s "
            f"audio={audio_s:.2f}s synth={total_s:.2f}s rtf={rtf:.2f}"
        )
        record_property(f"{label}_first_chunk_s", first_s)
        record_property(f"{label}_rtf", rtf)
    assert audio_s > 1.0
    assert rtf < 1.0  # faster than real time, or the first clause cannot start early
