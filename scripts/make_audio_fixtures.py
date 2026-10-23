"""Regenerate (or verify with --check) the synthetic speech test fixtures.

    uv run python scripts/make_audio_fixtures.py          # write, then verify
    uv run python scripts/make_audio_fixtures.py --check  # verify committed WAVs

Speech comes from kokoro-onnx (voice KOKORO_VOICE), never from a microphone, so
no real voice or conversation audio is ever committed (D-18). The wake phrase is
"Hey Jarvis" because the pretrained openWakeWord ``hey_jarvis`` model is the
A/B stand-in the flow tests run on. ``hey_snow_*`` fixtures are scored with the
user's trained ``models/wakeword/hey_snow.onnx`` instead; that file is gitignored, so
--check skips their wake score when it is absent (CI). Model files are cached under
the ignored ``models/`` directory and pinned by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "tests" / "fixtures" / "audio"
KOKORO_DIR = ROOT / "models" / "kokoro"
OWW_DIR = ROOT / "models" / "openwakeword"
HEY_SNOW = ROOT / "models" / "wakeword" / "hey_snow.onnx"

SR = 16_000
# British male "Jarvis" voice; every wake fixture scored >= 0.99 in the audition.
KOKORO_VOICE = "bm_george"
KOKORO_LANG = "en-gb"
# Voices for tv_negative: varied speakers and no wake phrase.
TV_VOICES = [
    ("bm_george", "en-gb"),
    ("af_heart", "en-us"),
    ("am_michael", "en-us"),
    ("bf_emma", "en-gb"),
]
LEAD_S = 0.5  # silence before speech so the wake model's feature buffers are warm
TAIL_S = 1.0
PEAK = 0.5  # every synthesized segment is peak-normalized to -6 dBFS before gain
WAKE_MIN = 0.7  # D-41 stand-in must fire at least this strongly on wake fixtures
NEG_MAX = 0.5  # and never cross the wake threshold on negatives

_KOKORO_RELEASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
)
_KOKORO_FILES = {  # name -> sha256 (official release assets, pinned)
    "kokoro-v1.0.int8.onnx": (
        "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"
    ),
    "voices-v1.0.bin": (
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
    ),
}

Audio = npt.NDArray[np.float32]


def _sil(seconds: float) -> Audio:
    return np.zeros(round(seconds * SR), np.float32)


class Synth:
    """Lazy kokoro wrapper: check mode never loads the 90 MB model."""

    def __init__(self) -> None:
        from kokoro_onnx import Kokoro  # noqa: PLC0415 - heavy import only when generating

        for name, digest in _KOKORO_FILES.items():
            _fetch(_KOKORO_RELEASE + name, KOKORO_DIR / name, digest)
        self._k = Kokoro(
            str(KOKORO_DIR / "kokoro-v1.0.int8.onnx"),
            str(KOKORO_DIR / "voices-v1.0.bin"),
        )

    def say(
        self,
        text: str,
        *,
        speed: float = 1.0,
        voice: str = KOKORO_VOICE,
        lang: str = KOKORO_LANG,
    ) -> Audio:
        samples, rate = self._k.create(text, voice=voice, speed=speed, lang=lang)
        out = resample_poly(samples, SR, rate).astype(np.float32)
        return out * (PEAK / max(float(np.abs(out).max()), 1e-6))


def _fetch(url: str, dest: Path, sha256: str) -> None:
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha256:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)  # noqa: S310 - constant https GitHub release URL
    if hashlib.sha256(dest.read_bytes()).hexdigest() != sha256:
        dest.unlink()
        raise SystemExit(f"FAIL sha256 mismatch for {url}")


def _join(*parts: Audio) -> Audio:
    return np.concatenate([_sil(LEAD_S), *parts, _sil(TAIL_S)])


def _tv_negative(s: Synth) -> Audio:
    sentences = [
        "The quarterly report shows steady growth across all regions.",
        "Tomorrow will be mostly cloudy with a light breeze from the west.",
        "She walked down to the harbour and watched the boats come in.",
        "Preheat the oven and mix the flour with two cups of warm water.",
        "The committee will vote on the new transport plan next week.",
        "Scientists discovered a faint signal coming from a distant galaxy.",
        "He picked up the guitar and played a slow melody by the window.",
        "Traffic is moving slowly on the main bridge because of roadworks.",
        "The match went into extra time after a late equalizer.",
        "Remember to keep the receipt in case you need to return it.",
    ]
    parts: list[Audio] = []
    total, i = 0, 0
    while total < 30 * SR:
        voice, lang = TV_VOICES[i % len(TV_VOICES)]
        parts += [
            s.say(sentences[i % len(sentences)], voice=voice, lang=lang),
            _sil(0.4),
        ]
        total += len(parts[-2]) + len(parts[-1])
        i += 1
    speech = np.concatenate(parts)[: 30 * SR]
    noise = np.random.default_rng(1234).normal(0.0, 0.003, 30 * SR).astype(np.float32)
    return speech + noise


def _gain(x: Audio, db: float) -> Audio:
    return np.clip(x * 10 ** (db / 20), -0.98, 0.98).astype(np.float32)


def _tone_sentence(s: Synth, speed: float, db: float) -> Audio:
    text = "I need the report finished before the meeting this afternoon."
    return _join(_gain(s.say(text, speed=speed), db))


# name -> (builder, (min_s, max_s), wake): wake=True must fire the stand-in,
# wake=False must stay below the wake threshold.
Builder = Callable[[Synth], Audio]
FIXTURES: dict[str, tuple[Builder, tuple[float, float], bool]] = {
    "wake_only": (
        lambda s: _join(s.say("Hey Jarvis."), _sil(3.0 - TAIL_S)),
        (4.5, 6.0),
        True,
    ),
}


def _cmd(gap_s: float) -> Builder:
    return lambda s: _join(
        s.say("Hey Jarvis."), _sil(gap_s), s.say("What is the capital of France?")
    )


FIXTURES.update(
    {
        "wake_cmd_gap0": (_cmd(0.0), (4.0, 6.0), True),
        "wake_cmd_gap150": (_cmd(0.15), (4.0, 6.0), True),
        "wake_cmd_gap600": (_cmd(0.6), (4.5, 6.5), True),
        "mid_thought_pause": (
            lambda s: _join(
                s.say("Hey Jarvis, I was thinking that we could"),
                _sil(1.2),
                s.say("maybe check the weather tomorrow."),
            ),
            (7.0, 10.0),
            True,
        ),
        "tv_negative": (_tv_negative, (30.0, 30.0), False),
        "phrase_thats_all": (
            lambda s: _join(s.say("Hey Jarvis, that's all.")),
            (3.0, 5.0),
            True,
        ),
        "phrase_mute": (lambda s: _join(s.say("Hey Jarvis, mute.")), (2.5, 4.5), True),
        "phrase_mute_substring": (
            lambda s: _join(s.say("Hey Jarvis, mute the speaker in the call.")),
            (4.0, 6.5),
            True,
        ),
        "phrase_go_to_sleep": (
            lambda s: _join(s.say("Hey Jarvis, go to sleep.")),
            (3.0, 5.0),
            True,
        ),
        "conversation_two_turns": (
            lambda s: _join(
                s.say("Hey Jarvis, what time is it?"),
                _sil(2.0),
                s.say("And what day is it?"),
            ),
            (7.0, 10.0),
            True,
        ),
        "hey_snow_cmd": (
            lambda s: _join(s.say("Hey Snow, what time is it?")),
            (2.5, 4.5),
            True,
        ),
        "tone_calm": (lambda s: _tone_sentence(s, 0.85, -10.0), (4.0, 7.5), False),
        "tone_stressed": (lambda s: _tone_sentence(s, 1.35, 6.0), (2.5, 5.0), False),
    }
)


def _wake_model(name: str) -> Path:
    if name.startswith("hey_snow"):
        return HEY_SNOW
    if not (OWW_DIR / "hey_jarvis_v0.1.onnx").exists():
        from openwakeword.utils import download_models  # noqa: PLC0415

        download_models(model_names=["hey_jarvis"], target_directory=str(OWW_DIR))
    return OWW_DIR / "hey_jarvis_v0.1.onnx"


def _wake_score(path: Path, wake_model: Path) -> float:
    from openwakeword.model import Model  # noqa: PLC0415 - only needed to score

    models = OWW_DIR
    model = Model(
        wakeword_models=[str(wake_model)],
        inference_framework="onnx",
        melspec_model_path=str(models / "melspectrogram.onnx"),
        embedding_model_path=str(models / "embedding_model.onnx"),
    )
    pcm, _ = sf.read(path, dtype="int16")
    pcm = np.concatenate(
        [pcm, np.zeros(SR, np.int16)]
    )  # let the final word's score land
    best = 0.0
    for i in range(0, len(pcm) - 1279, 1280):
        best = max(best, float(max(model.predict(pcm[i : i + 1280]).values())))
    return best


def check() -> bool:
    ok = True
    for name, (_, (lo, hi), wake) in FIXTURES.items():
        path = OUT_DIR / f"{name}.wav"
        if not path.exists():
            print(f"FAIL {name}: missing")
            ok = False
            continue
        info = sf.info(path)
        problems: list[str] = []
        if (info.samplerate, info.channels, info.subtype) != (SR, 1, "PCM_16"):
            problems.append(
                f"format {info.samplerate} Hz x{info.channels} {info.subtype}"
            )
        if not lo <= info.duration <= hi:
            problems.append(f"duration {info.duration:.2f}s outside {lo}-{hi}s")
        wake_model = _wake_model(name)
        scored = f"{wake_model.stem} absent, wake score skipped"
        if wake_model.exists():
            score = _wake_score(path, wake_model)
            scored = f"{wake_model.stem}={score:.3f}"
            if wake and score < WAKE_MIN:
                problems.append(f"wake score {score:.3f} < {WAKE_MIN}")
            if not wake and score >= NEG_MAX:
                problems.append(f"negative scored {score:.3f} >= {NEG_MAX}")
        ok &= not problems
        print(
            f"{'FAIL' if problems else 'PASS'} {name}: 16 kHz mono int16 "
            f"{info.duration:.2f}s {scored}" + "".join(f" [{p}]" for p in problems)
        )
    return ok


def generate() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    synth = Synth()
    for name, (build, _, _) in FIXTURES.items():
        audio = build(synth)
        sf.write(OUT_DIR / f"{name}.wav", audio, SR, subtype="PCM_16", format="WAV")
        print(f"wrote {name}.wav ({len(audio) / SR:.2f}s)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed fixtures without rewriting them",
    )
    args = parser.parse_args()
    if not args.check:
        generate()
    return 0 if check() else 1


if __name__ == "__main__":
    sys.exit(main())
