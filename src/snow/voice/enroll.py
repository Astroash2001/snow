"""`snow dev enroll-voice`: teach Snow the user's voice (VOIC-06, VOIC-07 base).

Two recordings through the same echo-cancelled mic path the live barge-in check
hears: Snow's own voice played through the speakers (the hardest impostor, a TV-like
voice) and about 30 s of the user reading `[speaker].calibration_lines`. The user's
embeddings give a centroid; held-out crops of the user against Snow's voice (and
optional TV speech) give the threshold. It refuses to save when the two sit closer
than `min_margin`.

Everything stays in memory: the only thing written is the DPAPI-wrapped voiceprint
(see speaker.py). Nothing is logged except counts and scores. It refuses to run while
Snow's hub is alive, so Snow cannot answer the calibration lines or pollute them.
"""

import argparse
import asyncio
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import psutil
import soxr

from snow.config.settings import load_config, run_dir
from snow.voice.aec import EchoCanceller
from snow.voice.config import SpeakerConfig, VoiceConfig
from snow.voice.playout import Playout, device_rate
from snow.voice.sources import Frame, MicSource, read_wav
from snow.voice.speaker import (
    SpeakerVerifier,
    Vector,
    delete_voiceprint,
    save_voiceprint,
    voiceprint_path,
)
from snow.voice.tone import voiced_level
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.pocket import PocketEngine

SEGMENT_S, SEGMENT_VOICED_S = 2.0, 1.0  # enrollment windows, and the speech each needs
CROP_S, CROP_HOP_S, CROP_VOICED_S = 0.8, 0.4, 0.5  # what the check hears: one word
MIN_SEGMENTS = 8
HELD_OUT = 5
_TAIL_S = 0.5  # recorded after Snow's voice has drained


def snow_is_running() -> bool:
    """True when the hub's pid is alive. Read-only: it never connects to, signals or
    stops anything. A stale hub.json whose pid is dead counts as not running."""
    try:
        info = json.loads((run_dir() / "hub.json").read_text(encoding="utf-8"))
        return psutil.pid_exists(int(info["pid"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def voiced_seconds(pcm: Frame, rate: int) -> float:
    """Seconds of speech in `pcm`, from tone.voiced_level's documented tuple."""
    return voiced_level(pcm.tobytes(), rate)[0]


def _windows(pcm: Frame, rate: int, size_s: float, hop_s: float) -> list[Frame]:
    size, hop = int(size_s * rate), int(hop_s * rate)
    return [pcm[i : i + size] for i in range(0, len(pcm) - size + 1, hop)]


def _voiced(windows: list[Frame], rate: int, min_voiced_s: float) -> list[Frame]:
    return [w for w in windows if voiced_seconds(w, rate) >= min_voiced_s]


def segments(pcm: Frame, rate: int) -> list[Frame]:
    """2 s windows with at least 1.0 s of speech; silence is dropped."""
    return _voiced(_windows(pcm, rate, SEGMENT_S, SEGMENT_S), rate, SEGMENT_VOICED_S)


def crops(pcm: Frame, rate: int) -> list[Frame]:
    """0.8 s windows at a 0.4 s hop with at least 0.5 s of speech: what the live check
    hears when the user says a word or two."""
    return _voiced(_windows(pcm, rate, CROP_S, CROP_HOP_S), rate, CROP_VOICED_S)


@dataclass(frozen=True)
class Calibration:
    threshold: float | None  # None: refused
    genuine_p5: float
    impostor_max: float
    margin: float


def calibrate(
    genuine: list[float], impostor: list[float], cfg: SpeakerConfig
) -> Calibration:
    """thr = clamp(midpoint(impostor max, genuine p5)); refused under `min_margin`."""
    p5 = float(np.percentile(genuine, 5))
    worst = float(max(impostor))
    margin = p5 - worst
    if margin < cfg.min_margin:
        return Calibration(None, p5, worst, margin)
    thr = min(max((p5 + worst) / 2, cfg.min_threshold), cfg.max_threshold)
    return Calibration(thr, p5, worst, margin)


# --- audio (hardware; faked in tests) -----------------------------------------------


def _mic_path(
    cfg: VoiceConfig,
) -> tuple[MicSource, "queue.Queue[Frame]", EchoCanceller | None]:
    a = cfg.audio
    try:
        aec: EchoCanceller | None = EchoCanceller(a.sample_rate, 24000)
    except Exception:  # noqa: BLE001 - no canceller: the raw mic is what the check hears
        aec = None
    mic = MicSource(a.input_device, a.sample_rate, a.frame_samples)
    q: queue.Queue[Frame] = queue.Queue()
    mic.open(lambda f: q.put(aec.capture(f) if aec else f))
    return mic, q, aec


def record(seconds: float) -> Frame:
    """The echo-cancelled mic for `seconds`, in memory."""
    cfg = load_config("voice.toml", VoiceConfig)
    mic, q, aec = _mic_path(cfg)
    try:
        need, parts = int(seconds * cfg.audio.sample_rate), list[Frame]()
        while need > 0:
            part = q.get(timeout=5)[:need]
            parts.append(part)
            need -= len(part)
    finally:
        mic.close()
        if aec:
            aec.close()
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)


async def _synthesize(engine: PocketEngine, text: str) -> npt.NDArray[np.float32]:
    chunks = [c async for c in engine.stream(text, "neutral")]
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def play_and_capture(text: str) -> Frame:
    """Snow's everyday voice (Pocket TTS) speaks `text` through the speakers with NO
    echo reference, so it reaches the mic like a TV voice; returns what the mic
    heard."""
    cfg = load_config("voice.toml", VoiceConfig)
    tts_cfg = load_config("tts.toml", TtsConfig)
    engine = PocketEngine(tts_cfg.engines.pocket_tts)
    engine.load()
    voice = asyncio.run(_synthesize(engine, text))
    rate = device_rate() or engine.sample_rate
    if rate != engine.sample_rate:
        voice = soxr.resample(voice, engine.sample_rate, rate).astype(np.float32)  # pyright: ignore[reportUnknownMemberType]
    drained = threading.Event()
    playout = Playout(rate, tts_cfg.playout, on_drained=drained.set)
    mic, q, aec = _mic_path(cfg)
    parts: list[Frame] = []
    try:
        playout.start_utterance()
        playout.push(voice)
        playout.end_utterance()
        deadline = time.monotonic() + len(voice) / rate + 15
        while not drained.is_set() and time.monotonic() < deadline:
            _drain(q, parts)
            time.sleep(0.02)
        end = time.monotonic() + _TAIL_S
        while time.monotonic() < end:
            _drain(q, parts)
            time.sleep(0.02)
        _drain(q, parts)
    finally:
        playout.close()
        mic.close()
        if aec:
            aec.close()
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)


def _drain(q: "queue.Queue[Frame]", parts: list[Frame]) -> None:
    while True:
        try:
            parts.append(q.get_nowait())
        except queue.Empty:
            return


def _load_verifier(cfg: SpeakerConfig) -> SpeakerVerifier:
    verifier = SpeakerVerifier(cfg)
    verifier.load()
    return verifier


# --- the tool -----------------------------------------------------------------------


def _scores(
    verifier: SpeakerVerifier, windows: list[Frame], centroid: Vector
) -> list[float]:
    return [float(verifier.embed(w) @ centroid) for w in windows]


def _countdown() -> None:
    for n in (3, 2, 1):
        print(f"  {n}...")
        time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snow dev enroll-voice",
        description="Teach Snow your voice (local only; nothing but the wrapped "
        "voiceprint is saved).",
    )
    parser.add_argument("--reset", action="store_true", help="delete the voiceprint")
    parser.add_argument("--seconds", type=float, default=30, help="your recording")
    parser.add_argument(
        "--tv-seconds",
        type=float,
        default=0,
        help="extra seconds of TV or YouTube speech, played by you, as impostor audio",
    )
    parser.add_argument(
        "--check-clips",
        type=Path,
        help="folder of your WAV clips to score against the new voiceprint",
    )
    args = parser.parse_args(argv)
    if args.reset:
        gone = delete_voiceprint()
        print("Voiceprint deleted." if gone else "There was no voiceprint to delete.")
        return 0
    if snow_is_running():
        print(
            "Snow is running: quit it, then run this again.",
            file=sys.stderr,
        )
        return 2

    cfg = load_config("voice.toml", VoiceConfig)
    sp, rate = cfg.speaker, cfg.audio.sample_rate
    verifier = _load_verifier(sp)

    print("Step 1 of 2: stay quiet while Snow's voice plays through the speakers.")
    snow_pcm = play_and_capture(" ".join(sp.calibration_lines))
    tv_pcm: Frame = np.zeros(0, dtype=np.int16)
    if args.tv_seconds > 0:
        print(f"Now play TV or YouTube speech for {args.tv_seconds:g} s.")
        tv_pcm = record(args.tv_seconds)
    print(f"Step 2 of 2: read these lines aloud, normal voice ({args.seconds:g} s):")
    for line in sp.calibration_lines:
        print(f"  {line}")
    _countdown()
    mine = segments(record(args.seconds), rate)
    if len(mine) < MIN_SEGMENTS:
        print(
            f"Refused: only {len(mine)} usable stretches of your voice were heard "
            f"(need {MIN_SEGMENTS}). Move closer to the mic or speak up, then rerun.",
            file=sys.stderr,
        )
        return 1

    held: set[int] = {int(i) for i in np.linspace(0, len(mine) - 1, HELD_OUT).round()}
    rest = [verifier.embed(s) for i, s in enumerate(mine) if i not in held]
    centroid: Vector = np.mean(rest, axis=0).astype(np.float32)
    centroid /= max(float(np.linalg.norm(centroid)), 1e-9)

    genuine = _scores(
        verifier, [c for i in sorted(held) for c in crops(mine[i], rate)], centroid
    )
    impostor = _scores(verifier, crops(snow_pcm, rate) + crops(tv_pcm, rate), centroid)
    if not genuine or not impostor:
        print(
            "Refused: no usable speech was captured for "
            f"{'your voice' if not genuine else 'Snow'}'s calibration "
            "(speaker volume too low?). Rerun with the speakers a bit louder.",
            file=sys.stderr,
        )
        return 1
    result = calibrate(genuine, impostor, sp)
    print(
        f"Your voice (5th percentile) {result.genuine_p5:.2f}; Snow and TV (highest) "
        f"{result.impostor_max:.2f}; margin {result.margin:.2f} "
        f"(needs {sp.min_margin:.2f})."
    )
    if args.check_clips is not None:
        clip_scores = _scores(
            verifier,
            [read_wav(p, rate) for p in sorted(args.check_clips.glob("*.wav"))],
            centroid,
        )
        if clip_scores:
            print(
                f"Your clips ({len(clip_scores)}): min {min(clip_scores):.2f}, mean "
                f"{float(np.mean(clip_scores)):.2f}, max {max(clip_scores):.2f}."
            )
    if result.threshold is None:
        print(
            "Refused: your voice and Snow's are too close to tell apart. Sit closer "
            "to the mic, use a quieter room, or lower the speaker volume, then rerun.",
            file=sys.stderr,
        )
        return 1
    save_voiceprint(centroid, result.threshold)
    print(f"Saved (threshold {result.threshold:.2f}): {voiceprint_path()}")
    print("Restart Snow to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
