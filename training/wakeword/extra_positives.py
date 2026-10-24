"""Extra "Hey Snow" positives for training, on this PC (README section 2c).

    uv run python training/wakeword/extra_positives.py split <recording> <out_dir>
    uv run python training/wakeword/extra_positives.py accents <out_dir> [count]

`split` cuts one recording of the user saying "Hey Snow" with pauses (any format
ffmpeg reads) into one 16 kHz WAV per utterance and prints each clip's score from
the configured wake model. `accents` writes `count` (default 2400) utterances in
Kokoro stock voices: two thirds led by Kokoro's Hindi speakers, the rest other
accents blended with them. Both output folders must sit outside this repository.
"""

import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import numpy as np
import soundfile as sf

from snow.config.settings import config_dir, repo_root

SR = 16000
HOP = 320  # 20 ms


def _outside_repo(path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(repo_root()):
        sys.exit(
            "output folder must be outside the repository (never commit voice data)"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wake_score(clip: np.ndarray) -> float:
    from snow.voice.config import VoiceConfig  # noqa: PLC0415 - only for split
    from snow.voice.wake import WakeGate  # noqa: PLC0415

    w = VoiceConfig.model_validate(
        tomllib.loads((config_dir() / "voice.toml").read_text())
    ).wake
    g = WakeGate(
        w.model,
        w.threshold,
        w.patience_frames,
        w.preroll_frames,
        w.refractory_s,
        SR,
        model_sha256=w.model_sha256,
    )
    pcm = np.concatenate([np.zeros(SR), clip, np.zeros(SR)])
    pcm = np.clip(pcm * 32767, -32768, 32767).astype(np.int16)
    best = 0.0
    for i in range(0, len(pcm) - 1279, 1280):
        g.process(pcm[i : i + 1280])
        best = max(best, g.last_score)
    return best


def split(recording: Path, out: Path) -> None:
    ffmpeg = shutil.which("ffmpeg") or sys.exit("ffmpeg not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "full.wav"
        subprocess.run(  # noqa: S603 - fixed argv, user-chosen input file
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-i",
                str(recording),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(SR),
                "-sample_fmt",
                "s16",
                str(wav),
            ],
            check=True,
        )
        x, _ = sf.read(wav, dtype="float32")

    db = 20 * np.log10(
        np.sqrt(np.convolve(x**2, np.ones(HOP) / HOP, "same")[::HOP] + 1e-12)
    )
    floor = float(np.percentile(db, 20))
    voiced = db > max(floor + 12, -50)
    segs: list[tuple[int, int]] = []
    start: int | None = None
    gap = 0
    for i, v in enumerate(voiced):  # voiced runs; gaps under 350 ms are merged
        if v:
            start = i if start is None else start
            gap = 0
        elif start is not None:
            gap += 1
            if gap * HOP / SR > 0.35:
                segs.append((start, i - gap + 1))
                start, gap = None, 0
    if start is not None:
        segs.append((start, len(voiced)))
    segs = [(a, b) for a, b in segs if 0.3 <= (b - a) * HOP / SR <= 2.5]

    print(f"floor={floor:.0f} dBFS clips={len(segs)}")
    for n, (a, b) in enumerate(segs):
        lo, hi = max(0, a * HOP - 2400), min(len(x), b * HOP + 2400)  # 150 ms pad
        clip = x[lo:hi]
        sf.write(out / f"user_{n:03d}.wav", clip, SR, subtype="PCM_16")
        print(
            f"user_{n:03d} at {lo / SR:5.1f}s len={len(clip) / SR:.2f}s "
            f"score={_wake_score(clip):.2f}"
        )


def accents(out: Path, total: int) -> None:
    import onnxruntime as ort  # noqa: PLC0415 - only for accents
    import soxr  # noqa: PLC0415
    from kokoro_onnx import Kokoro  # noqa: PLC0415

    m = repo_root() / "models" / "kokoro"  # the files Snow's Kokoro voice downloads
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 6
    k = Kokoro.from_session(
        ort.InferenceSession(
            str(m / "kokoro-v1.0.onnx"), opts, providers=["CPUExecutionProvider"]
        ),
        str(m / "voices-v1.0.bin"),
    )
    names = list(k.get_voices())
    indian = [v for v in names if v[:2] in ("hm", "hf")]
    others = [v for v in names if v not in indian and v[0] in "abeifp"]
    phrases = ["Hey Snow", "Hey Snow.", "Hey snow!", "Hey, Snow.", "hey snow"]
    rng = np.random.default_rng(7)
    for n in range(total):
        if n < total * 2 // 3:  # a Hindi speaker, alone or leading a blend
            a, b = str(rng.choice(indian)), str(rng.choice(names))
        else:
            a, b = str(rng.choice(others)), str(rng.choice(indian))
        wa = float(rng.uniform(0.55 if n < total * 2 // 3 else 0.5, 1.0))
        style = wa * k.get_voice_style(a) + (1 - wa) * k.get_voice_style(b)
        audio, sr = k.create(
            str(rng.choice(phrases)),
            voice=style,
            speed=float(rng.uniform(0.8, 1.25)),
            lang="en-us" if rng.random() < 0.7 else "en-gb",
        )
        a16 = soxr.resample(np.asarray(audio, dtype=np.float32), sr, SR)
        a16 *= 10 ** (rng.uniform(-6, 0) / 20) / max(float(np.abs(a16).max()), 1e-6)
        sf.write(out / f"kokoro_{n:05d}.wav", a16, SR, subtype="PCM_16")
        if n % 200 == 0:
            print(f"{n}/{total}", flush=True)
    print("done", total)


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["split", rec, out]:
            split(Path(rec), _outside_repo(Path(out)))
        case ["accents", out, *count]:
            accents(_outside_repo(Path(out)), int(count[0]) if count else 2400)
        case _:
            sys.exit(__doc__)
