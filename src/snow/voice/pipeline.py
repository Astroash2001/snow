"""Wires source -> wake gate -> turn engine -> Groq -> hub events.

The audio thread runs wake and turn code; everything it wants to publish hops onto the
asyncio loop with `call_soon_threadsafe`, into one queue so events keep their order.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, Literal, Protocol

from snow.contracts.events import (
    AckRequested,
    AudioLevel,
    ConversationEnded,
    ConversationStarted,
    Event,
    PresenceState,
    ReplyFinal,
    TranscriptFinal,
    WakeDetected,
)
from snow.voice.config import VoiceConfig
from snow.voice.phrases import match_command, strip_wake
from snow.voice.sources import AudioSource, Frame
from snow.voice.stt_groq import GroqStt, SttUnavailable
from snow.voice.turn import Presence, TurnEngine
from snow.voice.vad import EndOfTurn, VadDetector
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
        source_name: Literal["voice", "dev"] = "voice",
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
        self._name: Literal["voice", "dev"] = (
            source_name  # the hub requires events to carry the client's role
        )
        self._mode: Literal["awake", "soft_sleep"] = "awake"
        self._pending: str | None = None  # turn whose reply we are waiting for

    @property
    def waiting_reply(self) -> bool:
        return self._pending is not None

    # --- lifecycle (event loop) -------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._publisher_task = asyncio.ensure_future(self._publisher())
        self._source.open(self._on_frame)

    async def wait_done(self) -> None:
        """Run until the source ends (a file) and every transcript is published."""
        while self._source.is_open:  # noqa: ASYNC110 - a thread, not an awaitable
            await asyncio.sleep(0.01)
        self._engine.drain()  # a command answered after the last frame still counts
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
            source=self._name,
            correlation_id=self._conversation,
            **fields,
        )
        self._loop.call_soon_threadsafe(self._q.put_nowait, event)

    # EngineEvents: called on the audio thread.
    def on_wake(self, hit: WakeHit) -> None:
        self._mode = "awake"  # a wake phrase leaves soft sleep (D-10)
        if self._conversation is None:
            self._conversation = uuid.uuid4().hex[:12]
        self._put(WakeDetected, score=hit.score, model=hit.model)

    def on_conversation_start(self) -> None:
        self._put(ConversationStarted, trigger="wake")

    def on_presence(self, state: Presence) -> None:
        if state == "listening":
            self._pending = None  # the reply (or its timeout) is over
        self._put(PresenceState, state=state, mode=self._mode)

    def on_turn_start(self, turn_id: str) -> None: ...

    def on_wake_alone(self) -> None:
        self._put(AckRequested)  # D-09: the brain answers from its acknowledgement pool

    def on_conversation_end(self, reason: str) -> None:
        if reason == "sleep":
            self._mode = "soft_sleep"  # D-10: mic on, wake phrase only
        self._pending = None
        self._put(ConversationEnded, end_reason=reason)
        self._conversation = None

    def on_level(self, level: float) -> None:
        self._put(AudioLevel, channel="mic", level=level)

    def on_turn_end(
        self, turn_id: str, pcm: bytes, duration_ms: int, vad_stop_sample: int
    ) -> None:
        assert self._loop is not None  # noqa: S101
        correlation = self._conversation
        self._pending = turn_id
        self._loop.call_soon_threadsafe(
            self._spawn, self._transcribe(turn_id, correlation, pcm, duration_ms)
        )

    # --- event loop -------------------------------------------------------------

    async def on_hub_event(self, event: Event) -> None:
        """Hub -> voice: a finished reply ends the wait for its turn (or a wake ack)."""
        if isinstance(event, ReplyFinal) and self._pending in (None, event.turn_id):
            self._pending = None  # frees a paced file replay before the engine drains
            self._engine.reply_finished()

    def _release(self, turn_id: str) -> None:
        """This turn will get no reply: stop waiting for one."""
        if self._pending == turn_id:
            self._pending = None
            self._engine.reply_finished()

    async def _transcribe(
        self, turn_id: str, correlation: str | None, pcm: bytes, duration_ms: int
    ) -> None:
        try:
            raw = await self._stt.transcribe(pcm, self._cfg.audio.sample_rate)
        except SttUnavailable as e:
            # Local fallback and its health reporting arrive with plan 01-22.
            log.warning("stt_unavailable kind=%s", e.kind)
            self._release(turn_id)
            return
        except Exception as e:  # noqa: BLE001 - one bad turn must not stop the worker
            log.error("stt_failed kind=%s", type(e).__name__)
            self._release(turn_id)
            return
        text = strip_wake(raw, self._cfg.wake.strip_patterns)
        command = match_command(text, self._cfg.phrases) if text else None
        if command in ("end", "sleep"):  # handled here, so the brain never answers it
            self._engine.end_conversation("phrase" if command == "end" else "sleep")
            return
        if not text or command == "mute":  # mute itself arrives with plan 01-20
            self._release(turn_id)
            return
        await self._q.put(
            TranscriptFinal(
                ts_ns=time.time_ns(),
                source=self._name,
                correlation_id=correlation,
                turn_id=turn_id,
                text=text,
                stt_source="groq",
                duration_ms=duration_ms,
            )
        )


def build_pipeline(
    cfg: VoiceConfig,
    hub: Publisher,
    source: AudioSource,
    stt: GroqStt,
    source_name: Literal["voice", "dev"] = "voice",
) -> VoicePipeline:
    """Real wake gate, VAD and Smart Turn wired to `source` (worker and dev tool)."""
    rate, w = cfg.audio.sample_rate, cfg.wake
    wake = WakeGate(
        w.model, w.threshold, w.patience_frames, w.preroll_frames, w.refractory_s, rate
    )
    engine = TurnEngine(
        cfg.turn,
        VadDetector(rate),
        EndOfTurn(rate),
        sample_rate=rate,
        conversation=cfg.conversation,
    )
    return VoicePipeline(cfg, hub, source, wake, engine, stt, source_name)
