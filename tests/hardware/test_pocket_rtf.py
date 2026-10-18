"""Battery A/B of Pocket TTS real-time factor with and without `raise_priority()`.

Tests the gap study's inferred cause of "Snow stutters on battery": Windows scheduling
a hidden worker on efficiency cores. Run by hand with the laptop UNPLUGGED, Snow
running and idle (realistic contention) and nothing else heavy:

    uv run pytest -m hardware tests/hardware/test_pocket_rtf.py -s -q

Two hidden child processes run one after the other, each synthesizing the same sentences
in memory with the real Pocket TTS model. Nothing is played or written. The numbers are
printed for the user to report; there is no performance assert.
"""

import json
import subprocess
import sys

import pytest

from snow.config.settings import repo_root

pytestmark = pytest.mark.hardware

CHILD = """
import asyncio, json, sys, time
from snow.common.priority import raise_priority
from snow.config.settings import load_config
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.pocket import PocketEngine

SENTENCES = [
    "The build finished, and every test passed.",
    "I checked the logs and found nothing unusual in them.",
    "Shall I open the report now, or would you rather hear a short summary first?",
]


async def synth(engine, text):
    samples = 0
    async for chunk in engine.stream(text, "neutral"):
        samples += len(chunk)
    return samples


async def main(mode):
    if mode == "boosted":
        raise_priority()
    engine = PocketEngine(load_config("tts.toml", TtsConfig).engines.pocket_tts)
    await asyncio.to_thread(engine.load)
    await synth(engine, "Warm up.")
    started = time.perf_counter()
    samples = 0
    for text in SENTENCES:
        samples += await synth(engine, text)
    took = time.perf_counter() - started
    print(json.dumps({"mode": mode, "rtf": took / (samples / engine.sample_rate),
                      "audio_s": samples / engine.sample_rate}), flush=True)


asyncio.run(main(sys.argv[1]))
"""


def _run(mode: str) -> dict[str, float | str]:
    done = subprocess.run(  # noqa: S603 - our own interpreter and a fixed script
        [sys.executable, "-c", CHILD, mode],
        creationflags=subprocess.CREATE_NO_WINDOW,  # same class as a worker
        cwd=repo_root(),
        capture_output=True,
        timeout=600,
        check=True,
    )
    return json.loads(done.stdout.decode().strip().splitlines()[-1])


def test_pocket_rtf_with_and_without_raised_priority() -> None:
    plain = _run("plain")
    boosted = _run("boosted")
    print(  # noqa: T201 - the numbers are the point of this test
        f"\npocket rtf plain={plain['rtf']:.2f} boosted={boosted['rtf']:.2f} "
        f"ratio={float(boosted['rtf']) / float(plain['rtf']):.2f} "
        f"(audio {plain['audio_s']:.1f}s / {boosted['audio_s']:.1f}s)"
    )
    assert float(plain["audio_s"]) > 0
    assert float(boosted["audio_s"]) > 0
