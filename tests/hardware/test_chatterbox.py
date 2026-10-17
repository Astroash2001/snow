"""Chatterbox on the real GPU (SPCH-02, D-33, D-39): load time, peak VRAM, first audio.

Run by hand on the laptop, on mains power with the GPU idle:

    uv run pytest -m "hardware and gpu" tests/hardware/test_chatterbox.py -x -q -s

It starts the real isolated server (engines/chatterbox, its own environment; the first
run downloads the official ResembleAI/chatterbox weights), synthesises a few sentences
in memory, prints the numbers and stops the server. Nothing is played, recorded or
written, and the process is always stopped so the VRAM is given back.
"""

import time

import numpy as np
import pytest

from snow.config.settings import load_config, repo_root
from snow.voice.tts.chatterbox import ChatterboxEngine, GpuPolicy, resolve_reference
from snow.voice.tts.config import TtsConfig

pytestmark = [pytest.mark.hardware, pytest.mark.gpu]

SENTENCES = [
    ("The build passed, and everything is merged.", "content"),
    ("That one failed twice before it worked, so I am checking why.", "sympathetic"),
    ("We did it!", "excited"),
]


async def test_chatterbox_loads_and_speaks_on_the_gpu() -> None:
    cfg = load_config("tts.toml", TtsConfig)
    cb = cfg.engines.chatterbox
    policy = GpuPolicy(cb)
    for _ in range(12):  # the desktop makes the GPU busy for a moment now and then
        if policy.refresh():
            break
        time.sleep(5)  # noqa: ASYNC251 - nothing else runs in this test
    else:
        pytest.skip(f"policy is false ({policy.reason}): plug in and let the GPU idle")
    reference = resolve_reference(cb, cfg.engines.pocket_tts)
    engine = ChatterboxEngine(cb, policy, repo_root(), reference)
    engine.load()
    free_before = policy.free_now()
    assert free_before is not None

    started = time.monotonic()
    try:
        engine._start()  # noqa: SLF001 - the blocking load, timed here
        load_s = time.monotonic() - started
        free_after = policy.free_now()
        assert free_after is not None
        print(f"\nload (incl. first-run download and warm-up): {load_s:.1f} s")
        print(f"peak VRAM (torch allocated): {engine.peak_vram_mb:.0f} MB")
        print(
            f"VRAM taken from the GPU (nvidia-smi, incl. CUDA context): "
            f"{free_before - free_after:.0f} MB"
        )
        print(f"min_free_vram_mb to set: {int(free_before - free_after) + 512}")

        for text, emotion in SENTENCES:
            t0 = time.monotonic()
            first_s: float | None = None
            samples = 0
            peak = 0.0
            async for chunk in engine.stream(text, emotion):
                if first_s is None:
                    first_s = time.monotonic() - t0
                samples += len(chunk)
                assert np.isfinite(chunk).all()
                peak = max(peak, float(np.abs(chunk).max()))
            total_s = time.monotonic() - t0
            assert first_s is not None, "no audio came back"
            audio_s = samples / engine.sample_rate
            print(
                f"first audio {first_s:.2f} s, {audio_s:.1f} s of speech in "
                f"{total_s:.2f} s (RTF {total_s / audio_s:.2f}), {emotion}"
            )
            assert peak > 0.01, "silent output"
    finally:
        engine.close()  # always give the VRAM back
    assert not engine.warm()
    assert policy.free_now() is not None
