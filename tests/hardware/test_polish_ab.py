"""Hand-run A/B of Snow's voice polish through the real live speaker path.

    uv run pytest -m hardware tests/hardware/test_polish_ab.py -s -q

Plays three labelled clips of the audition line through the real speakers, one after
the other: A paul raw (only the device-rate resample), B paul polished (the shipped
[polish]), C george polished. It writes nothing to disk and opens no microphone; the
peak and RMS levels are printed as numbers. There is no assert on the sound: judge by
ear.
"""

import asyncio
import threading

import numpy as np
import pytest

from snow.config.settings import load_config
from snow.voice.playout import Playout, device_rate
from snow.voice.polish import Polish
from snow.voice.tts.base import Samples
from snow.voice.tts.config import PolishConfig, TtsConfig
from snow.voice.tts.pocket import PocketEngine
from snow.voice.tts.text import SentenceChunker

pytestmark = pytest.mark.hardware

DRAIN_TIMEOUT_S = 60.0
RAW = PolishConfig(
    trim_edges=False,
    compressor=False,
    makeup_db=0.0,
    pace=1.0,
    sentence_pause_ms=0,
    comma_pause_ms=0,
    eq=False,
    warmth_db=3.0,
    presence_db=2.0,
    reverb_wet=0.0,
)


def _db(x: float) -> float:
    return 20 * float(np.log10(max(x, 1e-9)))


def _levels(audio: Samples, rate: int) -> str:
    """Peak, whole-clip RMS and voiced-frame RMS (frames above -45 dBFS), in dBFS."""
    frame = rate // 100
    frames = audio[: len(audio) // frame * frame].reshape(-1, frame).astype(np.float64)
    voiced = frames[np.sqrt(np.mean(frames**2, axis=1)) > 10 ** (-45 / 20)]
    return (
        f"peak={_db(float(np.max(np.abs(audio)))):.1f} dBFS "
        f"rms={_db(float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))):.1f} dBFS "
        f"voiced_rms={_db(float(np.sqrt(np.mean(voiced**2)))):.1f} dBFS"
    )


async def _synthesize(engine: PocketEngine, line: str) -> list[tuple[str, Samples]]:
    chunker = SentenceChunker()
    texts = chunker.feed(line) + chunker.flush()
    clips: list[tuple[str, Samples]] = []
    for text in texts:
        parts = [c async for c in engine.stream(text, "calm")]
        clips.append((text, np.concatenate(parts)))
    return clips


def _play(
    label: str,
    clips: list[tuple[str, Samples]],
    cfg: TtsConfig,
    polish_cfg: PolishConfig,
    engine_rate: int,
) -> None:
    rate = device_rate() or engine_rate
    drained = threading.Event()
    playout = Playout(rate, cfg.playout, on_drained=drained.set)
    polish = Polish(polish_cfg, engine_rate, rate)
    heard: list[Samples] = []
    print(f"\n--- {label} (speaker {rate} Hz, voice {engine_rate} Hz)")  # noqa: T201
    try:
        playout.start_utterance()
        for text, audio in clips:
            for part in (polish.process(audio), polish.end_clause(text)):
                if len(part):
                    heard.append(part)
                    playout.push(part)
        if len(tail := polish.flush()):
            heard.append(tail)
            playout.push(tail)
        playout.end_utterance()
        assert drained.wait(DRAIN_TIMEOUT_S), "the clip never drained"
    finally:
        playout.close()
    print(_levels(np.concatenate(heard), rate))  # noqa: T201 - numbers only


def test_paul_raw_vs_polished_and_george_polished() -> None:
    cfg = load_config("tts.toml", TtsConfig)
    pocket = cfg.engines.pocket_tts
    paul = PocketEngine(pocket)
    george_clip = pocket.reference.model_copy(update={"path": "george"})
    george = PocketEngine(
        pocket.model_copy(update={"reference": george_clip, "moods": {}})
    )
    paul.load()
    george.load()

    async def synth() -> tuple[list[tuple[str, Samples]], list[tuple[str, Samples]]]:
        return (
            await _synthesize(paul, cfg.audition_line),
            await _synthesize(george, cfg.audition_line),
        )

    paul_clips, george_clips = asyncio.run(synth())
    _play("A paul raw", paul_clips, cfg, RAW, paul.sample_rate)
    _play("B paul polished", paul_clips, cfg, cfg.polish, paul.sample_rate)
    _play("C george polished", george_clips, cfg, cfg.polish, george.sample_rate)
