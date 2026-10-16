"""Wires source -> wake gate -> turn engine -> Groq -> hub events.

The audio thread runs wake and turn code; everything it wants to publish hops onto the
asyncio loop with `call_soon_threadsafe`, into one queue so events keep their order.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from snow.contracts.events import (
    ConversationStarted,
    Event,
    PresenceState,
    TranscriptFinal,
    WakeDetected,
)
from snow.voice.config import VoiceConfig
from snow.voice.phrases import strip_wake
from snow.voice.sources import AudioSource, Frame
from snow.voice.stt_groq import GroqStt, SttUnavailable
from snow.voice.turn import Presence, TurnEngine
from snow.voice.wake import WakeGate, WakeHit

log = logging.getLogger("snow.voice")


class Publisher(Protocol):
    async def publish(self, event: Event) -> None: ...


class VoicePipeline:
    def __init__(
        self,
        cfg: VoiceConfig,
        hub: Publisher,
        source: AudioSource,
        wake: WakeGate,
        engine: TurnEngine,
        stt: GroqStt,
    ) -> None:
        self._cfg = cfg
        self._hub = hub
        self._source = source
        self._wake = wake
        self._engine = engine
        self._stt = stt
        engine.events = self
        self._loop: asyncio.AbstractEventLoop | None = None
        self._q: asyncio.Queue[Event] = asyncio.Queue()
        self._tasks: set[asyncio.Future[None]] = set()
        self._publisher_task: asyncio.Future[None]
        self._conversation: str | None = None

    # --- lifecycle (event loop) -------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._publisher_task = asyncio.ensure_future(self._publisher())
        self._source.open(self._on_frame)

    async def wait_done(self) -> None:
        """Run until the source ends (a file) and every transcript is published."""
        while self._source.is_open:  # noqa: ASYNC110 - a thread, not an awaitable
            await asyncio.sleep(0.01)
        await asyncio.sleep(0)  # let call_soon_threadsafe hops from the last frames run
        while self._tasks:  # noqa: ASYNC110 - polls a set of tasks
            await asyncio.sleep(0.01)
        await self._q.join()

    async def stop(self) -> None:
        self._source.close()
        for task in [self._publisher_task, *self._tasks]:
            task.cancel()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _publisher(self) -> None:
        while True:
            event = await self._q.get()
            try:
                await self._hub.publish(event)
            finally:
                self._q.task_done()

    # --- audio thread -----------------------------------------------------------

    def _on_frame(self, frame: Frame) -> None:
        hit = self._wake.process(frame)
        if hit is not None:
            self._engine.on_wake(hit)
        else:
            self._engine.feed(frame)

    def _put(self, cls: Callable[..., Event], **fields: object) -> None:
        """Audio thread: build an event and queue it on the loop, in order."""
        assert self._loop is not None  # noqa: S101 - start() sets it before the source opens
        event = cls(
            ts_ns=time.time_ns(),
            source="voice",
            correlation_id=self._conversation,
            **fields,
        )
        self._loop.call_soon_threadsafe(self._q.put_nowait, event)

    # EngineEvents: called on the audio thread.
    def on_wake(self, hit: WakeHit) -> None:
        if self._conversation is None:
            self._conversation = uuid.uuid4().hex[:12]
        self._put(WakeDetected, score=hit.score, model=hit.model)

    def on_conversation_start(self) -> None:
        self._put(ConversationStarted, trigger="wake")

    def on_presence(self, state: Presence) -> None:
        self._put(PresenceState, state=state, mode="awake")

    def on_turn_start(self, turn_id: str) -> None: ...

    def on_wake_alone(self) -> None: ...

    def on_conversation_end(self, reason: str) -> None:
        self._conversation = None

    def on_level(self, level: float) -> None: ...

    def on_turn_end(
        self, turn_id: str, pcm: bytes, duration_ms: int, vad_stop_sample: int
    ) -> None:
        assert self._loop is not None  # noqa: S101
        correlation = self._conversation
        self._loop.call_soon_threadsafe(
            self._spawn, self._transcribe(turn_id, correlation, pcm, duration_ms)
        )

    # --- event loop -------------------------------------------------------------

    async def _transcribe(
        self, turn_id: str, correlation: str | None, pcm: bytes, duration_ms: int
    ) -> None:
        try:
            raw = await self._stt.transcribe(pcm, self._cfg.audio.sample_rate)
        except SttUnavailable as e:
            # Local fallback and its health reporting arrive with plan 01-22.
            log.warning("stt_unavailable kind=%s", e.kind)
            return
        except Exception as e:  # noqa: BLE001 - one bad turn must not stop the worker
            log.error("stt_failed kind=%s", type(e).__name__)
            return
        text = strip_wake(raw, self._cfg.wake.strip_patterns)
        if not text:
            return
        await self._q.put(
            TranscriptFinal(
                ts_ns=time.time_ns(),
                source="voice",
                correlation_id=correlation,
                turn_id=turn_id,
                text=text,
                stt_source="groq",
                duration_ms=duration_ms,
            )
        )
