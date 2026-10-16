"""Wake-alone acknowledgements: an LLM-written pool refilled in the background.

"Hey Snow" on its own is answered at once from this pool, so the hot path makes no
network call (D-09, SPCH-01). The pool is generated with `data_class="general"` from a
prompt that carries no user content (T-01-34). When the pool is empty and no model
answers, there is nothing to say and Snow stays silent (D-41).
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from openai.types.chat import ChatCompletionMessageParam

from snow.brain.chain import AllProvidersFailed, LLMChain, MidStreamError
from snow.brain.emotion import split_header
from snow.brain.persona import PersonaConfig

log = logging.getLogger("snow.brain.acks")


@dataclass(frozen=True)
class Ack:
    text: str
    emotion: str
    provider: str
    model: str


class AckPool:
    def __init__(
        self,
        chain_factory: Callable[[], Awaitable[LLMChain]],
        persona: Callable[[], PersonaConfig],
    ) -> None:
        self._chain_factory = chain_factory
        self._persona = persona
        self._acks: deque[Ack] = deque()
        self._task: asyncio.Task[None] | None = None

    def __len__(self) -> int:
        return len(self._acks)

    def pop(self) -> Ack | None:
        """The oldest ready line; refills in the background when the pool runs low."""
        ack = self._acks.popleft() if self._acks else None
        try:
            if len(self._acks) < self._persona().ack_pool_min:
                self.ensure_refill()
        except (OSError, ValueError):
            pass  # config trouble is logged by refill; popping must never raise
        return ack

    def ensure_refill(self) -> asyncio.Task[None] | None:
        """Start one background refill unless one is running (never awaited hot)."""
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.ensure_future(self.refill())
        return self._task

    async def get(self, deadline_s: float) -> Ack | None:
        """A line now if the pool has one, else wait up to the deadline for a refill."""
        if ack := self.pop():
            return ack
        task = self.ensure_refill()
        if task:
            await asyncio.wait({task}, timeout=deadline_s)  # the refill keeps running
        return self.pop()

    async def refill(self) -> None:
        """One fast-chain call that tops the pool up to `ack_pool_size`."""
        try:
            persona = self._persona()
            chain = await self._chain_factory()
        except (OSError, ValueError) as e:
            log.error("config_error kind=%s", type(e).__name__)
            return
        want = persona.ack_pool_size - len(self._acks)
        if want <= 0:
            return
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": persona.system_prompt},
            {"role": "user", "content": persona.ack_prompt.replace("{n}", str(want))},
        ]
        try:
            stream = await chain.stream(
                messages, data_class="general", max_tokens=persona.max_reply_tokens
            )
        except AllProvidersFailed:
            return  # llm.exhausted already told the HUD
        text = ""
        try:
            async for chunk in stream:
                text += chunk
        except MidStreamError:
            log.error("ack_refill_midstream provider=%s", stream.provider)
        seen = {a.text for a in self._acks}
        for line in text.splitlines():
            emotion, _big, found, spoken = split_header(
                line, persona.allowed_emotions, persona.fallback_emotion
            )
            spoken = spoken.strip()
            # A line without a header is model chatter, not an acknowledgement.
            if not found or not spoken or spoken in seen:
                continue
            seen.add(spoken)
            self._acks.append(Ack(spoken, emotion, stream.provider, stream.model))
            if len(self._acks) >= persona.ack_pool_size:
                break
