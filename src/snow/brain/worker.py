"""Brain worker: answers each transcript.final through the `fast` role's LLM chain.

Providers, base URLs, models and fallback order come only from config/models.toml
(CORE-04). Keys are read from Credential Manager by the chain at call time (SAFE-09).
Conversation turns are personal data, so every call is `data_class="private"` and the
chain never lets them reach an untrusted provider (SAFE-12, D-41).
"""

import logging
import time
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from snow.brain.chain import (
    AllProvidersFailed,
    ClientFactory,
    LLMChain,
    MidStreamError,
    PrivacyBlockedError,
    ProviderBoard,
    Trace,
)
from snow.brain.config import ModelsConfig, PersonaConfig
from snow.config.secrets import get_secret
from snow.config.settings import load_config
from snow.contracts.events import (
    Event,
    LlmRole,
    ReplyDelta,
    ReplyFinal,
    TranscriptFinal,
)
from snow.contracts.wire import Snapshot

log = logging.getLogger("snow.brain")

Publish = Callable[[Event], Awaitable[None]]
ROLES: tuple[LlmRole, ...] = ("brain", "fast", "vision")


def _default_factory(**kwargs: object) -> AsyncOpenAI:
    # Looked up at call time so tests can swap `snow.brain.worker.AsyncOpenAI`.
    return AsyncOpenAI(**kwargs)  # pyright: ignore[reportArgumentType]


class BrainWorker:
    def __init__(
        self, publish: Publish, *, client_factory: ClientFactory = _default_factory
    ) -> None:
        self._publish = publish
        self._client_factory = client_factory
        self._models: ModelsConfig | None = None
        self._chains: dict[LlmRole, LLMChain] = {}

    async def _chain(self, models: ModelsConfig, role: LlmRole) -> LLMChain:
        # Config is re-read every turn; chains are rebuilt only when it changed.
        if models != self._models:
            for old in self._chains.values():
                await old.aclose()
            board: ProviderBoard = {}
            self._chains = {
                r: LLMChain(
                    models,
                    r,
                    get_secret=get_secret,
                    emit=self._publish,
                    client_factory=self._client_factory,
                    board=board,
                )
                for r in ROLES
            }
            self._models = models
        return self._chains[role]

    async def on_snapshot(self, _snapshot: Snapshot) -> None:
        """(Re)connected to a hub: publish provider and role health rows (D-28)."""
        try:
            models = load_config("models.toml", ModelsConfig)
        except (OSError, ValueError) as e:
            log.error("config_error kind=%s", type(e).__name__)
            return
        for role in ROLES:
            await (await self._chain(models, role)).announce(force=True)

    async def on_event(self, event: Event) -> None:
        if isinstance(event, TranscriptFinal):
            await self._answer(event)

    async def _answer(self, heard: TranscriptFinal) -> None:
        try:
            models = load_config("models.toml", ModelsConfig)
            persona = load_config("persona.toml", PersonaConfig)
        except (OSError, ValueError) as e:
            log.error("config_error kind=%s", type(e).__name__)
            return
        chain = await self._chain(models, "fast")
        cid, tid, cause = heard.correlation_id, heard.turn_id, heard.seq
        try:
            stream = await chain.stream(
                [
                    {"role": "system", "content": persona.system_prompt},
                    {"role": "user", "content": heard.text},
                ],
                data_class="private",
                trace=Trace(cid, tid, cause),
            )
        except (AllProvidersFailed, PrivacyBlockedError):
            # No reply: llm.exhausted / llm.blocked_privacy tell the HUD why.
            return
        text = ""
        try:
            async for delta in stream:
                text += delta
                await self._publish(
                    ReplyDelta(
                        ts_ns=time.time_ns(),
                        source="brain",
                        correlation_id=cid,
                        turn_id=tid,
                        causation_id=cause,
                        text=delta,
                    )
                )
        except MidStreamError:
            log.error("llm_midstream_error provider=%s", stream.provider)
        await self._publish(
            ReplyFinal(
                ts_ns=time.time_ns(),
                source="brain",
                text=text,
                emotion="neutral",
                big_moment=False,
                reply_source="llm",
                provider=stream.provider,
                model=stream.model,
                correlation_id=cid,
                turn_id=tid,
                causation_id=cause,
            )
        )
