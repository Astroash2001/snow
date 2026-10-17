"""Pocket TTS, the everyday voice: Kyutai's 100M model on the CPU (D-33, D-39).

Pocket has no emotion setting, so the reply's emotion picks a mood clip: a reference of
the same voice spoken calm, upbeat, serious, playful or sympathetic (D-34). A state is
built once per distinct clip at load; a mood without a clip, or whose clip cannot be
loaded, speaks in the base voice.

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
        self.voice_name = cfg.reference.path
        self.sample_rate = 24000  # replaced by the model's own rate on load
        self._model: Any = None
        self._states: dict[str, Any] = {}  # clip path -> voice state, built once
        self._stop = threading.Event()

    def load(self) -> None:
        # A stale cached Hugging Face token makes public repositories fail (Pitfall 14).
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        try:
            import torch  # noqa: PLC0415 - slow import, only when this engine loads
            from pocket_tts import TTSModel  # noqa: PLC0415

            torch.set_num_threads(self._cfg.torch_threads)
            model: Any = TTSModel.load_model()  # CPU: the model has no GPU option here
            self.sample_rate = int(model.sample_rate)
            self._model = model
            self._state(self._cfg.reference.path)  # the base voice must load
        except Exception as e:  # noqa: BLE001 - network, disk and library errors alike
            log.error("tts_load_failed engine=pocket_tts kind=%s", type(e).__name__)
            raise EngineLoadError from e
        self._load_moods()

    def _load_moods(self) -> None:
        for mood, clip in self._cfg.moods.items():
            try:
                self._state(clip.path)
            except Exception as e:  # noqa: BLE001 - e.g. a clip that needs cloning weights
                log.warning(
                    "tts_mood_unavailable mood=%s kind=%s", mood, type(e).__name__
                )

    def _state(self, path: str) -> Any:
        if path not in self._states:
            self._states[path] = self._model.get_state_for_audio_prompt(path)
        return self._states[path]

    def _voice_for(self, emotion: str) -> Any:
        clip = self._cfg.moods.get(self._cfg.mood_for(emotion))
        path = clip.path if clip and clip.path in self._states else None
        return self._states[path or self._cfg.reference.path]

    def cancel(self) -> None:
        self._stop.set()

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        """Mono float32 chunks as the model decodes them, in the mood clip the emotion
        selects (Cartesia carries the big moments)."""
        if self._model is None:
            raise EngineLoadError
        async for chunk in self._speak(self._voice_for(emotion), text):
            yield chunk

    async def preview(self, text: str, path: str) -> AsyncIterator[Samples]:
        """Speak `text` in any one clip, used only by the voice audition tool."""
        if self._model is None:
            raise EngineLoadError
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, self._state, path)
        async for chunk in self._speak(state, text):
            yield chunk

    async def _speak(self, voice: Any, text: str) -> AsyncIterator[Samples]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = threading.Event()
        self._stop = stop

        def work() -> None:
            try:
                for chunk in self._model.generate_audio_stream(voice, text, stop=stop):
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
