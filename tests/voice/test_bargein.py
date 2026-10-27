"""Barge-in (VOIC-06): talking over Snow pauses it, a check of the words decides, an
accepted one stops it and the interrupting words are heard, a rejected one resumes it.

Fake microphone (scripted VAD fed 512-sample chunks), fake speaker, fake voice engine:
no real audio device is opened and nothing is played or written.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2
import numpy as np
import pytest

from snow.config.secrets import Secret
from snow.contracts.events import (
    PresenceState,
    ReplyInterrupted,
    TranscriptFinal,
    TurnCancelled,
    WakeDetected,
)
from snow.voice.pipeline import SpeakerCheck, VoicePipeline
from snow.voice.stt_groq import GroqStt
from snow.voice.tts.router import VoiceRouter
from snow.voice.turn import CHUNK, TurnEngine
from snow.voice.wake import WakeHit
from tests.voice.conftest import (
    CFG,
    FakeGroq,
    FakeHub,
    FakeLocalStt,
    StubSource,
    tts_cfg_polish_off,
    until,
)
from tests.voice.test_tts_pipeline import (
    RATE,
    TTS_CFG,
    FakeEngine,
    FakeStream,
    Speaker,
    delta,
    final,
    of,
    play_out,
)

SPEECH = 1000  # the value of every speech sample, so the turn audio can be inspected
MS = 16  # samples per millisecond at 16 kHz


class Vad:
    def __init__(self) -> None:
        self.speech = False

    def speech_prob(self, chunk: object) -> float:
        return 1.0 if self.speech else 0.0

    def reset(self) -> None: ...


class AlwaysComplete:
    def append(self, pcm: object) -> None: ...

    def is_complete(self) -> bool:
        return True

    def clear(self) -> None: ...


class NoWake:
    """The wake gate is not under test: frames go to the engine directly."""

    error: str | None = None  # the model loaded fine

    def process(self, frame: object) -> None:
        return None

    def reset(self) -> None: ...


class HoldEngine(FakeEngine):
    """Speaks the first `hold_from` chunks at once, then never finishes the next one:
    synthesis is still in flight when the user barges in."""

    def __init__(self, hold_from: int) -> None:
        super().__init__()
        self._hold_from = hold_from

    async def stream(self, text: str, emotion: str):  # type: ignore[override]
        if len(self.texts) >= self._hold_from:
            self.texts.append(text)
            await asyncio.Event().wait()
        async for block in super().stream(text, emotion):
            yield block


@dataclass
class Rig:
    pipeline: VoicePipeline
    hub: FakeHub
    voice: FakeEngine
    speaker: Speaker
    vad: Vad
    turn: TurnEngine
    local: FakeLocalStt
    mic: int = 0  # microphone samples fed so far
    aborts: list[int] = field(default_factory=list[int])  # `mic` at each speaker abort
    turn_pcm: list[bytes] = field(default_factory=list[bytes])

    def hear(self, ms: int, *, speech: bool) -> None:
        """Feed `ms` of microphone audio, one 512-sample chunk at a time."""
        self.vad.speech = speech
        for _ in range(ms * MS // CHUNK):
            self.mic += CHUNK
            value = SPEECH if speech else 0
            self.turn.feed(np.full(CHUNK, value, dtype=np.int16))

    def pump(self, blocks: int) -> None:
        assert self.speaker.stream is not None
        self.speaker.stream.pump(blocks)


class TimedSpeaker(Speaker):
    def __init__(self, rig_aborts: Callable[[], None]) -> None:
        super().__init__()
        self._on_abort = rig_aborts

    def factory(self, rate: int, block: int, callback: Callable[..., None]):  # type: ignore[override]
        speaker = self

        class Stream(FakeStream):
            def abort(self) -> None:
                super().abort()
                speaker._on_abort()  # noqa: SLF001

        assert rate == RATE
        self.stream = Stream(callback)
        return self.stream


async def make_rig(
    groq: FakeGroq,
    voice: FakeEngine,
    *,
    echo_cancel: bool = False,
    speaker: SpeakerCheck | None = None,
) -> Rig:
    groq.text = "what time is it"
    hub, vad = FakeHub(), Vad()
    turn = TurnEngine(CFG.turn, vad, AlwaysComplete(), conversation=CFG.conversation)
    stt = GroqStt(
        CFG.stt.groq,
        lambda _n: Secret("gsk_test_key_not_real"),
        transport=httpx2.MockTransport(groq.handler),
    )
    local = FakeLocalStt()
    pipeline = VoicePipeline(
        CFG,
        hub,
        StubSource(),  # type: ignore[arg-type]
        NoWake(),  # type: ignore[arg-type]
        turn,
        stt,
        "voice",
        local=local,
        echo_cancel=echo_cancel,
        speaker=speaker,
    )
    pipeline._tone.analyze = lambda *a: None  # type: ignore[method-assign,assignment]  # noqa: SLF001
    rig: Rig
    speaker = TimedSpeaker(lambda: rig.aborts.append(rig.mic))
    # Exact sample arithmetic (what had played by 0.6 s): no polish pace or pauses.
    cfg = tts_cfg_polish_off(TTS_CFG)
    pipeline._tts = VoiceRouter({"pocket_tts": voice}, cfg, pipeline._emit)  # noqa: SLF001
    pipeline._tts_cfg = cfg  # noqa: SLF001
    pipeline._stream_factory = speaker.factory  # noqa: SLF001
    rig = Rig(pipeline, hub, voice, speaker, vad, turn, local)
    on_turn_end = pipeline.on_turn_end

    def spy(turn_id: str, pcm: bytes, duration_ms: int, stop: int) -> None:
        rig.turn_pcm.append(pcm)
        on_turn_end(turn_id, pcm, duration_ms, stop)

    pipeline.on_turn_end = spy  # type: ignore[method-assign]
    await pipeline.start()
    await until(pipeline._tts_ready.is_set)  # noqa: SLF001
    return rig


async def ask(rig: Rig) -> str:
    """Wake Snow, speak one question, wait for its transcript; returns the turn id."""
    rig.turn.on_wake(WakeHit(1.0, "t", [np.zeros(1280, dtype=np.int16)], 1280))
    rig.hear(1000, speech=True)
    rig.hear(500, speech=False)
    await until(lambda: bool(of(rig.hub, TranscriptFinal)))
    return of(rig.hub, TranscriptFinal)[0].turn_id


async def start_reply(rig: Rig, turn_id: str, *, blocks: int) -> None:
    """Three one-sentence chunks of 0.5 s each; `blocks` of 20 ms are played."""
    for text in ("First sentence is here. ", "Second sentence is here. "):
        await rig.pipeline.on_hub_event(delta(text, turn_id))
    await rig.pipeline.on_hub_event(delta("Third sentence is here. ", turn_id))
    await rig.pipeline.on_hub_event(final("x", turn_id))
    await until(lambda: rig.speaker.stream is not None and len(rig.voice.texts) >= 3)
    rig.pump(1)
    await asyncio.sleep(0)  # first audio -> the engine learns Snow is audible
    await asyncio.sleep(0)
    rig.pump(blocks - 1)


async def verdict_in(rig: Rig) -> None:
    """Wait for the check to answer; the engine applies it on its next chunk."""
    await until(lambda: bool(rig.turn._verdicts))  # noqa: SLF001


def playout_of(rig: Rig):  # noqa: ANN201
    playout = rig.pipeline._playout  # noqa: SLF001
    assert playout is not None
    return playout


async def test_talking_over_snow_pauses_it_then_the_check_stops_it_for_good(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="snow.voice")
    voice = HoldEngine(hold_from=2)  # the third chunk is still being synthesized
    rig = await make_rig(groq, voice)
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=30)  # 0.6 s: chunk 1 whole, chunk 2 started
    assert rig.speaker.stream is not None and rig.aborts == []

    rig.hear(100, speech=False)
    rig.hear(320, speech=True)  # 10 chunks: 300 ms, the pause
    assert playout_of(rig)._paused  # noqa: SLF001
    assert rig.aborts == [], "a pause is not a cut"
    rig.pump(5)
    held = playout_of(rig).played
    rig.pump(20)
    assert playout_of(rig).played == held  # the held reply does not advance

    rig.hear(30 * 32, speech=True)  # 30 more: the window's 700 ms is reached
    await verdict_in(rig)
    assert rig.aborts == [], "the check answers; nothing is cut before the verdict"
    rig.hear(32, speech=True)  # the engine applies the verdict
    assert rig.aborts, "playback was not aborted"
    await until(lambda: bool(of(rig.hub, ReplyInterrupted)))
    await rig.pipeline._q.join()  # noqa: SLF001

    cancelled = of(rig.hub, TurnCancelled)
    assert [(c.turn_id, c.cancel_reason) for c in cancelled] == [(turn_id, "barge_in")]
    interrupted = of(rig.hub, ReplyInterrupted)
    assert interrupted[0].turn_id == turn_id
    # Chunk 0 played whole, chunk 1 partly; chunk 2 never started playing.
    assert interrupted[0].spoken_text == " ".join(voice.texts[:2])
    types = rig.hub.types()
    assert types.index("turn.cancelled") < types.index("reply.interrupted")
    assert voice.cancelled >= 1  # synthesis was stopped
    assert rig.pipeline._reply is None  # noqa: SLF001
    assert rig.pipeline._pending is None  # noqa: SLF001
    assert of(rig.hub, PresenceState)[-1].state == "listening"
    # the logs carry the reason and numbers, never the words
    assert "barge_check episode=1 reason=ok" in caplog.text
    assert rig.local.heard not in caplog.text

    # The late rest of the cancelled reply must not start speaking again.
    texts_before = len(voice.texts)
    await rig.pipeline.on_hub_event(delta("Late words. ", turn_id))
    await rig.pipeline.on_hub_event(final("Late words.", turn_id))
    await asyncio.sleep(0.05)
    assert rig.pipeline._reply is None  # noqa: SLF001
    assert len(voice.texts) == texts_before

    # The interrupting speech is the next user turn, with its onset kept.
    rig.hear(320, speech=True)
    rig.hear(500, speech=False)
    await until(lambda: len(of(rig.hub, TranscriptFinal)) == 2)
    second = of(rig.hub, TranscriptFinal)[1]
    assert second.turn_id != turn_id
    pcm = np.frombuffer(rig.turn_pcm[-1], dtype=np.int16)
    assert int(np.count_nonzero(pcm == SPEECH)) == 51 * CHUNK  # every speech chunk


async def test_a_confirmed_barge_in_on_the_very_first_audio_cancels_the_whole_reply(
    groq: FakeGroq,
) -> None:
    voice = HoldEngine(hold_from=1)
    rig = await make_rig(groq, voice)
    turn_id = await ask(rig)
    for text in ("First sentence is here. ", "Second sentence is here. "):
        await rig.pipeline.on_hub_event(delta(text, turn_id))
    await until(lambda: rig.speaker.stream is not None and len(voice.texts) == 2)
    rig.pump(1)  # one 20 ms block of the very first chunk
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    rig.hear(40 * 32, speech=True)  # the pause at 10 chunks, the check at 40
    await verdict_in(rig)
    rig.hear(32, speech=True)
    await until(lambda: bool(of(rig.hub, ReplyInterrupted)))

    assert of(rig.hub, TurnCancelled)[0].cancel_reason == "barge_in"
    assert of(rig.hub, ReplyInterrupted)[0].spoken_text == voice.texts[0]
    assert voice.cancelled >= 1
    assert rig.pipeline._reply is None  # noqa: SLF001
    await asyncio.sleep(0.05)
    assert len(voice.texts) == 2  # nothing after the cut was synthesized


@pytest.mark.parametrize(
    "heard", ["", "second sentence is here", None], ids=["noise", "echo", "error"]
)
async def test_a_rejected_check_resumes_the_reply_and_it_plays_to_the_end(
    groq: FakeGroq, heard: str | None
) -> None:
    rig = await make_rig(groq, FakeEngine())
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=30)
    if heard is None:
        rig.local.fail_transcribe = True
    else:
        rig.local.heard = heard

    rig.hear(320, speech=True)  # the pause
    rig.hear(15 * 32, speech=False)  # quiet: the episode is checked once
    assert playout_of(rig)._paused  # noqa: SLF001
    rig.pump(10)
    await verdict_in(rig)
    rig.hear(32, speech=False)  # the engine applies the verdict
    assert not playout_of(rig)._paused  # noqa: SLF001
    assert rig.aborts == []

    await play_out(rig.pipeline, rig.hub, rig.speaker)
    assert of(rig.hub, ReplyInterrupted) == [] and of(rig.hub, TurnCancelled) == []
    assert rig.local.windows == [(10 + 13) * CHUNK]  # one check, the whole episode


async def test_speech_over_a_warming_canceller_needs_600_ms_before_the_pause(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    turn_id = await ask(rig)
    rig.turn.echo_warming = lambda: True
    await start_reply(rig, turn_id, blocks=10)

    rig.hear(352, speech=True)  # a cold canceller's residual is up to 352 ms
    assert not playout_of(rig)._paused  # noqa: SLF001
    assert rig.aborts == [] and rig.local.windows == []
    assert of(rig.hub, TurnCancelled) == [] and of(rig.hub, ReplyInterrupted) == []
    assert rig.pipeline._reply is not None  # noqa: SLF001
    rig.hear(256, speech=True)  # 19 chunks: 608 ms
    assert playout_of(rig)._paused  # noqa: SLF001


async def test_a_warm_up_barge_in_keeps_the_whole_onset(groq: FakeGroq) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    turn_id = await ask(rig)
    rig.turn.echo_warming = lambda: True
    await start_reply(rig, turn_id, blocks=10)

    rig.hear(100, speech=False)
    rig.hear(49 * 32, speech=True)  # the pause at 19 chunks, the check at 49
    await verdict_in(rig)
    rig.hear(32, speech=True)
    await until(lambda: bool(of(rig.hub, ReplyInterrupted)))

    rig.hear(320, speech=True)
    rig.hear(500, speech=False)
    await until(lambda: len(of(rig.hub, TranscriptFinal)) == 2)
    pcm = np.frombuffer(rig.turn_pcm[-1], dtype=np.int16)
    assert int(np.count_nonzero(pcm == SPEECH)) == 60 * CHUNK  # every speech chunk


async def test_the_wake_phrase_over_snow_stops_it_at_once_and_listens(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=10)
    assert rig.aborts == []

    mic_before = rig.mic
    rig.turn.on_wake(WakeHit(1.0, "t", [np.zeros(1280, dtype=np.int16)], 1280))
    assert rig.aborts == [mic_before]  # stopped on the wake call, no more mic audio
    assert rig.local.windows == []  # no check
    await until(lambda: bool(of(rig.hub, ReplyInterrupted)))
    await rig.pipeline._q.join()  # noqa: SLF001

    cancelled = of(rig.hub, TurnCancelled)
    assert [(c.turn_id, c.cancel_reason) for c in cancelled] == [(turn_id, "barge_in")]
    assert len(of(rig.hub, WakeDetected)) == 2
    assert rig.pipeline._reply is None  # noqa: SLF001
    assert rig.pipeline._pending is None  # noqa: SLF001
    assert of(rig.hub, PresenceState)[-1].state == "listening"

    rig.hear(320, speech=True)
    rig.hear(500, speech=False)
    await until(lambda: len(of(rig.hub, TranscriptFinal)) == 2)
    assert of(rig.hub, TranscriptFinal)[1].turn_id != turn_id


async def test_speech_over_snow_ducks_it_and_an_unconfirmed_noise_gives_it_back(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=10)
    assert rig.turn.duck == rig.pipeline._playout.set_gain  # noqa: SLF001
    rig.local.heard = ""  # nothing intelligible

    gains: list[float] = []
    real = rig.turn.duck

    def spy(gain: float) -> None:
        gains.append(gain)
        real(gain)

    rig.turn.duck = spy
    rig.hear(192, speech=True)
    assert gains == [0.25]
    rig.hear(16 * 32, speech=False)  # quiet: the 6-chunk episode is checked
    await verdict_in(rig)
    rig.hear(32, speech=False)
    assert gains == [0.25, 1.0]
    assert rig.local.windows == [19 * CHUNK]
    assert rig.aborts == []
    assert rig.pipeline._reply is not None  # noqa: SLF001
