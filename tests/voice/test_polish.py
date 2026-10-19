"""The voice-polish chain (src/snow/voice/polish.py): deterministic DSP on numpy signals
and one speech fixture. Nothing here opens a device or writes audio anywhere."""

import time

import numpy as np
import pytest

from snow.config.settings import load_config
from snow.voice.polish import Polish
from snow.voice.sources import read_wav
from snow.voice.tts.base import Samples
from snow.voice.tts.config import PolishConfig, TtsConfig
from tests.voice.conftest import AUDIO, polish_off

VOICE, DEVICE = 24000, 48000
SHIPPED = load_config("tts.toml", TtsConfig).polish
PEAK = 10 ** (-1 / 20)


def db(x: float) -> float:
    return 20 * float(np.log10(max(x, 1e-9)))


def off(**parts: object) -> PolishConfig:
    return polish_off().model_copy(update=parts)


def speech(name: str = "tone_calm") -> Samples:
    """A fixture at the voice rate, float, normalized to a -1 dBFS peak like Pocket."""
    x = read_wav(AUDIO / f"{name}.wav", VOICE).astype(np.float32)
    return (x * (PEAK / float(np.max(np.abs(x))))).astype(np.float32)


def run(
    cfg: PolishConfig,
    x: Samples,
    *,
    chunk: int = 1920,
    out_rate: int = DEVICE,
    text: str = "Right",
) -> Samples:
    """Feed `x` in chunks, then end_clause and flush, as the pipeline does."""
    polish = Polish(cfg, VOICE, out_rate)
    parts = [polish.process(x[i : i + chunk]) for i in range(0, len(x), chunk)]
    parts += [polish.end_clause(text), polish.flush()]
    return np.concatenate(parts)


def voiced_rms_db(x: Samples, rate: int = DEVICE) -> float:
    """RMS over the 10 ms frames above -45 dBFS, in dBFS."""
    n = rate // 100
    frames = x[: len(x) // n * n].reshape(-1, n).astype(np.float64)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    voiced = frames[rms > 10 ** (-45 / 20)]
    return db(float(np.sqrt(np.mean(voiced**2))))


def sine(freq: float, seconds: float, amp: float = 0.5, rate: int = VOICE) -> Samples:
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def peak_freq(x: Samples, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spectrum)) * rate / len(x)


def test_everything_off_at_equal_rates_is_a_pass_through() -> None:
    x = sine(300, 0.5)
    polish = Polish(polish_off(), VOICE, VOICE)
    assert np.array_equal(polish.process(x), x)
    assert len(polish.end_clause("Right.")) == 0 and len(polish.flush()) == 0


def test_the_device_rate_resample_alone_keeps_length_level_and_pitch() -> None:
    x = sine(1000, 1.0)
    y = run(polish_off(), x)
    assert abs(len(y) - 2 * len(x)) < 0.01 * 2 * len(x)
    mid = slice(len(y) // 4, 3 * len(y) // 4)
    assert abs(db(float(np.sqrt(np.mean(y[mid] ** 2)))) - db(0.5 / np.sqrt(2))) < 0.2
    assert abs(peak_freq(y[mid], DEVICE) - 1000) < 20


def test_the_shipped_polish_is_loud_and_never_clips() -> None:
    y = run(SHIPPED, speech())
    assert -18.0 <= voiced_rms_db(y) <= -15.0
    assert float(np.max(np.abs(y))) <= PEAK + 1e-6


def test_clause_edges_are_trimmed_faded_and_click_free() -> None:
    tone = sine(220, 0.3)
    clause = np.concatenate(
        [np.zeros(2400, np.float32), tone, np.zeros(9600, np.float32)]
    )
    polish = Polish(off(trim_edges=True), VOICE, VOICE)
    outs: list[Samples] = []
    for _ in range(2):
        outs.append(polish.process(clause))
        outs.append(polish.end_clause("x"))
        assert len(outs[-1]) or len(outs[-2])
    outs.append(polish.flush())
    y = np.concatenate(outs)
    quiet = np.abs(y) < 10 ** (-50 / 20)
    runs = np.diff(np.flatnonzero(~quiet))
    gap = int(runs.max())  # silence between the two tones
    assert gap <= int(VOICE * (0.010 + 0.030 + 0.005))
    # the first and last sample of each clause are faded to zero
    assert abs(y[0]) < 1e-3 and abs(y[-1]) < 1e-3
    steps = np.abs(np.diff(y))
    assert float(steps.max()) <= float(np.abs(np.diff(tone)).max()) + 1e-6


def test_chunked_output_equals_one_shot() -> None:
    x = speech()
    whole = run(SHIPPED, x, chunk=len(x))
    for chunk in (1920, 777):
        y = run(SHIPPED, x, chunk=chunk)
        assert abs(len(y) - len(whole)) <= 2
        n = min(len(y), len(whole))
        assert float(np.max(np.abs(y[:n] - whole[:n]))) < 1e-3


def test_the_polish_adds_at_most_50_ms_of_delay() -> None:
    polish = Polish(SHIPPED, VOICE, DEVICE)
    x = sine(220, 0.5)
    got = sum(len(polish.process(x[i : i + 1920])) for i in range(0, len(x), 1920))
    assert got >= int(0.45 * DEVICE)


def test_the_polish_runs_far_faster_than_real_time() -> None:
    x = np.tile(speech(), 2)[: 10 * VOICE]
    started = time.perf_counter()
    run(SHIPPED, x, chunk=1920)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("field", ["makeup_db"])
def test_polish_config_bounds(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        PolishConfig(trim_edges=True, compressor=True, makeup_db=40.0)
