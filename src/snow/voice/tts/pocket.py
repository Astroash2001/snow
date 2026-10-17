"""Pocket TTS, the everyday voice: Kyutai's 100M model on the CPU (D-33, D-39).

The GPU stays free for everything else: this module never asks for a GPU device. Audio
is generated and handed on in memory, never written to disk (D-18). The weights download
once, from Kyutai's own Hugging Face repositories, into the Hugging Face cache.
"""

import asyncio
import logging
import os
import threading
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from snow.voice.tts.base import EngineLoadError, EngineName, Samples
from snow.voice.tts.config import PocketConfig

log = logging.getLogger("snow.voice")

_DONE = object()


class PocketEngine:
    name: EngineName = "pocket_tts"

    def __init__(self, cfg: PocketConfig) -> None:
        self._cfg = cfg
        self.voice_name = cfg.voice
        self.sample_rate = 24000  # replaced by the model's own rate on load
        self._model: Any = None
        self._voice: Any = None
        self._stop = threading.Event()

    def load(self) -> None:
        # A stale cached Hugging Face token makes public repositories fail (Pitfall 14).
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        try:
            import torch  # noqa: PLC0415 - slow import, only when this engine loads
            from pocket_tts import TTSModel  # noqa: PLC0415

            torch.set_num_threads(self._cfg.torch_threads)
            model: Any = TTSModel.load_model()  # CPU: the model has no GPU option here
            self._voice = model.get_state_for_audio_prompt(self._cfg.voice)
            self.sample_rate = int(model.sample_rate)
            self._model = model
        except Exception as e:  # noqa: BLE001 - network, disk and library errors alike
            log.error("tts_load_failed engine=pocket_tts kind=%s", type(e).__name__)
            raise EngineLoadError from e

    def cancel(self) -> None:
        self._stop.set()

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        """Mono float32 chunks as the model decodes them. `emotion` is ignored: Pocket
        has no style control (Cartesia carries the big moments)."""
        del emotion
        if self._model is None:
            raise EngineLoadError
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = threading.Event()
        self._stop = stop

        def work() -> None:
            try:
                for chunk in self._model.generate_audio_stream(
                    self._voice, text, stop=stop
                ):
                    audio = np.asarray(chunk.detach().cpu().numpy(), dtype=np.float32)
                    loop.call_soon_threadsafe(queue.put_nowait, audio)
            except Exception as e:  # noqa: BLE001 - handed to the awaiting side
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        worker = loop.run_in_executor(None, work)
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()  # cancelled or finished: the worker stops at its next chunk
            await worker
