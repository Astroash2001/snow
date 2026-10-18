"""Wires source -> wake gate -> turn engine -> Groq -> hub events.

The audio thread runs wake and turn code; everything it wants to publish hops onto the
asyncio loop with `call_soon_threadsafe`, into one queue so events keep their order.
"""

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
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
    ReplyDelta,
    ReplyFinal,
    ReplyInterrupted,
    Tone,
    TranscriptFinal,
    TranscriptPartial,
    TtsSpoken,
    TurnCancelled,
    TurnTiming,
    WakeDetected,
)
from snow.contracts.wire import Command, MuteSet, Snapshot
from snow.voice.config import VoiceConfig
from snow.voice.phrases import match_command, strip_wake
from snow.voice.playout import Playout, StreamFactory
from snow.voice.sources import AudioSource, Frame
from snow.voice.stt_groq import GroqStt, SttUnavailable
from snow.voice.stt_router import SttRouter
from snow.voice.tone import ToneAnalyzer
from snow.voice.tts.base import EngineName, Samples, TtsEngine
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.router import VoiceRouter
from snow.voice.tts.text import SentenceChunker
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


@dataclass
class _Reply:
    """One reply being spoken: its text chunks go in `queue`, None ends the reply."""

    turn_id: str | None
    started: float  # monotonic, when its first text arrived
    waited: bool  # a turn waits for it, so the engine emits the listening state
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue[str | None])
    task: "asyncio.Future[None] | None" = None
    emotion: str = "neutral"
    big_moment: bool = False
    chars: int = 0
    first_audio_ms: int | None = None
    spoke: bool = False  # the first sample has reached the speaker
    # Wall-clock marks of this reply's turn (SPCH-04); None where a stage did not occur.
    vad_stop_ns: int | None = None
    stt_final_ns: int | None = None
    llm_first_token_ns: int | None = None
    tts_first_audio_ns: int | None = None
    audio_out_first_ns: int | None = None
    pushed: int = 0  # samples handed to the playout so far
    # (text, samples pushed before it) per chunk, to tell what was heard if cut off
    chunks: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])

    def heard(self, played: int) -> str:
        """The chunks the speaker had begun by `played` samples (per sentence)."""
        return " ".join(text for text, start in self.chunks if start < played)


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
        tts: Mapping[EngineName, TtsEngine] | None = None,
        tts_cfg: TtsConfig | None = None,
        stream_factory: StreamFactory | None = None,
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
        # Speech output (SPCH-03). Loop thread only, except the three playout callbacks,
        # which hop onto the loop before touching anything here.
        self._tts = (
            VoiceRouter(tts, tts_cfg, self._emit)
            if tts and tts_cfg is not None
            else None
        )
        self._tts_cfg = tts_cfg
        self._stream_factory = stream_factory
        self._tts_ready: asyncio.Event
        self._playout: Playout | None = None
        self._chunker = SentenceChunker()
        self._reply: _Reply | None = None
        # Turns whose reply the user cut off: their late deltas must not start it again.
        self._dropped: deque[str] = deque(maxlen=8)
        # turn id -> [VAD stop, STT final] wall-clock ns, until its reply takes them
        self._marks: dict[str, list[int | None]] = {}

    @property
    def waiting_reply(self) -> bool:
        return self._pending is not None

    # --- lifecycle (event loop) -------------------------------------------------

    async def start(self, *, listen: bool = True) -> None:
        """`listen=False` (the worker) keeps the microphone closed until a hub snapshot
        says it is unmuted (D-10: after a restart the mic never opens by itself)."""
        self._loop = asyncio.get_running_loop()
        self._publisher_task = asyncio.ensure_future(self._publisher())
        self._tts_ready = asyncio.Event()
        self._publish_health()
        self._router.announce()
        if self._tts_cfg is not None and not self._tts_cfg.playout.assume_headphones:
            log.warning("speakers_without_echo_cancellation barge_in_hears_snow")
        if self._tts is not None:
            self._tts.start()
            self._spawn(self._load_tts(self._tts))
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
        if self._tts is not None:
            self._tts.announce(force=True)

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
        if self._tts is not None:  # the Cartesia budget starts from the hub's count
            self._tts.on_snapshot(snap.cartesia_chars_today)
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
        self._stop_speech()

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
        self._stop_speech()
        if self._tts is not None:
            self._tts.stop()
        if self._playout is not None:
            self._playout.close()
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

    def on_barge_in(self) -> None:
        """The user talked over Snow (VOIC-06). Silence first, on this thread; the loop
        then cancels synthesis and generation and reports what was heard."""
        playout, played = self._playout, 0
        if playout is not None:
            played = playout.played  # abort resets it
            playout.abort()
        self._pending = None
        self._hop(self._interrupt, played)

    def on_turn_end(
        self, turn_id: str, pcm: bytes, duration_ms: int, vad_stop_sample: int
    ) -> None:
        assert self._loop is not None  # noqa: S101
        correlation = self._conversation
        self._speaking = None
        self._pending = turn_id
        self._marks[turn_id] = [time.time_ns(), None]
        if len(self._marks) > 16:  # turns answered without a reply leave theirs behind
            del self._marks[next(iter(self._marks))]
        local = self._local.finish() if self._local and self._local_turn else None
        self._local_turn = False  # partials stop with the turn
        self._loop.call_soon_threadsafe(
            self._spawn, self._transcribe(turn_id, correlation, pcm, duration_ms, local)
        )

    # --- event loop -------------------------------------------------------------

    async def on_hub_event(self, event: Event) -> None:
        """Hub -> voice: the reply is spoken as it streams in; a finished reply ends the
        wait for its turn (or a wake ack) once played, or at once if silent."""
        if (
            isinstance(event, ReplyDelta | ReplyFinal)
            and event.turn_id in self._dropped
        ):
            return  # the user cut this reply off; the brain is stopping it
        if self._tts is not None and not self._muted:
            if isinstance(event, ReplyDelta) and self._pending in (None, event.turn_id):
                self._speak(event.turn_id, event.text, event.emotion, event.big_moment)
            elif isinstance(event, ReplyFinal) and self._speak_final(event):
                return
        if isinstance(event, ReplyFinal) and self._pending in (None, event.turn_id):
            self._pending = None  # frees a paced file replay before the engine drains
            self._engine.reply_finished()

    # --- speech output (SPCH-03, SPCH-04) -------------------------------------------

    async def _load_tts(self, router: VoiceRouter) -> None:
        assert self._tts_cfg is not None  # noqa: S101 - a router comes with its config
        if await router.wait_ready():
            self._playout = Playout(
                router.sample_rate,
                self._tts_cfg.playout,
                on_first_audio=lambda ts_ns: self._hop(self._first_audio, ts_ns),
                on_level=lambda level: self._hop(self._tts_level, level),
                on_drained=lambda: self._hop(self._drained),
                stream_factory=self._stream_factory,
            )
        self._tts_ready.set()  # no playout: no voice loaded, replies stay silent

    def _hop(self, fn: Callable[..., None], *args: object) -> None:
        """Audio thread -> event loop."""
        assert self._loop is not None  # noqa: S101
        self._loop.call_soon_threadsafe(fn, *args)

    def _begin(self, turn_id: str | None) -> _Reply:
        reply = self._reply
        if reply is not None and reply.turn_id == turn_id:
            return reply
        self._stop_speech()  # a newer reply replaces the one still playing
        reply = self._reply = _Reply(
            turn_id, time.monotonic(), waited=self._pending is not None
        )
        reply.llm_first_token_ns = time.time_ns()
        vad_stop, stt_final = self._marks.pop(turn_id or "", [None, None])
        reply.vad_stop_ns, reply.stt_final_ns = vad_stop, stt_final
        task = reply.task = asyncio.ensure_future(self._run_reply(reply))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return reply

    def _speak(
        self,
        turn_id: str | None,
        text: str,
        emotion: str | None = None,
        big_moment: bool = False,
    ) -> None:
        reply = self._begin(turn_id)
        # The brain knows both before the first word, so the first chunk already reaches
        # the right voice (the reply's final event repeats them for late joiners).
        reply.emotion = emotion or reply.emotion
        reply.big_moment = reply.big_moment or big_moment
        for chunk in self._chunker.feed(text):
            reply.queue.put_nowait(chunk)

    def _speak_final(self, event: ReplyFinal) -> bool:
        """Close the reply's text. False when there is nothing to say (D-41: silent)."""
        if self._pending not in (None, event.turn_id):
            return False
        reply = self._reply
        if reply is None or reply.turn_id != event.turn_id:
            if not event.text.strip():
                return False
            self._speak(event.turn_id, event.text)  # no deltas came: say the final text
            reply = self._reply
        assert reply is not None  # noqa: S101 - _speak just made it
        reply.emotion = event.emotion
        reply.big_moment = event.big_moment
        for chunk in self._chunker.flush():
            reply.queue.put_nowait(chunk)
        reply.queue.put_nowait(None)
        self._pending = None  # the reply is ours now: the end of playback ends the wait
        return True

    async def _run_reply(self, reply: _Reply) -> None:
        assert self._tts is not None  # noqa: S101
        await self._tts_ready.wait()
        playout = self._playout
        try:
            if playout is None:  # the voice did not load: stay silent, never block
                while await reply.queue.get() is not None:
                    pass
                self._finish(reply)
                return
            playout.start_utterance()

            async def texts() -> AsyncIterator[str]:
                while (text := await reply.queue.get()) is not None:
                    reply.chars += len(text)
                    reply.chunks.append((text, reply.pushed))
                    yield text

            def push(audio: Samples) -> None:
                reply.tts_first_audio_ns = reply.tts_first_audio_ns or time.time_ns()
                reply.pushed += len(audio)
                playout.push(audio)

            # The router picks the engine and fails over mid-reply (SPCH-03).
            await self._tts.speak(texts(), reply.emotion, reply.big_moment, push)
            playout.end_utterance()  # `_drained` follows when the last sample is out
        except Exception as e:  # noqa: BLE001 - a failed voice must not wedge the loop
            log.error("tts_failed kind=%s error=%s", type(e).__name__, e)
            if playout is not None:
                playout.abort()
            self._finish(reply)

    def _first_audio(self, ts_ns: int) -> None:
        reply = self._reply
        if reply is None or reply.spoke:
            return
        reply.spoke = True
        reply.audio_out_first_ns = ts_ns
        self._engine.set_speaking(True)  # from here the user can talk over it
        reply.first_audio_ms = int((time.monotonic() - reply.started) * 1000)
        self._emit(PresenceState, state="speaking", mode=self._mode)

    def _tts_level(self, level: float) -> None:
        if self._reply is not None and self._reply.spoke:
            self._emit(AudioLevel, channel="tts", level=level)

    def _drained(self) -> None:
        if self._reply is not None:
            self._finish(self._reply)

    def _finish(self, reply: _Reply) -> None:
        """Playback is over (or there was none): listen again, report what was said."""
        assert self._tts is not None  # noqa: S101
        if self._reply is not reply:
            return
        self._reply = None
        self._publish_timing(reply)
        spoken = self._tts.take_spoken()
        if reply.spoke:
            # One row per voice that spoke: the hub counts Cartesia's characters.
            by_voice = spoken or {self._tts.spoke_with or "pocket_tts": reply.chars}
            for engine, chars in by_voice.items():
                self._emit(
                    TtsSpoken,
                    engine=engine,
                    chars=chars,
                    first_audio_ms=reply.first_audio_ms,
                )
            if not reply.waited:  # no turn is waiting, so the engine will not say it
                self._emit(PresenceState, state="listening", mode=self._mode)
        self._engine.reply_finished()

    def _interrupt(self, played: int) -> None:
        """Loop side of a barge-in: end the reply for good, record what was heard."""
        reply = self._reply
        if reply is None:  # it ended by itself as the user began to talk
            return
        turn_id, heard = reply.turn_id, reply.heard(played)
        if self._tts is not None and (n := self._tts.spoken.get("cartesia")):
            self._emit(TtsSpoken, engine="cartesia", chars=n)  # its credits were spent
        self._stop_speech()
        self._publish_timing(reply)
        if turn_id is not None:  # a wake acknowledgement has no turn to cancel
            self._dropped.append(turn_id)
            self._emit(TurnCancelled, turn_id=turn_id, cancel_reason="barge_in")
        self._emit(ReplyInterrupted, turn_id=turn_id, spoken_text=heard)

    def _publish_timing(self, reply: _Reply) -> None:
        """One `turn.timing` per answered turn (an acknowledgement has no VAD stop)."""
        if reply.vad_stop_ns is None:
            return
        self._emit(
            TurnTiming,
            turn_id=reply.turn_id,
            vad_stop_ns=reply.vad_stop_ns,
            stt_final_ns=reply.stt_final_ns,
            llm_first_token_ns=reply.llm_first_token_ns,
            tts_first_audio_ns=reply.tts_first_audio_ns,
            audio_out_first_ns=reply.audio_out_first_ns,
        )

    def _stop_speech(self) -> None:
        """Drop the reply being spoken, without a word more (mute, a newer reply)."""
        reply, self._reply = self._reply, None
        self._chunker = SentenceChunker()
        if reply is None:
            return
        self._engine.set_speaking(False)
        if reply.task is not None:
            reply.task.cancel()
        if self._tts is not None:
            self._tts.cancel()
        if self._playout is not None:
            self._playout.abort()

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
        if marks := self._marks.get(turn_id):
            marks[1] = time.time_ns()
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
    tts: Mapping[EngineName, TtsEngine] | None = None,
    tts_cfg: TtsConfig | None = None,
    stream_factory: StreamFactory | None = None,
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
    return VoicePipeline(
        cfg,
        hub,
        source,
        wake,
        engine,
        stt,
        source_name,
        local,
        tts,
        tts_cfg,
        stream_factory,
    )
