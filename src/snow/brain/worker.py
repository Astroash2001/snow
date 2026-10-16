"""Brain worker: answers each transcript.final through the `fast` role's LLM chain.

Providers, base URLs, models and fallback order come only from config/models.toml
(CORE-04). Keys are read from Credential Manager by the chain at call time (SAFE-09).
Conversation turns are personal data, so every call is `data_class="private"` and the
chain never lets them reach an untrusted provider (SAFE-12, D-41). Every spoken word is
written by the model (SPCH-01): replies come from the persona prompt, the wake-alone
acknowledgement from a pre-generated pool, and when neither is possible Snow is silent.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TypedDict

from openai import AsyncOpenAI

from snow.brain.acks import AckPool
from snow.brain.chain import (
    AllProvidersFailed,
    ClientFactory,
    LLMChain,
    MidStreamError,
    PrivacyBlockedError,
    ProviderBoard,
    Trace,
)
from snow.brain.config import ModelsConfig
from snow.brain.emotion import HeaderParser
from snow.brain.limits import RateLimiter
from snow.brain.persona import (
    Fact,
    History,
    PersonaConfig,
    apply_overrides,
    build_messages,
)
from snow.config.secrets import get_secret
from snow.config.settings import load_config
from snow.contracts.events import (
    AckRequested,
    Event,
    LlmRole,
    LlmSwitch,
    ReplyDelta,
    ReplyFinal,
    SttStatus,
    TranscriptFinal,
    TurnCancelled,
    VoiceSwitch,
)
from snow.contracts.wire import Snapshot

log = logging.getLogger("snow.brain")

Publish = Callable[[Event], Awaitable[None]]
ROLES: tuple[LlmRole, ...] = ("brain", "fast", "vision")
ACK_DEADLINE_S = 1.5  # direct generation when the pool is empty (D-09)
_LIMIT_WORDS = {"rate_limit": "a rate limit", "out_of_quota": "an exhausted quota"}


class _Ids(TypedDict):
    correlation_id: str | None
    turn_id: str | None
    causation_id: int | None


def _default_factory(**kwargs: object) -> AsyncOpenAI:
    # Looked up at call time so tests can swap `snow.brain.worker.AsyncOpenAI`.
    return AsyncOpenAI(**kwargs)  # pyright: ignore[reportArgumentType]


def _load_persona() -> PersonaConfig:
    return load_config("persona.toml", PersonaConfig)


class BrainWorker:
    def __init__(
        self, publish: Publish, *, client_factory: ClientFactory = _default_factory
    ) -> None:
        self._publish = publish
        self._client_factory = client_factory
        self._models: ModelsConfig | None = None
        self._chains: dict[LlmRole, LLMChain] = {}
        self._limiter = (
            RateLimiter()
        )  # one per brain process: counters are per provider (D-27)
        self._history = History()
        self._facts: list[Fact] = []  # said once in the next reply, then cleared
        self._turns: dict[str, asyncio.Task[object] | None] = {}
        self._stt_degraded = False
        self.acks = AckPool(self._fast_chain, _load_persona)

    async def _chain(self, models: ModelsConfig, role: LlmRole) -> LLMChain:
        # Config is re-read every turn; chains are rebuilt only when it changed.
        if models != self._models:
            for old in self._chains.values():
                await old.aclose()
            board: ProviderBoard = {}
            self._limiter.defaults = models.limits
            self._chains = {
                r: LLMChain(
                    models,
                    r,
                    get_secret=get_secret,
                    emit=self._publish,
                    client_factory=self._client_factory,
                    board=board,
                    limiter=self._limiter,
                )
                for r in ROLES
            }
            self._models = models
        return self._chains[role]

    async def _fast_chain(self) -> LLMChain:
        return await self._chain(load_config("models.toml", ModelsConfig), "fast")

    async def on_snapshot(self, snapshot: Snapshot) -> None:
        """(Re)connected: health rows (D-28), restore history, fill the acks."""
        try:
            models = load_config("models.toml", ModelsConfig)
        except (OSError, ValueError) as e:
            log.error("config_error kind=%s", type(e).__name__)
            return
        for role in ROLES:
            await (await self._chain(models, role)).announce(force=True)
        if not len(self._history):
            self._history.seed(snapshot.rows)
        if task := self.acks.ensure_refill():
            await task  # this handler runs in its own task, so waiting blocks nothing

    async def on_event(self, event: Event) -> None:
        match event:
            case TranscriptFinal():
                await self._run_turn(event)
            case AckRequested():
                await self._ack(event)
            case TurnCancelled():
                self._cancel(event)
            case VoiceSwitch():
                self._facts.append(
                    Fact(
                        f"Snow's voice engine just changed from {event.from_engine} to "
                        f"{event.to_engine} ({event.switch_reason})."
                    )
                )
            case SttStatus():
                self._note_stt(event)
            case _:
                pass

    # --- one-time context facts (D-17, D-28) ---------------------------------

    def _note_stt(self, event: SttStatus) -> None:
        if event.status_reason == "primary":
            self._stt_degraded = False
        elif not self._stt_degraded:  # once per fallback episode
            self._stt_degraded = True
            self._facts.append(
                Fact(
                    f"Speech recognition fell back to {event.stt_source} "
                    f"({event.status_reason})."
                )
            )

    def _note_switch(self, notice: LlmSwitch) -> None:
        why = _LIMIT_WORDS.get(notice.switch_reason, notice.switch_reason)
        self._facts.append(
            Fact(
                f"The language model provider was just switched from "
                f"{notice.from_provider} to {notice.to_provider} because of {why}."
            )
        )

    # --- wake-alone acknowledgement (D-09, D-41) ------------------------------

    async def _ack(self, req: AckRequested) -> None:
        ack = await self.acks.get(ACK_DEADLINE_S)
        ids = _Ids(
            correlation_id=req.correlation_id,
            turn_id=req.turn_id,
            causation_id=req.seq,
        )
        if ack is None:
            # Nothing to say and no model to ask: stay silent, no literal, no earcon.
            await self._publish(
                ReplyFinal(
                    ts_ns=time.time_ns(),
                    source="brain",
                    emotion="neutral",
                    big_moment=False,
                    reply_source="fallback",
                    provider=None,
                    model=None,
                    **ids,
                )
            )
            return
        await self._publish(
            ReplyDelta(ts_ns=time.time_ns(), source="brain", text=ack.text, **ids)
        )
        await self._publish(
            ReplyFinal(
                ts_ns=time.time_ns(),
                source="brain",
                text=ack.text,
                emotion=ack.emotion,
                big_moment=False,
                reply_source="ack_pool",
                provider=ack.provider,
                model=ack.model,
                **ids,
            )
        )

    # --- conversation turns ----------------------------------------------------

    def _cancel(self, event: TurnCancelled) -> None:
        """turn.cancelled: stop the active turn's stream; no reply.final follows."""
        task = self._turns.get(event.turn_id or "")
        if task and task is not asyncio.current_task():
            task.cancel()

    async def _run_turn(self, heard: TranscriptFinal) -> None:
        key = heard.turn_id
        if key:
            self._turns[key] = asyncio.current_task()
        try:
            await self._answer(heard)
        finally:
            if key:
                self._turns.pop(key, None)

    async def _answer(self, heard: TranscriptFinal) -> None:
        try:
            models = load_config("models.toml", ModelsConfig)
            persona = _load_persona()
        except (OSError, ValueError) as e:
            log.error("config_error kind=%s", type(e).__name__)
            return
        chain = await self._chain(models, "fast")
        if notice := chain.take_switch_notice():
            self._note_switch(notice)
        facts, self._facts = self._facts, []
        cid, tid, cause = heard.correlation_id, heard.turn_id, heard.seq
        try:
            stream = await chain.stream(
                build_messages(persona, self._history, heard.text, heard.tone, facts),
                data_class="private",
                max_tokens=persona.max_reply_tokens,
                trace=Trace(cid, tid, cause),
            )
        except (AllProvidersFailed, PrivacyBlockedError):
            # No reply: llm.exhausted / llm.blocked_privacy tell the HUD why.
            self._facts = facts + self._facts
            return
        parser = HeaderParser(persona.allowed_emotions, persona.fallback_emotion)
        chunks = aiter(stream)
        text = ""

        async def say(piece: str) -> None:
            nonlocal text
            if not piece:
                return
            text += piece
            await self._publish(
                ReplyDelta(
                    ts_ns=time.time_ns(),
                    source="brain",
                    correlation_id=cid,
                    turn_id=tid,
                    causation_id=cause,
                    text=piece,
                )
            )

        try:
            try:
                async for raw in chunks:
                    await say(parser.feed(raw))
            except MidStreamError:
                log.error("llm_midstream_error provider=%s", stream.provider)
            await say(parser.flush())
        finally:
            # Closing the stream lets the chain record llm.call "cancelled".
            if isinstance(chunks, AsyncGenerator):
                await chunks.aclose()
        self._history.add(heard.text, text)
        await self._publish(
            ReplyFinal(
                ts_ns=time.time_ns(),
                source="brain",
                text=text,
                emotion=apply_overrides(persona, parser.emotion, heard.tone, facts),
                big_moment=parser.big,
                reply_source="llm",
                provider=stream.provider,
                model=stream.model,
                correlation_id=cid,
                turn_id=tid,
                causation_id=cause,
            )
        )
