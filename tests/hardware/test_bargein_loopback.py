"""Barge-in loopback self-test (VOIC-06): no user needed, laptop speakers and mic.

Run by hand with Snow quit (it skips itself while Snow's hub is alive) and the default
output set to the laptop speakers at normal volume, no headphones:

    uv run pytest -m hardware tests/hardware/test_bargein_loopback.py -x -q -s

WARNING: it plays sound out loud for several minutes (long replies, coughs, clicks, a
voice clip). It builds the real pipeline the way `python -m snow.voice` does (real mic,
wake gate, VAD, Smart Turn, Moonshine, Pocket TTS, echo canceller), with Pocket as the
only voice and a fail-closed fake Groq, so no audio leaves the PC and no Cartesia call
goes out. Nothing is recorded or written; the stand-in voiceprint lives in pytest's tmp
path only.

The room-sound scenarios pin the echo reference to "render": room sounds play through
the PC, so a loopback reference would cancel them and they would no longer stand in for
a person in the room. The FxSound-style scenarios use the loopback: Snow's own
voice goes through an EQ, a dynamic gain and saturation stage after the render
reference (what an output enhancer does), and the canceller must still not hear it.
They need the laptop speakers (or any real output) as the default output; with FxSound
itself as the default the loopback picks the single real output behind it.

Two voiceprint states: "enrolled" (the user's voiceprint when `snow dev enroll-voice`
has been run, otherwise a stand-in built from a fixture voice, which is NOT evidence of
the biometric gate) and "none" (the degraded words-only mode). Room sounds and a voice
clip play through a second output stream that is not the echo reference, like a real
room.
"""

import asyncio
import logging
import os
import queue
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx2
import numpy as np
import numpy.typing as npt
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.contracts.events import ReplyInterrupted, TtsSpoken
from snow.voice.config import VoiceConfig
from snow.voice.enroll import snow_is_running
from snow.voice.pipeline import VoicePipeline, build_pipeline
from snow.voice.playout import Playout, StreamFactory, _device_stream
from snow.voice.sources import Frame, MicSource, OnFrame, read_wav
from snow.voice.speaker import SpeakerVerifier, save_voiceprint, voiceprint_path
from snow.voice.stt_groq import GroqStt
from snow.voice.stt_local import LocalStt
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.pocket import PocketEngine
from snow.voice.turn import State
from tests.voice.conftest import AUDIO, FakeGroq, FakeHub, until
from tests.voice.test_tts_pipeline import delta, final

pytestmark = pytest.mark.hardware

CFG = load_config("voice.toml", VoiceConfig)
TTS = load_config("tts.toml", TtsConfig)
# The microphone to listen on: the Windows default (as in voice.toml), unless
# SNOW_LOOPBACK_MIC names another, e.g. "Microphone Array" for the laptop's own mic
# when a headset is the default input.
MIC_DEVICE = os.environ.get("SNOW_LOOPBACK_MIC", CFG.audio.input_device)
# How far above the room a speaker burst must sit at the mic for the run to count. Lower
# it (SNOW_LOOPBACK_MIN_RISE_DB) only to look at a soft-speaker setup: the verdicts are
# then weak evidence.
MIN_RISE_DB = float(os.environ.get("SNOW_LOOPBACK_MIN_RISE_DB", "10"))
ROOM_RATE = 24000  # the second (room) stream: no echo reference
WARM_S = 2.0  # the canceller's warm-up: the first reply of a rig may pause once
REPLY_TIMEOUT_S = 75
REASON = re.compile(r"barge_check episode=\d+ reason=(\w+) score=(\S+)")

# Plain sentences, no wake phrase and no name; about 20 s of speech each.
REPLIES = [
    "The river runs south for nearly two hundred miles before it widens into a broad "
    "and quiet delta. Farmers there grow rice and cotton on the flat land, and in the "
    "evening the fishing boats come in with their lanterns lit. It is slow work, "
    "and the families who do it have done it for many generations. ",
    "A good loaf of bread needs only flour, water, salt and time. The dough is mixed "
    "in the evening and left alone overnight, so that the yeast can do its slow work. "
    "By morning it has doubled, and a hot oven turns it into something with a crisp "
    "golden crust and a soft, open crumb inside. ",
    "Long ago the town had a stone bridge with seven arches, built by masons who "
    "carried every block up from the quarry by hand. Travellers crossed it on market "
    "days, and the bridge outlasted three floods and two wars. Today people mostly "
    "walk across it just to look at the water. ",
]


# --- room sounds, generated in memory ------------------------------------------------


def band_noise(rng: np.random.Generator, n: int, rate: int) -> npt.NDArray[np.float32]:
    """White noise limited to 300-3000 Hz (cough- and tap-like)."""
    spec = np.fft.rfft(rng.normal(size=n))
    freq = np.fft.rfftfreq(n, 1 / rate)
    spec[(freq < 300) | (freq > 3000)] = 0
    x = np.fft.irfft(spec, n)
    return (x / max(float(np.abs(x).max()), 1e-9)).astype(np.float32)


def room_noise(
    seconds: float, rate: int = ROOM_RATE, seed: int = 7
) -> npt.NDArray[np.float32]:
    """A -40 dBFS noise bed, a 250 ms cough about every 3 s and 5 ms desk clicks."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = (rng.normal(size=n) * 0.01).astype(np.float32)  # -40 dBFS rms
    cough = int(0.25 * rate)
    envelope = np.sin(np.linspace(0, np.pi, cough)) ** 2
    for t in np.arange(1.5, seconds - 0.5, 3.0):
        i = int(t * rate)
        out[i : i + cough] += 0.35 * band_noise(rng, cough, rate) * envelope
    click = int(0.005 * rate)
    decay = np.exp(-np.linspace(0, 6, click))
    for t in np.arange(0.8, seconds - 0.2, 1.7):
        i = int(t * rate)
        out[i : i + click] += 0.35 * band_noise(rng, click, rate) * decay
    return np.clip(out, -1, 1)


# --- an output enhancer, like FxSound ------------------------------------------------


class FxStyle:
    """Bass-boost EQ, then a smoothed AGC/compressor, then tanh saturation: all in
    numpy, cheap and deterministic. Applied to what the speakers play, after the
    echo reference has seen the clean block."""

    TAPS = 129

    def __init__(self, rate: int) -> None:
        t = np.arange(self.TAPS) - self.TAPS // 2
        low = np.sinc(2 * 250 / rate * t) * np.hamming(self.TAPS)
        ident = np.zeros(self.TAPS)
        ident[self.TAPS // 2] = 1.0
        self.taps = (0.6 * ident + 0.4 * low / low.sum()).astype(np.float32)
        self.history = np.zeros(self.TAPS - 1, dtype=np.float32)
        self.gain = 1.0

    def process(self, x: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        buf = np.concatenate([self.history, x])
        self.history = buf[-(self.TAPS - 1) :]
        y = np.convolve(buf, self.taps, mode="valid")
        rms = float(np.sqrt(np.mean(np.square(y, dtype=np.float64))))
        target = float(np.clip(0.25 / max(rms, 1e-6), 0.5, 4.0))
        self.gain += 0.3 * (target - self.gain)
        z = np.tanh(1.8 * self.gain * y) / np.tanh(1.8)
        return np.clip(z, -1.0, 1.0).astype(np.float32)


def fx_stream_factory() -> StreamFactory:
    def factory(rate: int, block: int, callback: Callable[..., None]):  # noqa: ANN202
        fx = FxStyle(rate)

        def wrapped(outdata: npt.NDArray[np.float32], *rest: object) -> None:
            callback(outdata, *rest)  # the clean block reaches on_render first
            outdata[:, 0] = fx.process(outdata[:, 0])

        return _device_stream(rate, block, wrapped)

    return factory


# --- the rig -----------------------------------------------------------------------


class ArmableMic:
    """The microphone, whose frames first run queued actions on the audio thread, so
    engine state is only ever touched there."""

    def __init__(self) -> None:
        a = CFG.audio
        self._mic = MicSource(MIC_DEVICE, a.sample_rate, a.frame_samples)
        self._actions: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()

    @property
    def is_open(self) -> bool:
        return self._mic.is_open

    def open(self, on_frame: OnFrame) -> None:
        def frame(f: Frame) -> None:
            while not self._actions.empty():
                self._actions.get_nowait()()
            on_frame(f)

        self._mic.open(frame)

    def close(self) -> None:
        self._mic.close()

    def arm(self, action: Callable[[], None]) -> None:
        self._actions.put(action)


@dataclass
class Stats:
    reply: int = 0  # the index of the reply being spoken
    pauses: list[int] = field(default_factory=list[int])  # reply index per pause
    checks: int = 0
    ok: int = 0
    rejected: int = 0
    reasons: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])


@dataclass
class Rig:
    pipeline: VoicePipeline
    hub: FakeHub
    mic: ArmableMic
    room: Playout
    stats: Stats
    state: str
    cut_after_room_s: float | None = None

    def interrupted(self) -> int:
        return sum(isinstance(e, ReplyInterrupted) for e in self.hub.events)

    def spoken(self) -> int:
        return sum(isinstance(e, TtsSpoken) for e in self.hub.events)

    async def reply(
        self,
        index: int,
        *,
        room: Callable[[], None] | None = None,
        room_after_s: float = 0.0,
    ) -> None:
        """Say reply `index` out loud and wait until it ends (or is cut off). `room`
        starts `room_after_s` after the voice has begun; `cut_after_room_s` then holds
        how long the reply lasted from there (None: it was not cut off)."""
        self.stats.reply = index
        turn = f"loop{index}"
        engine = self.pipeline._engine  # noqa: SLF001

        def rest() -> None:  # the audio thread: wake-only, nothing pending
            engine.drain()
            engine.state = State.SLEEPING
            engine._close_turn()  # noqa: SLF001
            engine._waiting = False  # noqa: SLF001
            self.pipeline._pending = None  # noqa: SLF001

        # Between replies the engine only listens for the wake phrase, so room sounds
        # that outlast a reply cannot open a user turn that would swallow the next one.
        self.mic.arm(rest)
        await asyncio.sleep(0.3)
        await until(lambda: not self.pipeline._tasks, 10)  # noqa: SLF001

        def arm() -> None:  # the audio thread
            engine.drain()  # the last reply's "finished" must not undo this
            engine.state = State.AWAKE
            engine._close_turn()  # noqa: SLF001
            engine._waiting, engine._waited = True, 0  # noqa: SLF001
            self.pipeline._pending = turn  # noqa: SLF001

        self.mic.arm(arm)
        await until(lambda: engine._waiting, 10)  # noqa: SLF001
        before_s, before_i = self.spoken(), self.interrupted()
        text = REPLIES[index % len(REPLIES)]
        for sentence in re.findall(r".+?[.!?] ", text):
            await self.pipeline.on_hub_event(delta(sentence, turn))
        await self.pipeline.on_hub_event(final(text, turn))
        started = time.monotonic()
        room_at: float | None = None
        async with asyncio.timeout(REPLY_TIMEOUT_S):
            while self.spoken() == before_s and self.interrupted() == before_i:
                reply = self.pipeline._reply  # noqa: SLF001
                if (
                    room is not None
                    and room_at is None
                    and reply is not None
                    and reply.spoke
                ):
                    room_at = time.monotonic() + room_after_s
                if (
                    room is not None
                    and room_at is not None
                    and time.monotonic() >= room_at
                ):
                    room()
                    room = None
                await asyncio.sleep(0.02)
        self.room.abort()  # the room sound ends with the reply
        cut = self.interrupted() > before_i
        self.cut_after_room_s = (
            time.monotonic() - room_at if cut and room_at is not None else None
        )
        print(
            f"  reply {index}: {time.monotonic() - started:.1f} s, "
            f"{'CUT OFF' if cut else 'completed'}"
        )

    def play_room(self, samples: npt.NDArray[np.float32]) -> None:
        self.room.start_utterance()
        self.room.push(samples)
        self.room.end_utterance()

    def report(self, title: str) -> None:
        s = self.stats
        by_reason = {r: sum(x == r for x, _ in s.reasons) for r, _ in s.reasons}
        scores = [sc for _, sc in s.reasons if sc != "None"]
        print(
            f"[{self.state}] {title}: pauses {len(s.pauses)} (per reply {s.pauses}), "
            f"checks {s.checks}, verdicts ok {s.ok} / rejected {s.rejected}, "
            f"reasons {by_reason}, speaker scores {scores}, "
            f"cut offs {self.interrupted()}, replies completed {self.spoken()}, "
            f"pause_after_ms {CFG.turn.pause_after_ms}"
        )


def stand_in_voiceprint(tmp: Path) -> tuple[SpeakerVerifier, str]:
    """The user's voiceprint when enrolled; else one built from a fixture voice."""
    if voiceprint_path().is_file():
        return SpeakerVerifier(CFG.speaker), "the user's real voiceprint"
    store = tmp / "stand-in.bin"
    builder = SpeakerVerifier(CFG.speaker, store=store)
    builder.load()
    clip = read_wav(AUDIO / "tone_calm.wav", CFG.audio.sample_rate)
    save_voiceprint(builder.embed(clip), CFG.speaker.threshold, store)
    return SpeakerVerifier(CFG.speaker, store=store), (
        "a STAND-IN voiceprint (tone_calm.wav): not evidence of the biometric gate"
    )


@asynccontextmanager
async def running(
    state: str,
    tmp: Path,
    caplog: pytest.LogCaptureFixture,
    *,
    reference: str = "render",
    fx: bool = False,
) -> AsyncIterator[Rig]:
    caplog.set_level(logging.INFO, logger="snow.voice")
    speaker: SpeakerVerifier | None = None
    if state == "enrolled":
        speaker, which = stand_in_voiceprint(tmp)
        print(f"\n[enrolled] voiceprint: {which}")
    else:
        print("\n[none] no voiceprint: degraded words-only mode")

    groq = FakeGroq(text="")  # fail-closed: any real request is a violation
    stt = GroqStt(
        CFG.stt.groq,
        lambda _n: Secret("gsk_test_key_not_real"),
        transport=httpx2.MockTransport(groq.handler),
    )
    cfg = CFG.model_copy(
        update={"audio": CFG.audio.model_copy(update={"aec_reference": reference})}
    )
    a = cfg.audio
    local = LocalStt(CFG.stt.local, a.sample_rate)
    router = TTS.router.model_copy(update={"order": ["pocket_tts"]})
    tts_cfg = TTS.model_copy(update={"router": router})
    mic, hub, stats = ArmableMic(), FakeHub(), Stats()
    pipeline = build_pipeline(
        cfg,
        hub,
        mic,  # type: ignore[arg-type]
        stt,
        local=local,
        tts={"pocket_tts": PocketEngine(TTS.engines.pocket_tts)},
        tts_cfg=tts_cfg,
        echo_cancel=True,
        speaker=speaker,
    )
    if fx:
        pipeline._stream_factory = fx_stream_factory()  # noqa: SLF001
    engine = pipeline._engine  # noqa: SLF001
    check = engine.check

    def spy_check(window: Frame, episode: int) -> None:
        stats.checks += 1
        check(window, episode)

    engine.check = spy_check
    verdict = engine.verdict

    def spy_verdict(episode: int, ok: bool) -> None:
        stats.ok += ok
        stats.rejected += not ok
        verdict(episode, ok)

    engine.verdict = spy_verdict  # type: ignore[method-assign]

    class Reasons(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            m = REASON.search(record.getMessage())
            if m:
                stats.reasons.append((m.group(1), m.group(2)))

    handler = Reasons()
    logging.getLogger("snow.voice").addHandler(handler)
    room = Playout(ROOM_RATE, TTS.playout)  # no on_render: not the echo reference
    try:
        await pipeline.start(listen=True)
        async with asyncio.timeout(120):
            await pipeline._tts_ready.wait()  # noqa: SLF001
        await until(lambda: speaker is None or speaker.enrolled, 120)
        assert pipeline._playout is not None, "Pocket TTS did not load"  # noqa: SLF001
        pause = engine.pause

        def spy_pause(paused: bool) -> None:
            if paused:
                stats.pauses.append(stats.reply)
            pause(paused)

        engine.pause = spy_pause
        if reference == "loopback":
            aec = pipeline._aec  # noqa: SLF001
            try:
                await until(lambda: aec is not None and aec.loopback, 10)
            except TimeoutError:
                lines = [
                    r.getMessage() for r in caplog.records if "aec_" in r.getMessage()
                ]
                pytest.fail(f"the loopback reference never came up: {lines}")
        await asyncio.sleep(1.5)  # the microphone settles before anything plays
        yield Rig(pipeline, hub, mic, room, stats, state)
        assert not groq.violations, f"requests to unrouted hosts: {groq.violations}"
    finally:
        logging.getLogger("snow.voice").removeHandler(handler)
        room.close()
        await pipeline.stop()
        local.close()


def level_db(frames: list[Frame]) -> float:
    x = np.concatenate(frames).astype(np.float64) / 32768
    return 20 * float(np.log10(max(float(np.sqrt(np.mean(x**2))), 1e-9)))


@pytest.fixture(autouse=True, scope="module")
def snow_must_be_quit() -> None:
    if snow_is_running():
        pytest.skip("Snow is running: quit it, then rerun")


@pytest.fixture(autouse=True, scope="module")
def the_microphone_hears_the_speakers(snow_must_be_quit: None) -> None:
    """Without a live loopback every scenario below passes vacuously (a muted or
    headset default mic reads digital silence): play a burst and demand the mic hears
    it well above the room."""
    frames: list[Frame] = []
    mic = MicSource(MIC_DEVICE, CFG.audio.sample_rate, CFG.audio.frame_samples)
    mic.open(frames.append)
    done = threading.Event()
    room = Playout(ROOM_RATE, TTS.playout, on_drained=done.set)
    try:
        time.sleep(1.5)
        quiet = len(frames)
        rng = np.random.default_rng(3)
        room.start_utterance()
        room.push((0.5 * band_noise(rng, 2 * ROOM_RATE, ROOM_RATE)).astype(np.float32))
        room.end_utterance()
        done.wait(10)
        time.sleep(0.3)
    finally:
        room.close()
        mic.close()
    room_db, burst_db = level_db(frames[:quiet]), level_db(frames[quiet:])
    print(
        f"\nloopback check on {MIC_DEVICE or 'the default mic'}: room {room_db:.1f} "
        f"dBFS, speaker burst {burst_db:.1f} dBFS"
    )
    if burst_db < room_db + MIN_RISE_DB:
        pytest.skip(
            "loopback is not live: the microphone does not hear the speakers (muted, "
            "headset or wrong default devices). Make the laptop speakers the default "
            "output and its own mic the default input (or set SNOW_LOOPBACK_MIC to its "
            "name), at normal volume, then rerun"
        )


# --- scenarios ------------------------------------------------------------------------


async def test_snow_alone_never_pauses_or_cuts_itself(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with running("enrolled", tmp_path, caplog) as rig:
        for i in range(3):
            await rig.reply(i)
        rig.report("Snow alone, 3 long replies")
        assert rig.interrupted() == 0, "Snow cut itself off"
        assert rig.spoken() == 3, "a reply did not complete"
        late = [p for p in rig.stats.pauses if p >= 1]
        assert not late, f"Snow paused itself after warm-up, in replies {late}"
        print(f"  (reply 1 may warm the canceller: {rig.stats.pauses.count(0)} pauses)")


async def test_noise_over_snow_never_cuts_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with running("enrolled", tmp_path, caplog) as rig:
        for i in range(2):
            await rig.reply(i, room=lambda: rig.play_room(room_noise(24)))
        rig.report("coughs, clicks and a noise bed over Snow")
        assert rig.interrupted() == 0, "room noise cut Snow off"
        assert rig.spoken() == 2, "a reply did not complete"


async def test_noise_over_snow_without_voiceprint_is_recorded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with running("none", tmp_path, caplog) as rig:
        for i in range(2):
            await rig.reply(i, room=lambda: rig.play_room(room_noise(24)))
        rig.report("the same noise, no voiceprint (degraded mode, recorded only)")
        # Only a crash or an incomplete run fails: the degraded mode is accepted.
        assert rig.interrupted() + rig.spoken() == 2


def voice_clip() -> npt.NDArray[np.float32]:
    pcm = read_wav(AUDIO / "mid_thought_pause.wav", ROOM_RATE)
    return pcm.astype(np.float32) / 32768


async def test_a_voice_over_snow_is_checked(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The positive control: with no voiceprint a real voice over Snow is confirmed."""
    clip = voice_clip()
    async with running("none", tmp_path, caplog) as rig:
        await rig.reply(0, room=lambda: rig.play_room(clip), room_after_s=4.0)
        rig.report("a voice clip over Snow")
        assert rig.interrupted() == 1, "the voice never cut Snow off"
        assert rig.stats.ok >= 1
        assert rig.cut_after_room_s is not None and rig.cut_after_room_s <= 3.5, (
            f"cut {rig.cut_after_room_s} s after the clip began"
        )


@pytest.mark.skipif(
    not voiceprint_path().is_file(),
    reason="needs the user's real voiceprint: run `snow dev enroll-voice` first",
)
async def test_a_voice_over_snow_is_rejected_with_the_users_voiceprint(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """RESEARCH: a speaker-replayed voice is a regression signal, not the threshold."""
    clip = voice_clip()
    async with running("enrolled", tmp_path, caplog) as rig:
        await rig.reply(0, room=lambda: rig.play_room(clip), room_after_s=4.0)
        rig.report("a voice clip over Snow, with the user's voiceprint")
        assert rig.interrupted() == 0, "a voice that is not the user's cut Snow off"
        assert any(reason == "speaker" for reason, _ in rig.stats.reasons)


async def test_fxsound_style_output_with_the_loopback_reference_never_pauses_snow(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The point of the loopback: EQ, dynamic gain and saturation after the render
    reference must not make Snow hear (and pause for) itself."""
    async with running(
        "enrolled", tmp_path, caplog, reference="loopback", fx=True
    ) as rig:
        for i in range(3):
            await rig.reply(i)
        rig.report("FxSound-style output, loopback reference, 3 long replies")
        assert rig.interrupted() == 0, "Snow cut itself off"
        assert rig.spoken() == 3, "a reply did not complete"
        late = [p for p in rig.stats.pauses if p >= 1]
        assert not late, f"Snow paused itself after warm-up, in replies {late}"


async def test_fxsound_style_output_with_the_render_reference_is_recorded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The control: the old reference. It reports pauses; only a crash fails."""
    async with running(
        "enrolled", tmp_path, caplog, reference="render", fx=True
    ) as rig:
        for i in range(3):
            await rig.reply(i)
        rig.report("FxSound-style output, render reference (the old reference)")
        assert rig.interrupted() + rig.spoken() == 3
