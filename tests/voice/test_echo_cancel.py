"""Echo cancellation (VOIC-06): real WebRTC APM and real Silero VAD on synthetic echo.

Nothing is played, the microphone is not opened and nothing is written: Snow's voice is
a fixture phrase, the room is a seeded decaying-noise impulse response, all in memory.
The numbers are deterministic for the pinned livekit and a fixed seed.
"""

import threading
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from snow.contracts.events import TtsSpoken
from snow.voice.aec import EchoCanceller
from snow.voice.playout import Playout
from snow.voice.sources import read_wav
from snow.voice.vad import VadDetector
from tests.voice.conftest import AUDIO, CFG, FakeGroq
from tests.voice.test_bargein import HoldEngine, ask, make_rig, start_reply
from tests.voice.test_tts_pipeline import (
    TTS_CFG,
    FakeEngine,
    Speaker,
    of,
    play_out,
)

SR, TR = 16000, 24000
CHUNK = 512
FRAME = 1280
MIN_RUN_MS = CFG.turn.barge_in_min_ms
Pcm = npt.NDArray[np.int16]


def far_of(*names: str, gap_s: float = 0.0) -> tuple[Pcm, Pcm]:
    """The fixture phrases back to back (a gap between them) at 24 kHz and 16 kHz."""
    out: list[list[Pcm]] = [[], []]
    for i, name in enumerate(names):
        for k, rate in enumerate((TR, SR)):
            if i:
                out[k].append(np.zeros(int(rate * gap_s), dtype=np.int16))
            out[k].append(read_wav(AUDIO / f"{name}.wav", rate))
    return np.concatenate(out[0]), np.concatenate(out[1])


def echo_of(
    far16: Pcm, delay_ms: int, level_dbfs: float, seed: int
) -> npt.NDArray[np.float64]:
    """What the mic hears of the speaker: a 60 ms room impulse, delayed, then scaled."""
    rng = np.random.default_rng(seed)
    n = int(SR * 0.06)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (SR * 0.015))
    ir[0] = 3.0
    ir /= np.sqrt((ir**2).sum())
    y = np.convolve(far16.astype(np.float64), ir)[: len(far16)]
    y = np.concatenate([np.zeros(int(SR * delay_ms / 1000)), y])[: len(far16)]
    return y * (10 ** (level_dbfs / 20) * 32768 / np.sqrt(np.mean(y**2)))


def to_pcm(x: npt.NDArray[np.float64]) -> Pcm:
    return np.clip(x, -32768, 32767).astype(np.int16)


def noise(n: int, seed: int) -> npt.NDArray[np.float64]:
    return (
        np.random.default_rng(seed + 100).standard_normal(n) * 10 ** (-63 / 20) * 32768
    )


def drive(aec: EchoCanceller, far24: Pcm, mic: Pcm) -> Pcm:
    """Play `far24` into render() 20 ms at a time and clean `mic` 80 ms at a time,
    render first so the reference is never older than the echo."""
    frames = len(mic) // FRAME
    far = np.zeros(frames * 4 * 480, dtype=np.float32)
    n = min(len(far24), len(far))
    far[:n] = far24[:n] / 32768.0
    out = np.empty(frames * FRAME, dtype=np.int16)
    for f in range(frames):
        for b in range(4):
            i = (f * 4 + b) * 480
            aec.render(far[i : i + 480])
        out[f * FRAME : (f + 1) * FRAME] = aec.capture(mic[f * FRAME : (f + 1) * FRAME])
    return out


_VAD = VadDetector(SR)


def longest_run_ms(pcm: Pcm, start_s: float = 0.0, end_s: float | None = None) -> int:
    """Longest stretch of consecutive 32 ms chunks Silero calls speech."""
    a = int(start_s * SR)
    b = len(pcm) if end_s is None else int(end_s * SR)
    _VAD.reset()
    best = run = 0
    for i in range(a, b - CHUNK + 1, CHUNK):
        if _VAD.speech_prob(pcm[i : i + CHUNK]) >= CFG.turn.vad_threshold:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best * CHUNK * 1000 // SR


def erle_db(raw: Pcm, out: Pcm, start_s: float) -> float:
    a = int(start_s * SR)
    n = min(len(raw), len(out))

    def rms(x: Pcm) -> float:
        return float(np.sqrt(np.mean(np.square(x[a:n].astype(np.float64)))))

    return 20 * float(np.log10(rms(raw) / max(rms(out), 1e-9)))


class Scene:
    """utt1, a 2 s silence, utt2: the second reply is the warm one. `extra_s` of
    silence after the echo leaves room for a user to talk on."""

    def __init__(
        self,
        delay_ms: int = 120,
        level: float = -26.0,
        seed: int = 0,
        extra_s: float = 0.0,
    ) -> None:
        a24, a16 = far_of("phrase_thats_all", "tone_calm", gap_s=0.3)
        b24, b16 = far_of("phrase_go_to_sleep")
        gap = 2 * SR  # the silence between the two replies
        tail = SR + int(extra_s * SR)  # the echo finishes in the first second
        far16 = np.concatenate([a16, np.zeros(gap, np.int16), b16])
        self.utt2_s = (len(a16) + gap) / SR
        echo = echo_of(far16, delay_ms, level, seed)
        self.echo = np.concatenate([echo, np.zeros(tail)])
        self.far24 = np.concatenate(
            [a24, np.zeros(2 * TR, np.int16), b24, np.zeros(tail * TR // SR, np.int16)]
        )
        self.noise = noise(len(self.echo), seed)
        self.n = len(self.echo) // FRAME * FRAME

    def mic(self, user: Pcm | None = None) -> Pcm:
        x = self.echo + self.noise
        if user is not None:
            x = x + np.pad(user.astype(np.float64), (0, len(x) - len(user)))
        return to_pcm(x)[: self.n]


def test_the_fixture_reproduces_the_bug() -> None:
    """Without the canceller the echo alone is a barge-in-length run of speech."""
    scene = Scene()
    assert longest_run_ms(scene.mic(), scene.utt2_s) >= MIN_RUN_MS


def test_warm_echo_never_reaches_a_barge_in_length_run() -> None:
    scene = Scene()
    aec = EchoCanceller(SR, TR)
    out = drive(aec, scene.far24, scene.mic())
    aec.close()
    assert longest_run_ms(out, scene.utt2_s) < MIN_RUN_MS
    assert erle_db(to_pcm(scene.echo), out, scene.utt2_s + 1.0) >= 20


@pytest.mark.parametrize("n", [100, 170])
def test_capture_rejects_a_frame_that_is_not_whole_10_ms(n: int) -> None:
    aec = EchoCanceller(SR, TR)
    with pytest.raises(ValueError, match="10 ms"):
        aec.capture(np.zeros(n, dtype=np.int16))
    aec.close()


def test_a_rate_that_is_not_a_multiple_of_100_is_refused() -> None:
    with pytest.raises(ValueError, match="multiples of 100"):
        EchoCanceller(SR, 22050)


def test_playout_feeds_the_reference_every_block_silent_ones_too() -> None:
    blocks: list[tuple[str, int]] = []
    speaker = Speaker()
    playout = Playout(
        TR,
        TTS_CFG.playout,
        on_render=lambda b: blocks.append((str(b.dtype), len(b))),
        stream_factory=speaker.factory,
    )
    playout.start_utterance()
    assert speaker.stream is not None
    speaker.stream.pump(3)  # nothing queued: silence
    playout.push(np.full(480 * 4, 0.3, dtype=np.float32))
    playout.end_utterance()
    speaker.stream.pump(6)  # four blocks of speech, then silence again
    assert blocks == [("float32", 480)] * 9
    playout.close()


async def test_the_pipeline_cleans_mic_frames_first_when_enabled(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2), echo_cancel=True)
    aec = rig.pipeline._aec  # noqa: SLF001
    assert isinstance(aec, EchoCanceller)
    seen: list[int] = []
    capture = aec.capture

    def spy(frame: Pcm) -> Pcm:
        seen.append(len(frame))
        return capture(frame)

    aec.capture = spy  # type: ignore[method-assign]
    rig.pipeline._on_frame(np.zeros(FRAME, dtype=np.int16))  # noqa: SLF001
    assert seen == [FRAME]
    await rig.pipeline.stop()


async def test_the_pipeline_leaves_frames_alone_when_disabled(groq: FakeGroq) -> None:
    rig = await make_rig(groq, HoldEngine(hold_from=2))
    assert rig.pipeline._aec is None  # noqa: SLF001
    await rig.pipeline.stop()


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("delay_ms", [60, 120, 250])
def test_warm_residual_sweep(seed: int, delay_ms: int) -> None:
    scene = Scene(delay_ms=delay_ms, seed=seed)
    aec = EchoCanceller(SR, TR)
    out = drive(aec, scene.far24, scene.mic())
    aec.close()
    assert longest_run_ms(out, scene.utt2_s) < MIN_RUN_MS
    assert erle_db(to_pcm(scene.echo), out, scene.utt2_s + 1.0) >= 20


def speech_flags(pcm: Pcm) -> npt.NDArray[np.bool_]:
    _VAD.reset()
    return np.array(
        [
            _VAD.speech_prob(pcm[i : i + CHUNK]) >= CFG.turn.vad_threshold
            for i in range(0, len(pcm) - CHUNK + 1, CHUNK)
        ]
    )


def detected_at_s(flags: npt.NDArray[np.bool_], after_s: float) -> float | None:
    """When a run of barge_in_min_ms of speech completes, searching from `after_s`."""
    need = -(-MIN_RUN_MS * SR // (1000 * CHUNK))  # chunks, rounded up
    run = 0
    for i in range(int(after_s * SR) // CHUNK, len(flags)):
        run = run + 1 if flags[i] else 0
        if run >= need:
            return (i + 1) * CHUNK / SR
    return None


def test_the_user_talking_over_snow_still_gets_through() -> None:
    scene = Scene(extra_s=6.0)
    user_16 = read_wav(AUDIO / "mid_thought_pause.wav", SR).astype(np.float64)
    user_16 *= 10 ** (-32 / 20) * 32768 / np.sqrt(np.mean(user_16**2))
    user = np.concatenate([np.zeros(int((scene.utt2_s + 1.5) * SR)), user_16])
    user = to_pcm(np.pad(user, (0, max(0, scene.n - len(user))))[: scene.n])
    aec = EchoCanceller(SR, TR)
    out = drive(aec, scene.far24, scene.mic(user))
    aec.close()

    alone = speech_flags(to_pcm(user.astype(np.float64) + scene.noise[: len(user)]))
    cleaned = speech_flags(out)
    assert alone.sum() > 50
    assert (alone & cleaned).sum() >= 0.7 * alone.sum()
    start = scene.utt2_s + 1.5
    ideal, got = detected_at_s(alone, start), detected_at_s(cleaned, start)
    assert ideal is not None and got is not None
    assert got - ideal <= 0.7


def test_render_and_capture_on_two_threads_is_safe() -> None:
    aec = EchoCanceller(SR, TR)
    errors: list[BaseException] = []
    block = np.full(480, 0.1, dtype=np.float32)
    frame = np.full(FRAME, 300, dtype=np.int16)

    def loop(fn: Callable[[], object]) -> None:
        try:
            for _ in range(500):
                fn()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [
        threading.Thread(target=loop, args=(lambda: aec.render(block),)),
        threading.Thread(target=loop, args=(lambda: aec.capture(frame),)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert aec._apm is not None  # noqa: SLF001 - neither side fell back to pass-through
    aec.close()


class _Broken:
    def process_stream(self, frame: object) -> None:
        raise RuntimeError("native failure")

    process_reverse_stream = process_stream


def test_a_failing_apm_passes_audio_through_and_never_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    aec = EchoCanceller(SR, TR)
    aec._apm = _Broken()  # type: ignore[assignment]  # noqa: SLF001
    frame = np.arange(FRAME, dtype=np.int16)

    with caplog.at_level("ERROR", logger="snow.voice"):
        aec.render(np.zeros(480, dtype=np.float32))  # must not raise into PortAudio
        assert aec._apm is None  # noqa: SLF001
        assert np.array_equal(aec.capture(frame), frame)
        aec.render(np.zeros(480, dtype=np.float32))
    assert [r.getMessage() for r in caplog.records] == ["aec_failed kind=RuntimeError"]
    aec.close()
    aec.close()


async def test_a_canceller_that_cannot_load_leaves_the_voice_working(
    groq: FakeGroq,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(*_args: object) -> EchoCanceller:
        raise ImportError("livekit")

    monkeypatch.setattr("snow.voice.pipeline.EchoCanceller", broken)
    with caplog.at_level("WARNING", logger="snow.voice"):
        rig = await make_rig(groq, FakeEngine(), echo_cancel=True)
    assert rig.pipeline._aec is None  # noqa: SLF001
    assert "aec_unavailable kind=ImportError barge_in_hears_snow" in caplog.text

    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=3)
    await play_out(rig.pipeline, rig.hub, rig.speaker)
    assert of(rig.hub, TtsSpoken)
