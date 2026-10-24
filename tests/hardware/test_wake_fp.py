"""Wake word acceptance on the live microphone (VOIC-01, research Wake Word Plan 5).

Run by hand with Snow stopped (it would hold the microphone), using the configured
`[wake]` model and threshold. Audio is scored in memory only; nothing is stored.

False accepts per hour, with normal room noise and the TV on, for at least two hours
(SNOW_FP_MINUTES, default 120). Target: under 1 per hour.

    uv run pytest -m hardware tests/hardware/test_wake_fp.py -k false_accepts -s -q

Recall: say "Hey Snow" when prompted, 50 times across three distances (arm's length,
across the room, from the doorway). A short beep means "say it now". Target: at least
90 %.

    uv run pytest -m hardware tests/hardware/test_wake_fp.py -k recall -s -q
"""

import os
import queue
import winsound

import pytest

from snow.config.settings import load_config
from snow.voice.config import VoiceConfig
from snow.voice.sources import Frame, MicSource
from snow.voice.wake import WakeGate

pytestmark = pytest.mark.hardware

CFG = load_config("voice.toml", VoiceConfig)
DISTANCES = [("arm's length", 17), ("across the room", 17), ("from the doorway", 16)]
_LISTEN_S = 4.0  # per recall prompt


def _gate() -> WakeGate:
    w, a = CFG.wake, CFG.audio
    g = WakeGate(
        w.model,
        w.threshold,
        w.patience_frames,
        w.preroll_frames,
        w.refractory_s,
        a.sample_rate,
        model_sha256=w.model_sha256,
    )
    if g.error:
        pytest.fail(f"wake model refused: {g.error}")
    return g


def _hits(g: WakeGate, frames: "queue.Queue[Frame]", seconds: float) -> int:
    """Detections in the next `seconds` of microphone audio, printed as they fire."""
    count, heard, need = 0, 0, int(seconds * CFG.audio.sample_rate)
    while heard < need:
        frame = frames.get(timeout=5)
        heard += len(frame)
        hit = g.process(frame)
        if hit is not None:
            count += 1
            print(f"    wake at {heard / CFG.audio.sample_rate:.1f} s: {hit.score:.2f}")
    return count


def _mic() -> tuple[MicSource, "queue.Queue[Frame]"]:
    a = CFG.audio
    mic = MicSource(a.input_device, a.sample_rate, a.frame_samples)
    frames: queue.Queue[Frame] = queue.Queue()
    mic.open(frames.put)
    return mic, frames


def test_false_accepts_per_hour() -> None:
    minutes = float(os.environ.get("SNOW_FP_MINUTES", "120"))
    g = _gate()
    mic, frames = _mic()
    print(f"Listening for {minutes:g} min; every wake below is a false accept.")
    try:
        accepts = _hits(g, frames, minutes * 60)
    finally:
        mic.close()
    rate = accepts / (minutes / 60)
    print(
        f"model={g.name} threshold={CFG.wake.threshold} minutes={minutes:g} "
        f"false_accepts={accepts} false_accepts_per_hour={rate:.2f}"
    )
    assert rate < 1.0


def test_recall_on_the_users_voice() -> None:
    g = _gate()
    mic, frames = _mic()
    heard = total = 0
    try:
        for where, count in DISTANCES:
            input(f'\nStand {where}, then press Enter. Say "Hey Snow" at each prompt.')
            for i in range(count):
                g.reset()
                winsound.Beep(1000, 150)  # "speak now" from far away; blocks until done
                while not frames.empty():  # drop pre-prompt audio and the beep
                    frames.get_nowait()
                print(f'  {i + 1}/{count}: say "Hey Snow" now', flush=True)
                hit = _hits(g, frames, _LISTEN_S) > 0
                heard += hit
                total += 1
                print("    heard" if hit else "    missed")
    finally:
        mic.close()
    recall = heard / total
    print(f"model={g.name} threshold={CFG.wake.threshold} recall={recall:.2f}")
    print(f"heard {heard} of {total}")
    assert recall >= 0.90
