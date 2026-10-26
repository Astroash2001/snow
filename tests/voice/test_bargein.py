"""Barge-in (VOIC-06): talking over Snow stops it, and the interrupting words are heard.

Fake microphone (scripted VAD fed 512-sample chunks), fake speaker, fake voice engine:
no real audio device is opened and nothing is played or written.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx2
import numpy as np

from snow.config.secrets import Secret
from snow.contracts.events import (
    PresenceState,
    ReplyInterrupted,
    TranscriptFinal,
    TurnCancelled,
    WakeDetected,
)
from snow.voice.pipeline import VoicePipeline
from snow.voice.stt_groq import GroqStt
from snow.voice.tts.router import VoiceRouter
from snow.voice.turn import CHUNK, TurnEngine
from snow.voice.wake import WakeHit
from tests.voice.conftest import (
    CFG,
    FakeGroq,
    FakeHub,
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
    groq: FakeGroq, voice: FakeEngine, *, echo_cancel: bool = False
) -> Rig:
    groq.text = "what time is it"
    hub, vad = FakeHub(), Vad()
    turn = TurnEngine(CFG.turn, vad, AlwaysComplete(), conversation=CFG.conversation)
    stt = GroqStt(
        CFG.stt.groq,
        lambda _n: Secret("gsk_test_key_not_real"),
        transport=httpx2.MockTransport(groq.handler),
    )
    pipeline = VoicePipeline(
        CFG,
        hub,
        StubSource(),  # type: ignore[arg-type]
        NoWake(),  # type: ignore[arg-type]
        turn,
        stt,
        "voice",
        echo_cancel=echo_cancel,
    )
    pipeline._tone.analyze = lambda *a: None  # type: ignore[method-assign,assignment]  # noqa: SLF001
    rig: Rig
    speaker = TimedSpeaker(lambda: rig.aborts.append(rig.mic))
    # Exact sample arithmetic (what had played by 0.6 s): no polish pace or pauses.
    cfg = tts_cfg_polish_off(TTS_CFG)
    pipeline._tts = VoiceRouter({"pocket_tts": voice}, cfg, pipeline._emit)  # noqa: SLF001
    pipeline._tts_cfg = cfg  # noqa: SLF001
    pipeline._stream_factory = speaker.factory  # noqa: SLF001
    rig = Rig(pipeline, hub, voice, speaker, vad, turn)
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


async def test_talking_over_snow_stops_it_and_keeps_the_first_words(
    groq: FakeGroq,
) -> None:
    voice = HoldEngine(hold_from=2)  # the third chunk is still being synthesized
    rig = await make_rig(groq, voice)
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=30)  # 0.6 s: chunk 1 whole, chunk 2 started
    assert rig.speaker.stream is not None and rig.aborts == []

    rig.hear(100, speech=False)
    speech_start = rig.mic
    rig.hear(320, speech=True)  # 10 chunks: the barge-in fires on the 8th
    detection = speech_start + 8 * CHUNK

    assert rig.aborts, "playback was not aborted"
    assert rig.aborts[0] - detection <= 150 * MS
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
    assert int(np.count_nonzero(pcm == SPEECH)) == 20 * CHUNK  # every speech chunk


async def test_barge_in_on_the_very_first_audio_cancels_the_whole_reply(
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

    rig.hear(320, speech=True)
    await until(lambda: bool(of(rig.hub, ReplyInterrupted)))

    assert of(rig.hub, TurnCancelled)[0].cancel_reason == "barge_in"
    assert of(rig.hub, ReplyInterrupted)[0].spoken_text == voice.texts[0]
    assert voice.cancelled >= 1
    assert rig.pipeline._reply is None  # noqa: SLF001
    await asyncio.sleep(0.05)
    assert len(voice.texts) == 2  # nothing after the cut was synthesized


async def test_200_ms_of_speech_over_snow_is_not_a_barge_in(groq: FakeGroq) -> None:
    voice = HoldEngine(hold_from=2)
    rig = await make_rig(groq, voice)
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=10)

    rig.hear(192, speech=True)  # 6 chunks
    rig.hear(300, speech=False)
    await asyncio.sleep(0.05)

    assert rig.aborts == []
    assert of(rig.hub, TurnCancelled) == [] and of(rig.hub, ReplyInterrupted) == []
    assert rig.pipeline._reply is not None  # noqa: SLF001
    assert voice.cancelled == 0


async def test_a_352_ms_burst_over_a_warming_canceller_is_not_a_barge_in(
    groq: FakeGroq,
) -> None:
    """A cold canceller leaves residual up to 352 ms; while warming it cannot cut in."""
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    turn_id = await ask(rig)
    rig.turn.echo_warming = lambda: True
    await start_reply(rig, turn_id, blocks=10)

    rig.hear(352, speech=True)
    rig.hear(300, speech=False)
    await asyncio.sleep(0.05)

    assert rig.aborts == []
    assert of(rig.hub, TurnCancelled) == [] and of(rig.hub, ReplyInterrupted) == []
    assert rig.pipeline._reply is not None  # noqa: SLF001


async def test_warm_up_barge_in_needs_600_ms_and_keeps_the_whole_onset(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    turn_id = await ask(rig)
    rig.turn.echo_warming = lambda: True
    await start_reply(rig, turn_id, blocks=10)

    rig.hear(100, speech=False)
    rig.hear(640, speech=True)  # 20 chunks: the barge-in fires on the 19th (608 ms)
    assert rig.aborts, "playback was not aborted"
    await until(lambda: bool(of(rig.hub, ReplyInterrupted)))

    rig.hear(320, speech=True)
    rig.hear(500, speech=False)
    await until(lambda: len(of(rig.hub, TranscriptFinal)) == 2)
    pcm = np.frombuffer(rig.turn_pcm[-1], dtype=np.int16)
    assert int(np.count_nonzero(pcm == SPEECH)) == 30 * CHUNK  # every speech chunk


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

    gains: list[float] = []
    real = rig.turn.duck

    def spy(gain: float) -> None:
        gains.append(gain)
        real(gain)

    rig.turn.duck = spy
    rig.hear(192, speech=True)
    assert gains == [0.25]
    rig.hear(900, speech=False)
    assert gains == [0.25, 1.0]
    assert rig.aborts == []
    assert rig.pipeline._reply is not None  # noqa: SLF001
