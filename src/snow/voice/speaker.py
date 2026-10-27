"""Speaker verification: is this the user's voice? (VOIC-06 barge-in, VOIC-07 base)

NeMo TitaNet-small through sherpa-onnx, on one CPU thread (~40 ms per second of audio).
The model is fetched once into the gitignored `models/speaker/` and loaded only if it
matches the SHA-256 pinned in config/voice.toml (T-wvr-07).

The voiceprint is biometric: it stays on this PC, is never logged, never committed
and is deleted by `snow dev enroll-voice --reset`. Only the unit-length mean
embedding (192 floats) and the calibrated threshold are kept, wrapped with Windows
DPAPI for the current user under %LOCALAPPDATA%/Snow. No audio is stored. Scores
and the threshold may be logged; a vector never is (T-wvr-08).
"""

import importlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from snow.config.settings import data_dir, repo_root
from snow.voice.config import SpeakerConfig
from snow.voice.tts.kokoro import ensure_pinned

log = logging.getLogger("snow.voice")

Vector = npt.NDArray[np.float32]
_ENTROPY = b"snow-voiceprint-v1"  # app-specific DPAPI entropy
_VERSION = 1
_RATE = 16000


def voiceprint_path() -> Path:
    return data_dir() / "voice" / "voiceprint.bin"


@dataclass(frozen=True)
class Voiceprint:
    centroid: Vector  # unit length
    threshold: float  # the cosine at or above which a voice is the user's


def save_voiceprint(
    centroid: Vector, threshold: float, path: Path | None = None
) -> Path:
    """DPAPI-wrap and write the voiceprint (temp file, then an atomic replace)."""
    win32crypt: Any = importlib.import_module("win32crypt")  # Windows only

    dest = path or voiceprint_path()
    body = json.dumps(
        {
            "version": _VERSION,
            "dim": len(centroid),
            "threshold": float(threshold),
            "centroid": [float(x) for x in centroid],
        }
    ).encode()
    blob: bytes = win32crypt.CryptProtectData(
        body, "Snow voiceprint", _ENTROPY, None, None, 0
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, dest)
    return dest


def load_voiceprint(
    path: Path | None = None, dim: int | None = None
) -> Voiceprint | None:
    """The stored voiceprint, or None when it is missing, will not decrypt, is malformed
    or (given `dim`) has the wrong dimension. Logs the failure's class, nothing else."""
    src = path or voiceprint_path()
    if not src.is_file():
        return None
    try:
        win32crypt: Any = importlib.import_module("win32crypt")
        raw: Any = win32crypt.CryptUnprotectData(
            src.read_bytes(), _ENTROPY, None, None, 0
        )
        body: Any = json.loads(bytes(raw[1]))
        centroid = np.asarray(body["centroid"], dtype=np.float32)
        if body["version"] != _VERSION or len(centroid) != int(body["dim"]):
            raise ValueError("bad voiceprint")
        if dim is not None and len(centroid) != dim:
            raise ValueError("wrong voiceprint dimension")
        return Voiceprint(centroid, float(body["threshold"]))
    except Exception as e:  # noqa: BLE001 - any failure means "no usable voiceprint"
        log.error("voiceprint_unreadable kind=%s", type(e).__name__)
        return None


def delete_voiceprint(path: Path | None = None) -> bool:
    """Remove the stored voiceprint; True when there was one."""
    src = path or voiceprint_path()
    existed = src.is_file()
    src.unlink(missing_ok=True)
    return existed


class SpeakerVerifier:
    def __init__(
        self,
        cfg: SpeakerConfig,
        models_dir: Path | None = None,
        store: Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._dir = models_dir or repo_root() / "models" / "speaker"
        self._store = store or voiceprint_path()
        self._extractor: Any = None
        self._print: Voiceprint | None = None
        self._lock = threading.Lock()  # one extractor, one caller at a time
        self.dim = 0

    @property
    def enrolled(self) -> bool:
        """A usable voiceprint is loaded."""
        return self._print is not None

    @property
    def threshold(self) -> float:
        return self._print.threshold if self._print else self._cfg.threshold

    def voiceprint_on_disk(self) -> bool:
        """A voiceprint file exists, loaded or not: Snow must then never run ungated."""
        return self._store.is_file()

    def load(self) -> None:
        """Blocking: fetch (once) and verify the model, build the extractor, read the
        voiceprint. Raises when the model cannot be had; a bad voiceprint loads as
        None."""
        c = self._cfg
        model = ensure_pinned(
            c.model_url, c.model_sha256, self._dir / c.model_url.rsplit("/", 1)[-1]
        )
        sherpa: Any = importlib.import_module("sherpa_onnx")  # native libraries, now
        config = sherpa.SpeakerEmbeddingExtractorConfig(
            model=str(model), num_threads=1, debug=False, provider="cpu"
        )
        extractor = sherpa.SpeakerEmbeddingExtractor(config)
        self._extractor = extractor
        self.dim = int(extractor.dim)
        self._print = load_voiceprint(self._store, self.dim)

    def embed(self, pcm: npt.NDArray[np.int16]) -> Vector:
        """The unit-length embedding of 16 kHz mono int16 audio."""
        wave = pcm.astype(np.float32) / 32768.0
        with self._lock:
            stream: Any = self._extractor.create_stream()
            stream.accept_waveform(sample_rate=_RATE, waveform=wave)
            stream.input_finished()
            vec = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        return vec / max(float(np.linalg.norm(vec)), 1e-9)

    def score(self, pcm: npt.NDArray[np.int16]) -> float | None:
        """Cosine against the voiceprint, or None when no voiceprint is loaded."""
        if self._print is None:
            return None
        return float(self.embed(pcm) @ self._print.centroid)
