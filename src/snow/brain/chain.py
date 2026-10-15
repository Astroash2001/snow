"""Config-driven LLM fallback chain per role (CORE-04, CORE-08, CORE-10, SAFE-12).

A role is an ordered list of (provider, model) entries from models.toml.
`LLMChain.stream` tries them in order and fails over only BEFORE the first token;
after the first token an error ends the turn (`MidStreamError`) so the user never
hears two contradictory replies. Every attempt leaves a durable `llm.call` event and
health rows tell the HUD who is serving. Error bodies are never logged or emitted,
only the failure kind (T-01-20).
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AsyncStream,
    OpenAIError,
)
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

from snow.brain.config import ChainEntry, ModelsConfig, Provider, Role
from snow.brain.limits import RateLimiter
from snow.config.secrets import Secret
from snow.contracts.events import (
    ChainEntryStatus,
    Event,
    HealthProvider,
    HealthRole,
    LlmBlockedPrivacy,
    LlmCall,
    LlmExhausted,
    LlmRole,
    LlmSwitch,
    ProviderStatus,
)

log = logging.getLogger("snow.brain.chain")

DataClass = Literal["general", "private"]
SwitchReason = Literal[
    "rate_limit",
    "out_of_quota",
    "service_error",
    "timeout",
    "unreachable",
    "bad_key",
    "config_error",
]

Emit = Callable[[Event], Awaitable[None]]
ClientFactory = Callable[..., AsyncOpenAI]
SecretLookup = Callable[[str], Secret | None]
# Shared across the three role chains: a provider serves several roles.
ProviderBoard = dict[str, tuple[ProviderStatus, str | None]]

_QUOTA_CODES = frozenset(
    {
        "insufficient_quota",
        "key_daily_cap",
        "insufficient_credits",
        "free_limit_reached",
    }
)
_LIMIT_REASONS = frozenset({"rate_limit", "out_of_quota"})


def _ns(when: datetime) -> int:
    return int(when.timestamp() * 1_000_000_000)


class AllProvidersFailed(Exception):
    """Every chain entry was keyless, unresolved or failed before the first token."""

    def __init__(self, role: LlmRole) -> None:
        super().__init__(f"no provider could serve role {role!r}")
        self.role = role


class PrivacyBlockedError(Exception):
    """Only untrusted providers remain for private data; nothing was sent (SAFE-12)."""

    def __init__(self, role: LlmRole, data_class: DataClass) -> None:
        super().__init__(f"role {role!r}: {data_class} data, only untrusted left")
        self.role = role
        self.data_class = data_class


class MidStreamError(Exception):
    """The provider failed after the first token; no failover (no duplicated reply)."""


def _error_code(exc: APIStatusError) -> str | None:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body = exc.body
    if isinstance(body, dict):
        inner = body.get("error", body)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(inner, dict):
            value = inner.get("code")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            return value if isinstance(value, str) else None
    return None


def classify(exc: BaseException) -> SwitchReason:
    """Map a pre-first-token failure to the reason carried by `llm.switch`."""
    if isinstance(exc, TimeoutError | APITimeoutError):
        return "timeout"
    if isinstance(exc, APIConnectionError):
        return "unreachable"
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status == 429:
            return "out_of_quota" if _error_code(exc) in _QUOTA_CODES else "rate_limit"
        if status in (401, 403):
            return "bad_key"
        if status in (400, 404, 422):
            return "config_error"
    return "service_error"


class _EmptyReply(OpenAIError):
    """The stream ended without any text: counts as a provider failure."""


@dataclass
class _Opened:
    stream: AsyncStream[ChatCompletionChunk]
    iterator: AsyncIterator[ChatCompletionChunk]


@dataclass(frozen=True)
class Trace:
    """Links `llm.*` events to the turn that caused them."""

    correlation_id: str | None = None
    turn_id: str | None = None
    causation_id: int | None = None


class ChainStream:
    """Text chunks of one reply plus who is serving it."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        index: int,
        headers: Mapping[str, str],
        chunks: AsyncIterator[str],
    ) -> None:
        self.provider = provider
        self.model = model
        self.index = index
        self.headers = headers  # rate-limit headers for plan 01-12
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[str]:
        return self._chunks


class LLMChain:
    def __init__(
        self,
        models: ModelsConfig,
        role: LlmRole,
        *,
        get_secret: SecretLookup,
        emit: Emit,
        now: Callable[[], float] = time.monotonic,
        client_factory: ClientFactory = AsyncOpenAI,
        board: ProviderBoard | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._models = models
        self._role_name: LlmRole = role
        self._role: Role = models.roles.get(role, Role(chain=[]))
        self._get_secret = get_secret
        self._emit = emit
        self._now = now
        self._client_factory = client_factory
        self._board: ProviderBoard = board if board is not None else {}
        self._limiter = limiter
        self._sent_board: dict[str, tuple[object, ...]] = {}
        self._clients: dict[str, tuple[str, str, AsyncOpenAI]] = {}
        self._switch_notice: LlmSwitch | None = None

    # --- public ------------------------------------------------------------

    async def stream(
        self,
        messages: list[ChatCompletionMessageParam],
        data_class: DataClass = "private",  # fail closed
        max_tokens: int | None = None,
        trace: Trace | None = None,
    ) -> ChainStream:
        trace = trace or Trace()
        failed: dict[int, SwitchReason] = {}
        blocked: set[int] = set()  # skipped by the privacy rule only
        last_failed: tuple[ChainEntry, SwitchReason] | None = None
        for index, entry in enumerate(self._role.chain):
            provider = self._models.providers[entry.provider]
            secret = self._get_secret(provider.key_name)
            if secret is None or not entry.model:
                continue
            if data_class == "private" and provider.trust == "untrusted":
                blocked.add(index)  # SAFE-12: never send private data here
                continue
            if self._limiter and self._limiter.cooling_until(entry.provider, entry):
                continue  # after the privacy check: cooling never promotes untrusted
            started = self._now()
            try:
                opened = await self._open(entry, provider, secret, messages, max_tokens)
            except (OpenAIError, TimeoutError) as e:
                reason = classify(e)
                failed[index] = reason
                last_failed = (entry, reason)
                log.warning(
                    "llm_failed provider=%s kind=%s status=%s",
                    entry.provider,
                    reason,
                    getattr(e, "status_code", None),
                )
                await self._emit_call(
                    entry,
                    data_class,
                    trace,
                    outcome="error",
                    error_kind=reason,
                    total_ms=self._ms(started),
                )
                self._board[entry.provider] = self._record_failure(entry, reason, e)
                continue
            raw_stream, first_text, headers = opened
            ttft_ms = self._ms(started)
            if last_failed is not None:
                await self._announce_switch(last_failed, entry, trace)
            self._board[entry.provider] = ("active", None)
            await self._publish_health(served=index, failed=failed, blocked=blocked)
            chunks = self._drain(
                entry, data_class, trace, raw_stream, first_text, started, ttft_ms
            )
            return ChainStream(
                provider=entry.provider,
                model=entry.model,
                index=index,
                headers=headers,
                chunks=chunks,
            )
        await self._publish_health(served=None, failed=failed, blocked=blocked)
        if blocked:
            await self._emit(
                LlmBlockedPrivacy(
                    ts_ns=time.time_ns(),
                    source="brain",
                    role=self._role_name,
                    data_class=data_class,
                    **trace.__dict__,
                )
            )
            raise PrivacyBlockedError(self._role_name, data_class)
        await self._emit(
            LlmExhausted(
                ts_ns=time.time_ns(),
                source="brain",
                role=self._role_name,
                **trace.__dict__,
            )
        )
        raise AllProvidersFailed(self._role_name)

    def take_switch_notice(self) -> LlmSwitch | None:
        """The last limit-caused switch, once (plan 01-16 voices it)."""
        notice, self._switch_notice = self._switch_notice, None
        return notice

    async def announce(self, *, force: bool = False) -> None:
        """Startup/reconnect health rows: who is configured, nothing used yet."""
        if force:
            self._sent_board.clear()
        for entry in self._role.chain:
            provider = self._models.providers[entry.provider]
            if self._get_secret(provider.key_name) is None:
                self._board[entry.provider] = ("not_configured", "No key stored")
            else:
                self._board.setdefault(entry.provider, ("ready", None))
        await self._publish_health(served=None, failed={}, used=False)

    async def aclose(self) -> None:
        for _, _, client in self._clients.values():
            await client.close()
        self._clients.clear()

    # --- internals ---------------------------------------------------------

    def _ms(self, since: float) -> int:
        return round((self._now() - since) * 1000)

    def _record_failure(
        self, entry: ChainEntry, reason: SwitchReason, exc: BaseException
    ) -> tuple[ProviderStatus, str | None]:
        """Start the provider's cooldown from the error's headers and body (CORE-09)."""
        if self._limiter is None:
            return "failing", reason
        headers: Mapping[str, str] = {}
        body: object = None
        if isinstance(exc, APIStatusError):
            headers, body = exc.response.headers, exc.body
        until = self._limiter.record_failure(entry.provider, reason, headers, body)
        return ("cooling_down" if until else "failing"), reason

    def _client(self, name: str, provider: Provider, secret: Secret) -> AsyncOpenAI:
        cached = self._clients.get(name)
        if cached and cached[:2] == (provider.base_url, secret.reveal()):
            return cached[2]
        client = self._client_factory(
            base_url=provider.base_url,
            api_key=secret.reveal(),
            max_retries=0,  # SDK retries would delay failover (research F6)
            timeout=30,
        )
        self._clients[name] = (provider.base_url, secret.reveal(), client)
        return client

    async def _open(
        self,
        entry: ChainEntry,
        provider: Provider,
        secret: Secret,
        messages: list[ChatCompletionMessageParam],
        max_tokens: int | None,
    ) -> tuple[_Opened, str, Mapping[str, str]]:
        """Connect and wait for the first text, all inside the role's TTFT deadline."""
        body: dict[str, object] = {
            k: v for k, v in entry.params.items() if k not in entry.drop_params
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if "stream_options" not in entry.drop_params:
            body["stream_options"] = {"include_usage": True}
        client = self._client(entry.provider, provider, secret)
        async with asyncio.timeout(self._role.ttft_timeout_s):
            raw = await client.chat.completions.with_raw_response.create(
                model=entry.model, messages=messages, stream=True, extra_body=body
            )
            stream = raw.parse()
            it = stream.__aiter__()
            try:
                while True:
                    try:
                        chunk = await it.__anext__()
                    except StopAsyncIteration:
                        raise _EmptyReply from None
                    text = chunk.choices[0].delta.content if chunk.choices else None
                    if text:
                        return _Opened(stream, it), text, raw.headers
            except BaseException:
                await stream.close()
                raise

    async def _drain(
        self,
        entry: ChainEntry,
        data_class: DataClass,
        trace: Trace,
        opened: _Opened,
        first_text: str,
        started: float,
        ttft_ms: int,
    ) -> AsyncIterator[str]:
        usage_in: int | None = None
        usage_out: int | None = None
        text_len = len(first_text)
        outcome: Literal["ok", "error", "cancelled"] = "cancelled"
        error_kind: str | None = None
        try:
            yield first_text
            async for chunk in opened.iterator:
                if chunk.usage:
                    usage_in = chunk.usage.prompt_tokens
                    usage_out = chunk.usage.completion_tokens
                text = chunk.choices[0].delta.content if chunk.choices else None
                if text:
                    text_len += len(text)
                    yield text
            outcome = "ok"
        except (OpenAIError, TimeoutError) as e:
            outcome, error_kind = "error", classify(e)
            raise MidStreamError(error_kind) from e
        finally:
            await opened.stream.close()
            await self._emit_call(
                entry,
                data_class,
                trace,
                outcome=outcome,
                error_kind=error_kind,
                total_ms=self._ms(started),
                ttft_ms=ttft_ms,
                prompt_tokens=usage_in,
                completion_tokens=usage_out,
            )
            if self._limiter:  # a served request counts even if cut short
                tokens = (
                    usage_in + usage_out
                    if usage_in is not None and usage_out is not None
                    else None
                )
                self._limiter.record_success(entry.provider, entry, tokens, text_len)
                await self._publish_providers()

    async def _emit_call(
        self,
        entry: ChainEntry,
        data_class: DataClass,
        trace: Trace,
        *,
        outcome: Literal["ok", "error", "cancelled"],
        total_ms: int,
        error_kind: str | None = None,
        ttft_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        await self._emit(
            LlmCall(
                ts_ns=time.time_ns(),
                source="brain",
                role=self._role_name,
                provider=entry.provider,
                model=entry.model,
                data_class=data_class,
                ttft_ms=ttft_ms,
                total_ms=total_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                outcome=outcome,
                error_kind=error_kind,
                **trace.__dict__,
            )
        )

    async def _announce_switch(
        self, last_failed: tuple[ChainEntry, SwitchReason], to: ChainEntry, trace: Trace
    ) -> None:
        frm, reason = last_failed
        switch = LlmSwitch(
            ts_ns=time.time_ns(),
            source="brain",
            role=self._role_name,
            from_provider=frm.provider,
            from_model=frm.model,
            to_provider=to.provider,
            to_model=to.model,
            switch_reason=reason,
            **trace.__dict__,
        )
        if reason in _LIMIT_REASONS:
            self._switch_notice = switch
        await self._emit(switch)

    def _cooling(self, entry: ChainEntry) -> datetime | None:
        return (
            self._limiter.cooling_until(entry.provider, entry)
            if self._limiter
            else None
        )

    def _entry_status(
        self,
        index: int,
        entry: ChainEntry,
        served: int | None,
        failed: dict[int, SwitchReason],
        blocked: set[int],
    ) -> ChainEntryStatus:
        provider = self._models.providers[entry.provider]
        status: ProviderStatus = "ready"
        detail: str | None = None
        cooling_ns: int | None = None
        if self._get_secret(provider.key_name) is None:
            status, detail = "not_configured", "No key stored"
        elif not entry.model:
            status = "not_configured"
            detail = "Model ID not resolved; run snow dev probe-models"
        elif index in blocked:
            detail = "Skipped: private data stays off untrusted providers"
        elif index == served:
            status = "active"
        elif until := self._cooling(entry):
            status, cooling_ns, detail = "cooling_down", _ns(until), failed.get(index)
        elif index in failed:
            status, detail = "failing", failed[index]
        return ChainEntryStatus(
            provider=entry.provider,
            provider_label=provider.label,
            model=entry.model,
            status=status,
            cooling_until_ns=cooling_ns,
            detail=detail,
        )

    async def _publish_health(
        self,
        *,
        served: int | None,
        failed: dict[int, SwitchReason],
        blocked: set[int] | None = None,
        used: bool = True,
    ) -> None:
        blocked = blocked or set()
        chain = self._role.chain
        entries = [
            self._entry_status(i, e, served, failed, blocked)
            for i, e in enumerate(chain)
        ]
        status: Literal[
            "active",
            "fallback",
            "cooling_down",
            "failing",
            "not_configured",
            "not_used_yet",
        ]
        if all(e.status == "not_configured" for e in entries):
            status = "not_configured"
        elif served is not None:
            status = "active" if served == 0 else "fallback"
        elif used:
            cooling = any(e.status == "cooling_down" for e in entries)
            failing = any(e.status == "failing" for e in entries)
            status = "cooling_down" if cooling and not failing else "failing"
        else:
            status = "not_used_yet"
        entry = chain[served] if served is not None else None
        await self._emit(
            HealthRole(
                ts_ns=time.time_ns(),
                source="brain",
                role=self._role_name,
                status=status,
                active_provider=entry.provider if entry else None,
                active_model=entry.model if entry else None,
                active_index=served,
                entries=entries,
            )
        )
        await self._publish_providers()

    async def _publish_providers(self) -> None:
        """Provider rows on change: status, cooldown end and today's counters."""
        for name, (pstatus, detail) in self._board.items():
            entry = next((e for e in self._role.chain if e.provider == name), None)
            requests = tokens = 0
            until: datetime | None = None
            if self._limiter and entry:
                requests, tokens, until = self._limiter.snapshot(name)
            if pstatus == "cooling_down" and until is None:
                pstatus = "ready"  # cooldown over; the next call retries it
            elif until is not None:
                pstatus = "cooling_down"
            cooling_ns = _ns(until) if until else None
            row = (pstatus, detail, requests, tokens, cooling_ns)
            if self._sent_board.get(name) == row:
                continue
            self._sent_board[name] = row
            await self._emit(
                HealthProvider(
                    ts_ns=time.time_ns(),
                    source="brain",
                    provider=name,
                    label=self._models.providers[name].label,
                    status=pstatus,
                    cooling_until_ns=cooling_ns,
                    detail=detail,
                    requests_today=requests,
                    tokens_today=tokens,
                )
            )
