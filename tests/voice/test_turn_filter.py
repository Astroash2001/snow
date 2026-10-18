"""Turns with too little voiced sound, or that Whisper calls silent, get no reply."""

import logging

import numpy as np
import pytest

from snow.contracts.events import ReplyDelta, ReplyFinal, TranscriptFinal
from snow.voice.tone import voiced_level
from snow.voice.wake import WakeHit
from tests.voice.conftest import CFG, SR, FakeGroq, until
from tests.voice.test_bargein import Rig, make_rig
from tests.voice.test_tts_pipeline import FakeEngine, of

FRAME = int(SR * 0.03)


def burst(frames: int, dbfs: float, noise_dbfs: float = -70.0) -> bytes:
    """Noise, a tone burst of `frames` 30 ms frames, then noise (frame aligned)."""
    rng = np.random.default_rng(0)
    amp = 10 ** (dbfs / 20) * np.sqrt(2)  # a sine's RMS is amp / sqrt(2)
    noise = 10 ** (noise_dbfs / 20)
    n = frames * FRAME
    tone = amp * np.sin(2 * np.pi * 440 * np.arange(n) / SR)
    pad = rng.normal(0, noise, 4 * FRAME)
    x = np.concatenate([pad, tone, pad])
    return (x * 32768).astype("<i2").tobytes()


def test_voiced_level_of_a_270_ms_burst_is_about_its_length_and_level() -> None:
    voiced_s, dbfs = voiced_level(burst(9, -30), SR)
    assert voiced_s == pytest.approx(0.27, abs=0.031)
    assert dbfs == pytest.approx(-30, abs=1.0)


def test_a_300_ms_burst_reaches_the_minimum() -> None:
    voiced_s, _ = voiced_level(burst(10, -30), SR)
    assert voiced_s >= CFG.stt.min_voiced_s


def test_pure_noise_has_no_voiced_sound() -> None:
    rng = np.random.default_rng(1)
    pcm = (rng.normal(0, 10 ** (-70 / 20), SR) * 32768).astype("<i2").tobytes()
    assert voiced_level(pcm, SR) == (0.0, -100.0)


async def released(rig: Rig) -> None:
    """The turn engine stops waiting for a reply (it listens again)."""

    def listening() -> bool:
        rig.turn.drain()
        return not rig.turn._waiting  # noqa: SLF001

    await until(listening)


async def wake_and_say(rig: Rig, ms: int) -> None:
    rig.turn.on_wake(WakeHit(1.0, "t", [], 0))
    rig.hear(ms, speech=True)
    rig.hear(500, speech=False)


async def test_256_ms_of_speech_never_reaches_groq(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="snow.voice")
    rig = await make_rig(groq, FakeEngine())
    await wake_and_say(rig, 256)
    await until(lambda: "turn_dropped" in caplog.text)

    assert groq.requests == []
    assert of(rig.hub, TranscriptFinal) == []
    await released(rig)
    assert "turn_audio" in caplog.text
    assert "reason=too_short" in caplog.text


async def test_352_ms_of_speech_is_transcribed(groq: FakeGroq) -> None:
    rig = await make_rig(groq, FakeEngine())
    await wake_and_say(rig, 352)
    await until(lambda: bool(of(rig.hub, TranscriptFinal)))
    assert len(groq.requests) == 1


async def test_a_turn_whisper_calls_silent_gets_no_transcript_and_no_reply(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, FakeEngine())
    groq.no_speech_prob, groq.avg_logprob = 0.9, -2.0
    await wake_and_say(rig, 1000)
    await until(lambda: len(groq.requests) == 1)
    await released(rig)
    await rig.pipeline._q.join()  # noqa: SLF001

    assert of(rig.hub, TranscriptFinal) == []
    assert of(rig.hub, ReplyDelta) == [] and of(rig.hub, ReplyFinal) == []
    assert rig.pipeline._reply is None  # noqa: SLF001
