"""Kokoro-onnx, the last-resort local voice (SPCH-03, D-33): British male, on the CPU.

It is not a streaming model: each text chunk is synthesized whole in a worker thread, so
the chunker's short first clause keeps the first wait short. Audio stays in memory
(D-18). The two model files come from the official kokoro-onnx release into the
gitignored `models/kokoro/` on first use and are loaded only if they match the SHA-256
pinned in config/tts.toml (T-01-58).
"""

import asyncio
import hashlib
import logging
import os
import threading
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np

from snow.config.settings import repo_root
from snow.voice.tts.base import EngineLoadError, EngineName, Samples
from snow.voice.tts.config import KokoroConfig

log = logging.getLogger("snow.voice")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def ensure_pinned(url: str, sha256: str, dest: Path) -> Path:
    """`dest` if it matches the pin, else fetched (https only) and verified first."""
    if dest.is_file() and _sha256(dest) == sha256.lower():
        return dest
    if not url.startswith("https://"):
        raise ValueError("model url must be https")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, part.open("wb") as f:  # noqa: S310 - https checked above
        while block := r.read(1 << 20):
            f.write(block)
    if _sha256(part) != sha256.lower():
        part.unlink()
        raise ValueError("downloaded model file failed its SHA-256 check")
    os.replace(part, dest)
    return dest


class KokoroEngine:
    name: EngineName = "kokoro"
    sample_rate = 24000

    def __init__(self, cfg: KokoroConfig, models_dir: Path | None = None) -> None:
        self._cfg = cfg
        self._dir = models_dir or repo_root() / "models" / "kokoro"
        self.voice_name = cfg.voice
        self._model: Any = None
        self._stop = threading.Event()

    def load(self) -> None:
        c = self._cfg
        try:
            import onnxruntime as ort  # noqa: PLC0415 - heavy, only when this engine loads
            from kokoro_onnx import Kokoro  # noqa: PLC0415

            model = ensure_pinned(
                c.model_url, c.model_sha256, self._dir / c.model_url.rsplit("/", 1)[-1]
            )
            voices = ensure_pinned(
                c.voices_url,
                c.voices_sha256,
                self._dir / c.voices_url.rsplit("/", 1)[-1],
            )
            opts: Any = ort.SessionOptions()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            opts.intra_op_num_threads = c.threads
            session = ort.InferenceSession(
                str(model), opts, providers=["CPUExecutionProvider"]
            )
            kokoro: Any = Kokoro.from_session(  # pyright: ignore[reportUnknownMemberType]
                session, str(voices)
            )
            if c.voice not in kokoro.voices:
                raise ValueError("voice not in voices file")
            self._model = kokoro
        except Exception as e:  # noqa: BLE001 - network, checksum, disk and library errors alike
            log.error("tts_load_failed engine=kokoro kind=%s", type(e).__name__)
            raise EngineLoadError from e

    def cancel(self) -> None:
        self._stop.set()

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        """The whole chunk as one float32 array; `emotion` is ignored."""
        del emotion
        if self._model is None:
            raise EngineLoadError
        stop = threading.Event()
        self._stop = stop
        model, c = self._model, self._cfg

        def work() -> Samples:
            audio, _rate = model.create(
                text, voice=c.voice, speed=c.speed, lang="en-gb"
            )
            return np.asarray(audio, dtype=np.float32)

        audio = await asyncio.to_thread(work)
        if not stop.is_set():  # cancelled while synthesizing: drop it
            yield audio
