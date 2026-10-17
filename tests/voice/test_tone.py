"""Tone detection (D-35, SPCH-02): prosody on the plan 01-05 fixtures, in memory."""

import builtins
import hashlib
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snow.contracts.events import Tone, TranscriptFinal
from snow.voice.config import ToneConfig
from snow.voice.tone import ToneAnalyzer
from tests.voice.conftest import AUDIO, CFG, FakeGroq, RunFixture

SENTENCE = "I need the report finished before the meeting this afternoon."
SIX_WORDS = "one two three four five six"
SR = 16000
ASK = "Hey Jarvis, what is the capital of France?"


def pcm_of(name: str) -> bytes:
    with wave.open(str(AUDIO / f"{name}.wav"), "rb") as w:
        return w.readframes(w.getnframes())


def synthetic(seconds: float, amp: float = 0.2, f0: float = 150.0) -> bytes:
    """Half a second of silence, `seconds` of a 150 Hz harmonic tone, silence."""
    t = np.arange(int(seconds * SR)) / SR
    tone = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in (1, 2, 3)) * amp / 2
    quiet = np.zeros(SR // 2)
    pcm = np.concatenate([quiet, tone, quiet])
    return (pcm * 32767).astype("<i2").tobytes()


def test_stressed_turn_is_fast_and_loud() -> None:
    tone = ToneAnalyzer(CFG.tone).analyze(pcm_of("tone_stressed"), SENTENCE)
    assert (tone.pace, tone.loudness) == ("fast", "loud")


def test_calm_turn_is_not_fast_or_loud() -> None:
    tone = ToneAnalyzer(CFG.tone).analyze(pcm_of("tone_calm"), SENTENCE)
    assert tone.pace in ("slow", "normal")
    assert tone.loudness in ("quiet", "normal")
    assert tone.pitch_hz_median is not None
    assert 60 <= tone.pitch_hz_median <= 400


def test_words_per_minute_is_words_over_voiced_minutes() -> None:
    tone = ToneAnalyzer(CFG.tone).analyze(synthetic(3.0), SIX_WORDS)
    assert tone.words_per_min == pytest.approx(6 / (3.0 / 60), rel=0.10)
    assert tone.pitch_hz_median == pytest.approx(150.0, rel=0.05)


def test_pace_and_loudness_follow_this_users_own_median() -> None:
    a = ToneAnalyzer(CFG.tone)
    for _ in range(4):  # a soft, slow talker: 90 wpm at about -33 dBFS
        a.analyze(synthetic(4.0, amp=0.03), SIX_WORDS)
    # 120 wpm and well above that median: fast and loud for HIM, whatever the absolutes
    tone = a.analyze(synthetic(3.0, amp=0.1), SIX_WORDS)
    assert (tone.pace, tone.loudness) == ("fast", "loud")


def test_analysis_of_five_seconds_is_quick() -> None:
    a, pcm = ToneAnalyzer(CFG.tone), synthetic(4.0)
    a.analyze(pcm, "warm up")
    start = time.perf_counter()
    a.analyze(pcm, "one two three")
    assert time.perf_counter() - start < 0.150


def test_analysis_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open, real_wave = builtins.open, wave.open

    def no_write_open(file: Any, mode: str = "r", *a: Any, **k: Any) -> Any:
        assert not set(mode) & set("wax+"), f"opened {file!r} for writing"
        return real_open(file, mode, *a, **k)

    def no_write_wave(f: Any, mode: str | None = None, *a: Any, **k: Any) -> Any:
        assert not (mode or "r").startswith("w"), "wave opened for writing"
        return real_wave(f, mode, *a, **k)

    pcm = pcm_of("tone_stressed")
    monkeypatch.setattr(builtins, "open", no_write_open)
    monkeypatch.setattr(wave, "open", no_write_wave)
    monkeypatch.setattr(Path, "write_bytes", lambda *_a, **_k: pytest.fail("write"))
    assert ToneAnalyzer(CFG.tone).analyze(pcm, SENTENCE).pace == "fast"


def configured(tmp_path: Path, content: bytes | None, sha: str) -> ToneAnalyzer:
    if content is not None:
        (tmp_path / "m.onnx").write_bytes(content)
    cfg = ToneConfig(
        model_url="https://example.invalid/m.onnx", model_sha256=sha, labels=["a", "b"]
    )
    return ToneAnalyzer(cfg, models_dir=tmp_path)


@pytest.mark.parametrize("case", ["missing", "checksum", "not onnx"])
def test_unavailable_model_leaves_emotion_none_and_prosody_filled(
    case: str, tmp_path: Path
) -> None:
    a = {
        "missing": lambda: configured(tmp_path, None, "0" * 64),
        "checksum": lambda: configured(tmp_path, b"weights", "0" * 64),
        # right checksum, but onnxruntime cannot read it
        "not onnx": lambda: configured(
            tmp_path, b"junk", hashlib.sha256(b"junk").hexdigest()
        ),
    }[case]()
    assert not a.has_model
    tone = a.analyze(pcm_of("tone_stressed"), SENTENCE)
    assert tone.emotion is None and tone.emotion_confidence is None
    assert tone.loudness == "loud" and tone.words_per_min > 0


class FakeSession:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def get_inputs(self) -> list[Any]:
        return [type("I", (), {"name": "waveform"})()]

    def run(self, _out: Any, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        assert feed["waveform"].shape == (1, 48000)
        return [np.array([self.scores], np.float32)]


def test_emotion_is_the_top_label_when_confident() -> None:
    a = ToneAnalyzer(ToneConfig(labels=["a", "b", "c"]))
    a._session, a._window = FakeSession([0.0, 4.0, 0.0]), 48000  # type: ignore[assignment]  # noqa: SLF001
    tone = a.analyze(synthetic(1.0), "hello")
    assert tone.emotion == "b"
    assert tone.emotion_confidence == pytest.approx(0.965, abs=0.001)


def test_emotion_is_none_when_the_model_is_unsure() -> None:
    a = ToneAnalyzer(
        ToneConfig(labels=["a", "b", "c"])
    )  # three even scores: 0.33 < 0.4
    a._session, a._window = FakeSession([0.0, 0.0, 0.0]), 48000  # type: ignore[assignment]  # noqa: SLF001
    assert a.analyze(synthetic(1.0), "hello").emotion is None


@pytest.mark.slow
def test_pinned_emotion_model_runs_within_budget() -> None:
    if not CFG.tone.model_url:
        pytest.skip(
            "emotion model disabled (plan 01-24 spike: FunASR licence is not "
            "permissive and the model misses most non-calm speech); prosody only"
        )
    a = ToneAnalyzer(CFG.tone)
    assert a.has_model, "run `uv run python -m snow.voice.tone` to fetch the model"
    pcm = pcm_of("tone_calm")
    a.analyze(pcm, SENTENCE)
    start = time.perf_counter()
    tone = a.analyze(pcm, SENTENCE)
    assert time.perf_counter() - start < 0.150
    assert tone.pace in ("slow", "normal")


async def test_transcript_final_carries_the_tone(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    run = await run_fixture("wake_cmd_gap150", ASK)
    final = next(e for e in run.hub.events if isinstance(e, TranscriptFinal))
    assert isinstance(final.tone, Tone)
    assert final.tone.words_per_min > 0


async def test_a_slow_analysis_never_delays_the_transcript(
    groq: FakeGroq, run_fixture: RunFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(*_a: Any, **_k: Any) -> Tone:
        time.sleep(CFG.tone.wait_s * 3)
        raise RuntimeError("too late to matter")

    monkeypatch.setattr(ToneAnalyzer, "analyze", slow)
    run = await run_fixture("wake_cmd_gap150", ASK)
    final = next(e for e in run.hub.events if isinstance(e, TranscriptFinal))
    assert final.tone is None
    assert final.text == "what is the capital of France?"
