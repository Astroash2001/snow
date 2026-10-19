"""`snow dev record-negatives`: room audio to train the wake word (VOIC-01, T-01-46).

An explicit developer action. It records the microphone (16 kHz mono, 10-minute WAV
files) into a folder the user names, which must be outside the repository and outside
the Snow data folder, so these files never mix with the conversation log or get
committed. Nothing is uploaded: the user takes the files to training by hand.
"""

import argparse
import queue
import sys
import time
import wave
from collections.abc import Iterable
from pathlib import Path

from snow.config.settings import data_dir, load_config, repo_root
from snow.voice.config import VoiceConfig
from snow.voice.sources import Frame, MicSource

_FILE_S = 600  # 10 minutes per WAV file


def refuse_reason(out: Path) -> str | None:
    """Why `out` may not hold negatives, or None when it may."""
    target = out.expanduser().resolve()
    for name, root in (
        ("the repository", repo_root()),
        ("the Snow data folder", data_dir()),
    ):
        if target.is_relative_to(root.resolve()):  # Windows paths compare case-blind
            return f"{target} is inside {name} ({root}); choose a folder outside it"
    return None


def write_chunks(
    frames: Iterable[Frame], out: Path, rate: int, file_s: int = _FILE_S
) -> list[Path]:
    """Write frames as consecutive mono 16-bit WAV files of at most `file_s` seconds."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    written: list[Path] = []
    w: wave.Wave_write | None = None
    room = 0
    try:
        for frame in frames:
            while len(frame):
                if w is None or room == 0:
                    if w is not None:
                        w.close()
                    path = out / f"negatives-{stamp}-{len(written) + 1:03d}.wav"
                    w = wave.open(str(path), "wb")  # noqa: SIM115 - rotated by hand
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(rate)
                    written.append(path)
                    room = file_s * rate
                part, frame = frame[:room], frame[room:]
                w.writeframes(part.tobytes())
                room -= len(part)
    finally:
        if w is not None:
            w.close()
    return written


def _mic_frames(device: str, rate: int, frame: int, seconds: float) -> Iterable[Frame]:
    mic = MicSource(device, rate, frame)
    q: queue.Queue[Frame] = queue.Queue()
    mic.open(q.put)
    try:
        need = int(seconds * rate)
        while need > 0:
            got = q.get()[:need]
            need -= len(got)
            yield got
    finally:
        mic.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snow dev record-negatives",
        description="Record room and TV audio for wake word training (local only).",
    )
    parser.add_argument("--minutes", type=float, required=True)
    parser.add_argument(
        "--out", type=Path, required=True, help="folder outside the repo"
    )
    args = parser.parse_args(argv)
    if args.minutes <= 0:
        parser.error("--minutes must be above 0")
    reason = refuse_reason(args.out)
    if reason:
        print(f"snow: refusing to record: {reason}", file=sys.stderr)
        return 2
    out: Path = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    audio = load_config("voice.toml", VoiceConfig).audio
    print(f"Recording {args.minutes:g} min of microphone audio into {out}")
    print("These files are for wake word training only. Ctrl+C stops early.")
    frames = _mic_frames(
        audio.input_device, audio.sample_rate, audio.frame_samples, args.minutes * 60
    )
    try:
        write_chunks(frames, out, audio.sample_rate)
    except KeyboardInterrupt:
        print("Stopped early; the files written so far are complete.")
    print(f"Done. Files are in {out}. Upload them only to your own training run.")
    return 0
