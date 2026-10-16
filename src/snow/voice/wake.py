"""Local wake word gate (VOIC-01). Audio stays on this PC and in RAM until a hit.

openWakeWord runs on CPU through ONNX. A short ring of the most recent frames is the
pre-roll that keeps words spoken right after the wake phrase (D-09).
"""

import collections
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from openwakeword.model import Model  # pyright: ignore[reportMissingTypeStubs]
from openwakeword.utils import download_models  # pyright: ignore[reportMissingTypeStubs]

from snow.config.settings import repo_root

Frame = npt.NDArray[np.int16]

_RING_FRAMES = 25  # about 2 s at 80 ms per frame


@dataclass(frozen=True)
class WakeHit:
    score: float
    model: str
    preroll: list[Frame]  # the frames just before detection plus the detecting frame
    at_sample: int  # samples seen by the gate when it fired (audio time)


def model_files(name: str, models_dir: Path | None = None) -> tuple[Path, Path, Path]:
    """(wake model, melspectrogram, embedding) paths, downloading missing ones once.

    The package resources folder is not populated, so the feature models are passed
    explicitly (plan 01-05 note). Downloads come only from openWakeWord's own releases.
    """
    root = models_dir or repo_root() / "models" / "openwakeword"
    if not name.endswith(".onnx"):
        if not list(root.glob(f"{name}_v*.onnx")):
            download_models(model_names=[name], target_directory=str(root))
        found = sorted(root.glob(f"{name}_v*.onnx"))
        if not found:
            raise FileNotFoundError(f"wake model {name!r} not found in {root}")
        wake = found[-1]
    else:
        wake = Path(name)
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
    ) -> None:
        wake, mel, emb = model_files(model, models_dir)
        self._model = Model(  # pyright: ignore[reportUnknownVariableType]
            wakeword_models=[str(wake)],
            inference_framework="onnx",
            melspec_model_path=str(mel),
            embedding_model_path=str(emb),
        )
        self.name = Path(model).stem
        self._threshold = threshold
        self._patience = patience_frames
        self._preroll = preroll_frames
        self._refractory = int(refractory_s * sample_rate)
        self._ring: collections.deque[Frame] = collections.deque(maxlen=_RING_FRAMES)
        self._streak = 0
        self._samples = 0
        self._quiet_until = 0

    def process(self, frame: Frame) -> WakeHit | None:
        self._ring.append(frame)
        self._samples += len(frame)
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
