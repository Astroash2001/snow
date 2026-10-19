"""Local wake word gate (VOIC-01). Audio stays on this PC and in RAM until a hit.

openWakeWord runs on CPU through ONNX. A short ring of the most recent frames is the
pre-roll that keeps words spoken right after the wake phrase (D-09).

A custom model (a path ending in .onnx, e.g. the user's trained "hey snow") is loaded
only when its SHA-256 matches `[wake] model_sha256` (T-01-45). A missing or mismatched
file leaves the gate deaf with `error` set, so the worker reports it instead of dying.
"""

import collections
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from openwakeword.model import Model  # pyright: ignore[reportMissingTypeStubs]
from openwakeword.utils import download_models  # pyright: ignore[reportMissingTypeStubs]

from snow.config.settings import repo_root

log = logging.getLogger("snow.voice")

Frame = npt.NDArray[np.int16]

_RING_FRAMES = 25  # about 2 s at 80 ms per frame


@dataclass(frozen=True)
class WakeHit:
    score: float
    model: str
    preroll: list[Frame]  # the frames just before detection plus the detecting frame
    at_sample: int  # samples seen by the gate when it fired (audio time)


class WakeModelError(Exception):
    """The configured wake model cannot be used; the message is the health detail."""


def model_files(
    name: str, models_dir: Path | None = None, sha256: str = ""
) -> tuple[Path, Path, Path]:
    """(wake model, melspectrogram, embedding) paths, downloading missing ones once.

    The package resources folder is not populated, so the feature models are passed
    explicitly (plan 01-05 note). Downloads come only from openWakeWord's own releases.
    A path (ending .onnx, relative to the repo) must match `sha256`; a pretrained name
    is checked only when `sha256` is set.
    """
    root = models_dir or repo_root() / "models" / "openwakeword"
    custom = name.endswith(".onnx")
    if custom:
        wake = repo_root() / name  # an absolute `name` replaces the repo root
        if not (root / "melspectrogram.onnx").exists():
            # a name no official model contains: fetches only the feature models
            download_models(
                model_names=["feature-models-only"], target_directory=str(root)
            )
    else:
        if not list(root.glob(f"{name}_v*.onnx")):
            download_models(model_names=[name], target_directory=str(root))
        found = sorted(root.glob(f"{name}_v*.onnx"))
        if not found:
            raise WakeModelError("Wake model missing")
        wake = found[-1]
    if not wake.is_file():
        raise WakeModelError("Wake model missing")
    if custom or sha256:
        digest = hashlib.sha256(wake.read_bytes()).hexdigest()
        if digest != sha256.strip().lower():
            log.error("wake_model_checksum_mismatch file=%s sha256=%s", wake, digest)
            raise WakeModelError("Wake model checksum mismatch")
    return wake, root / "melspectrogram.onnx", root / "embedding_model.onnx"


class WakeGate:
    def __init__(
        self,
        model: str,
        threshold: float,
        patience_frames: int,
        preroll_frames: int,
        refractory_s: float,
        sample_rate: int = 16000,
        models_dir: Path | None = None,
        model_sha256: str = "",
    ) -> None:
        self.name = Path(model).stem
        self.error: str | None = (
            None  # set when the model was refused: the gate is deaf
        )
        self._model: Model | None = None
        try:
            wake, mel, emb = model_files(model, models_dir, model_sha256)
        except WakeModelError as e:
            log.error("wake_model_refused model=%s reason=%s", model, e)
            self.error = str(e)
        else:
            self._model = Model(
                wakeword_models=[str(wake)],
                inference_framework="onnx",
                melspec_model_path=str(mel),
                embedding_model_path=str(emb),
            )
        self._threshold = threshold
        self._patience = patience_frames
        self._preroll = preroll_frames
        self._refractory = int(refractory_s * sample_rate)
        self._ring: collections.deque[Frame] = collections.deque(maxlen=_RING_FRAMES)
        self._streak = 0
        self._samples = 0
        self._quiet_until = 0

    def reset(self) -> None:
        """Forget all audio heard so far (no pre-mute audio in a later pre-roll)."""
        self._ring.clear()
        self._streak = 0
        if self._model is not None:
            self._model.reset()  # pyright: ignore[reportUnknownMemberType]

    def process(self, frame: Frame) -> WakeHit | None:
        self._ring.append(frame)
        self._samples += len(frame)
        if self._model is None:
            return None
        scores: dict[str, float] = self._model.predict(frame)  # pyright: ignore[reportUnknownMemberType, reportAssignmentType, reportUnknownVariableType]
        score = float(max(scores.values()))
        if self._samples < self._quiet_until:
            return None
        self._streak = self._streak + 1 if score >= self._threshold else 0
        if self._streak < self._patience:
            return None
        self._streak = 0
        self._quiet_until = self._samples + self._refractory
        self._model.reset()  # pyright: ignore[reportUnknownMemberType]
        return WakeHit(
            score=score,
            model=self.name,
            preroll=list(self._ring)[-(self._preroll + 1) :],
            at_sample=self._samples,
        )
