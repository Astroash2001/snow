"""Wires source -> wake gate -> turn engine -> Groq -> hub events.

The audio thread runs wake and turn code; everything it wants to publish hops onto the
asyncio loop with `call_soon_threadsafe`, into one queue so events keep their order.
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any, Literal, Protocol

from snow.contracts.events import (
    AckRequested,
    AudioLevel,
    ConversationEnded,
    ConversationStarted,
    Event,
    HealthSubsystem,
    MuteChanged,
    PresenceState,
    ReplyFinal,
    Tone,
    TranscriptFinal,
    TranscriptPartial,
    TurnCancelled,
    WakeDetected,
)
from snow.contracts.wire import Command, MuteSet, Snapshot
from snow.voice.config import VoiceConfig
from snow.voice.phrases import match_command, strip_wake
from snow.voice.sources import AudioSource, Frame
from snow.voice.stt_groq import GroqStt, SttUnavailable
from snow.voice.stt_router import SttRouter
from snow.voice.tone import ToneAnalyzer
from snow.voice.turn import Presence, TurnEngine
from snow.voice.vad import EndOfTurn, VadDetector
from snow.voice.wake import WakeGate, WakeHit

log = logging.getLogger("snow.voice")

_LEAD_IN_FRAMES = (
    8  # 640 ms kept so a follow-on turn's first word reaches the local model
)


class Publisher(Protocol):
    async def publish(self, event: Event) -> None: ...


class LocalSource(Protocol):
    """The local streaming speech model (`LocalStt`, or a fake in tests)."""

    def start_turn(self) -> None: ...

    def feed(self, frame: Frame) -> None: ...

    def partial(self) -> str | None: ...

    def finish(self) -> "Future[str]": ...

    def cancel(self) -> None: ...


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
        local: LocalSource | None = None,
    ) -> None:
        self._cfg = cfg
        self._hub = hub
        self._source = source
        self._wake = wake
        self._engine = engine
        self._router = SttRouter(
            stt,
            cfg.stt,
            self._emit,
            has_local=local is not None,
            on_change=self._publish_health,
        )
        self._tone = ToneAnalyzer(cfg.tone)
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
        self._speaking: str | None = None  # turn the user is in the middle of
        self._muted = False
        self._seen_snapshot = False
        self._mic_ok = True
        # Live words (VOIC-08). Audio thread only: a turn open on the local model, the
        # last frames (a follow-on turn starts late), samples since the last partial.
        self._local = local
        self._local_turn = False
        self._recent: deque[Frame] = deque(maxlen=_LEAD_IN_FRAMES)
        self._since_partial = 0
        self._last_partial = ""

    @property
    def waiting_reply(self) -> bool:
        return self._pending is not None

    # --- lifecycle (event loop) -------------------------------------------------

    async def start(self, *, listen: bool = True) -> None:
        """`listen=False` (the worker) keeps the microphone closed until a hub snapshot
        says it is unmuted (D-10: after a restart the mic never opens by itself)."""
        self._loop = asyncio.get_running_loop()
        self._publisher_task = asyncio.ensure_future(self._publisher())
        self._publish_health()
        self._router.announce()
        self._muted = not listen
        if listen:
            self._open_source()

    def _open_source(self) -> None:
        self._source.open(self._on_frame)

    def _publish_health(self) -> None:
        """Both rows. Sent at start and on every hub (re)connect: a row sent while the
        hub was away is lost, and the key may have been added meanwhile."""
        self._router.refresh()  # a key stored since the last look counts at once
        status, detail = self._router.health()
        self._emit(
            HealthSubsystem,
            name="speech_to_text",
            label="Speech to text",
            owner="voice",
            status=status,
            detail=detail,
        )
        self._emit(
            HealthSubsystem,
            name="wake_word",
            label="Wake word",
            owner="voice",
            status="running" if self._mic_ok else "restarting",
            detail=None if self._mic_ok else "Microphone unavailable",
        )

    def mic_health(self, ok: bool) -> None:
        """Thread-safe: the microphone was lost (False) or reopened (True)."""
        assert self._loop is not None  # noqa: S101
        self._loop.call_soon_threadsafe(self._set_mic_ok, ok)

    def _set_mic_ok(self, ok: bool) -> None:
        self._mic_ok = ok
        self._publish_health()

    # --- hub -> voice: mute (D-10, VOIC-03) -----------------------------------------

    async def on_snapshot(self, snap: Snapshot) -> None:
        """Every (re)connect. The first one decides whether the mic opens at all."""
        first, self._seen_snapshot = not self._seen_snapshot, True
        if snap.muted:
            self._close_source()  # the hub (or an earlier session) muted us
        elif self._muted and first:
            self._muted = False
            self._open_source()
        elif self._muted:  # we muted but the hub never heard: tell it, stay closed
            self._emit(MuteChanged, muted=True, by="voice")
        self._publish_health()
        if snap.stt is None:  # a hub that restarted forgot the source: say it again
            self._router.announce(force=True)

    async def on_command(self, command: Command) -> None:
        if isinstance(command, MuteSet):
            await self._set_muted(command.muted, command.by)

    def _close_source(self) -> None:
        self._muted = True
        self._source.close()
        self._wake.reset()
        self._engine.mute()
        self._cancel_local()

    async def _set_muted(
        self,
        muted: bool,
        by: Literal["voice", "hud", "tray"],
        *,
        own_turn: str | None = None,
    ) -> None:
        """The only places the source opens or closes: this, and the first snapshot."""
        if muted == self._muted:
            return
        if muted:
            cancelled = self._speaking is not None or self._pending not in (
                None,
                own_turn,
            )
            ended = self._conversation is not None
            self._close_source()
            await asyncio.sleep(0)  # let hops queued by the audio thread land first
            self._pending = self._speaking = None
            self._emit(MuteChanged, muted=True, by=by)
            self._emit(PresenceState, state="muted", mode=self._mode)
            if cancelled:
                self._emit(TurnCancelled, cancel_reason="mute")
            if ended:
                self._emit(ConversationEnded, end_reason="mute")
                self._conversation = None
            return
        self._muted = False
        self._engine.unmute()
        self._wake.reset()
        self._open_source()
        self._emit(MuteChanged, muted=False, by=by)
        self._emit(PresenceState, state="sleeping", mode=self._mode)

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
        self._recent.append(frame)
        if self._local_turn:
            self._feed_local(frame)
        hit = self._wake.process(frame)
        if hit is not None:
            self._engine.on_wake(hit)
        else:
            self._engine.feed(frame)

    def _start_local(self, frames: list[Frame]) -> None:
        if self._local is None or self._local_turn:
            return
        self._local_turn = True
        self._since_partial = 0
        self._last_partial = ""
        self._local.start_turn()
        for frame in frames:
            self._local.feed(frame)

    def _feed_local(self, frame: Frame) -> None:
        assert self._local is not None  # noqa: S101 - _local_turn implies it
        self._local.feed(frame)
        self._since_partial += len(frame)
        turn = self._speaking
        interval = self._cfg.stt.local.partial_interval_ms * self._cfg.audio.sample_rate
        if turn is None or self._since_partial * 1000 < interval:
            return  # no turn id before speech is confirmed; partials wait for it
        self._since_partial = 0
        text = strip_wake(self._local.partial() or "", self._cfg.wake.strip_patterns)
        if text and text != self._last_partial:
            self._last_partial = text
            self._put(TranscriptPartial, turn_id=turn, text=text)

    def _cancel_local(self) -> None:
        if self._local is not None and self._local_turn:
            self._local_turn = False
            self._local.cancel()

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

    def _emit(self, cls: Callable[..., Event], **fields: object) -> None:
        """Event loop: queue an event behind the ones already queued."""
        self._q.put_nowait(
            cls(
                ts_ns=time.time_ns(),
                source=self._name,
                correlation_id=self._conversation,
                **fields,
            )
        )

    # EngineEvents: called on the audio thread.
    def on_wake(self, hit: WakeHit) -> None:
        self._mode = "awake"  # a wake phrase leaves soft sleep (D-10)
        if self._conversation is None:
            self._conversation = uuid.uuid4().hex[:12]
        self._put(WakeDetected, score=hit.score, model=hit.model)
        self._start_local(hit.preroll)  # the words right after the wake phrase count

    def on_conversation_start(self) -> None:
        self._put(ConversationStarted, trigger="wake")

    def on_presence(self, state: Presence) -> None:
        if state == "listening":
            self._pending = None  # the reply (or its timeout) is over
        self._put(PresenceState, state=state, mode=self._mode)

    def on_turn_start(self, turn_id: str) -> None:
        self._speaking = turn_id
        self._start_local(list(self._recent))  # a follow-on turn: no wake started it

    def on_wake_alone(self) -> None:
        self._cancel_local()
        self._put(AckRequested)  # D-09: the brain answers from its acknowledgement pool

    def on_conversation_end(self, reason: str) -> None:
        if reason == "sleep":
            self._mode = "soft_sleep"  # D-10: mic on, wake phrase only
        self._pending = self._speaking = None
        self._cancel_local()
        self._put(ConversationEnded, end_reason=reason)
        self._conversation = None

    def on_level(self, level: float) -> None:
        self._put(AudioLevel, channel="mic", level=level)

    def on_turn_end(
        self, turn_id: str, pcm: bytes, duration_ms: int, vad_stop_sample: int
    ) -> None:
        assert self._loop is not None  # noqa: S101
        correlation = self._conversation
        self._speaking = None
        self._pending = turn_id
        local = self._local.finish() if self._local and self._local_turn else None
        self._local_turn = False  # partials stop with the turn
        self._loop.call_soon_threadsafe(
            self._spawn, self._transcribe(turn_id, correlation, pcm, duration_ms, local)
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
        self,
        turn_id: str,
        correlation: str | None,
        pcm: bytes,
        duration_ms: int,
        local: "Future[str] | None" = None,
    ) -> None:
        try:
            raw, source = await self._router.final(
                pcm, self._cfg.audio.sample_rate, local
            )
        except SttUnavailable as e:  # no source could hear this turn
            log.warning("stt_unavailable kind=%s", e.kind)
            self._release(turn_id)
            return
        except Exception as e:  # noqa: BLE001 - one bad turn must not stop the worker
            log.error("stt_failed kind=%s", type(e).__name__)
            self._release(turn_id)
            return
        if self._muted:  # muted while the audio was up there: the turn is void
            return
        text = strip_wake(raw, self._cfg.wake.strip_patterns)
        command = match_command(text, self._cfg.phrases) if text else None
        if command in ("end", "sleep"):  # handled here, so the brain never answers it
            self._engine.end_conversation("phrase" if command == "end" else "sleep")
            return
        if command == "mute":  # closes the stream itself; unmute is a click only
            await self._set_muted(True, "voice", own_turn=turn_id)
            return
        if not text:
            self._release(turn_id)
            return
        tone = await self._tone_of(pcm, raw)
        if self._muted:  # muted while the tone was measured
            return
        await self._q.put(
            TranscriptFinal(
                ts_ns=time.time_ns(),
                source=self._name,
                correlation_id=correlation,
                turn_id=turn_id,
                text=text,
                stt_source=source,
                duration_ms=duration_ms,
                tone=tone,
            )
        )

    async def _tone_of(self, pcm: bytes, spoken: str) -> Tone | None:
        """Tone never delays or breaks a reply: late or failed means no tone (D-35).
        `spoken` is the unstripped text, so the wake words count toward the pace."""
        task = asyncio.ensure_future(
            asyncio.to_thread(
                self._tone.analyze, pcm, spoken, self._cfg.audio.sample_rate
            )
        )
        try:
            return await asyncio.wait_for(asyncio.shield(task), self._cfg.tone.wait_s)
        except TimeoutError:
            log.warning("tone_late")
        except Exception as e:  # noqa: BLE001
            log.warning("tone_failed kind=%s", type(e).__name__)
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # no warning
        return None


def build_pipeline(
    cfg: VoiceConfig,
    hub: Publisher,
    source: AudioSource,
    stt: GroqStt,
    source_name: Literal["voice", "dev"] = "voice",
    local: LocalSource | None = None,
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
    return VoicePipeline(cfg, hub, source, wake, engine, stt, source_name, local)
