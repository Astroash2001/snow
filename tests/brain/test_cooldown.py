"""CORE-09 / D-27: cooldowns follow each provider's limit signals; daily counters."""

import copy
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

import httpx2
import pytest
from openai.types.chat import ChatCompletionMessageParam

from snow.brain.chain import AllProvidersFailed, ChainStream, LLMChain
from snow.brain.config import ChainEntry, ModelsConfig
from snow.brain.limits import CooldownDefaults, RateLimiter, parse_duration
from snow.brain.worker import BrainWorker
from snow.config.secrets import Secret
from snow.contracts.events import LlmRole
from tests.brain.conftest import (
    ALL_KEYS,
    MODELS,
    Events,
    FakeClock,
    Routes,
    hang_route,
    host_of,
    sse_route,
)
from tests.conftest import openai_sse

MSG: list[ChatCompletionMessageParam] = [{"role": "user", "content": "hi"}]
START = datetime(2026, 10, 16, 10, 0, 0)
ENTRY = ChainEntry(provider="groq", model="m")


class Clock:
    def __init__(self) -> None:
        self.t = START

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def limiter(clock: Clock) -> RateLimiter:
    return RateLimiter(clock, CooldownDefaults())


def two_groq() -> ModelsConfig:
    """Fast chain with two groq models, as in the shipped models.toml."""
    cfg = copy.deepcopy(MODELS)
    cfg["roles"]["fast"]["chain"].insert(1, {"provider": "groq", "model": "groq-2"})
    return ModelsConfig.model_validate(cfg)


def cooldown_s(
    limiter: RateLimiter,
    clock: Clock,
    reason: str,
    headers: Mapping[str, str] | None = None,
    body: object = None,
) -> float | None:
    until = limiter.record_failure("p", ENTRY, reason, headers or {}, body)
    return None if until is None else (until - clock.t).total_seconds()


# --- parse_duration ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("2m59.56s", 179.56),
        ("7.66s", 7.66),
        ("250ms", 0.25),
        ("1h2m3.5s", 3723.5),
    ],
)
def test_parse_duration(text: str, seconds: float) -> None:
    assert parse_duration(text) == pytest.approx(seconds)


@pytest.mark.parametrize("text", ["garbage", "", "5", "1x"])
def test_parse_duration_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


# --- per-provider limit signals (policy) -------------------------------------


def test_groq_retry_after_seconds(limiter: RateLimiter, clock: Clock) -> None:
    assert cooldown_s(limiter, clock, "rate_limit", {"retry-after": "12"}) == 12


def test_groq_reset_requests_when_that_window_is_empty(
    limiter: RateLimiter, clock: Clock
) -> None:
    headers = {
        "x-ratelimit-reset-requests": "2m59.56s",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-tokens": "7.66s",
        "x-ratelimit-remaining-tokens": "4000",
    }
    assert cooldown_s(limiter, clock, "rate_limit", headers) == pytest.approx(179.56)


def test_openrouter_reset_is_an_epoch_millisecond_instant(
    limiter: RateLimiter, clock: Clock
) -> None:
    reset = int((clock.t + timedelta(seconds=45)).timestamp() * 1000)
    headers = {"X-RateLimit-Reset": str(reset)}
    assert cooldown_s(limiter, clock, "rate_limit", headers) == pytest.approx(45)


def test_google_retry_delay_in_body(limiter: RateLimiter, clock: Clock) -> None:
    body = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "x.RetryInfo", "retryDelay": "13s"}],
        }
    }
    assert cooldown_s(limiter, clock, "rate_limit", body=body) == 13
    # openai may hand over the body as a one-element list
    assert cooldown_s(limiter, clock, "rate_limit", body=[body]) == 13


def test_experiential_codes(limiter: RateLimiter, clock: Clock) -> None:
    def err(code: str) -> dict[str, Any]:
        return {"error": {"code": code}}

    until_midnight = (datetime(2026, 10, 17) - clock.t).total_seconds()
    assert cooldown_s(limiter, clock, "out_of_quota", body=err("key_daily_cap")) == (
        until_midnight
    )
    assert (
        cooldown_s(limiter, clock, "out_of_quota", body=err("insufficient_credits"))
        == 1800
    )
    assert (
        cooldown_s(limiter, clock, "rate_limit", body=err("gateway_overloaded")) == 15
    )


def test_unknown_signals_use_defaults(limiter: RateLimiter, clock: Clock) -> None:
    assert cooldown_s(limiter, clock, "rate_limit") == 60
    assert cooldown_s(limiter, clock, "service_error") == 20
    assert cooldown_s(limiter, clock, "timeout") == 20
    assert cooldown_s(limiter, clock, "unreachable") == 20
    # Garbage hints fall back instead of raising.
    assert cooldown_s(limiter, clock, "rate_limit", {"retry-after": "soon"}) == 60


def test_config_error_is_not_a_provider_wide_cooldown(
    limiter: RateLimiter,
) -> None:
    assert limiter.record_failure("p", ENTRY, "config_error", {}, None) is None
    assert limiter.cooling_until("p", ENTRY) is None


def test_cooldown_ends_exactly_when_asked(limiter: RateLimiter, clock: Clock) -> None:
    limiter.record_failure("groq", ENTRY, "rate_limit", {"retry-after": "12"}, None)
    assert limiter.cooling_until("groq", ENTRY) is not None
    clock.advance(11.9)
    assert limiter.cooling_until("groq", ENTRY) is not None
    clock.advance(0.2)
    assert limiter.cooling_until("groq", ENTRY) is None


def test_defaults_are_configurable_from_models_toml() -> None:
    cfg = copy.deepcopy(MODELS)
    cfg["limits"] = {"rate_limit_s": 5, "transient_s": 2}
    models = ModelsConfig.model_validate(cfg)
    assert models.limits.rate_limit_s == 5
    assert models.limits.out_of_quota_s == 1800  # untouched keys keep defaults


# --- counters ----------------------------------------------------------------


def test_counters_use_usage_else_estimate_and_reset_at_midnight(
    limiter: RateLimiter, clock: Clock
) -> None:
    limiter.record_success("groq", ENTRY, 120, 999)
    limiter.record_success("groq", ENTRY, None, 41)  # 41 // 4 = 10
    assert limiter.snapshot("groq")[:2] == (2, 130)
    assert limiter.snapshot("nvidia")[:2] == (0, 0)
    clock.t = datetime(2026, 10, 17, 0, 0, 1)
    assert limiter.snapshot("groq")[:2] == (0, 0)


def test_daily_request_cap_cools_until_local_midnight(
    limiter: RateLimiter, clock: Clock
) -> None:
    capped = ChainEntry(provider="groq", model="m", daily_request_cap=2)
    limiter.record_success("groq", capped, 1, 0)
    assert limiter.cooling_until("groq", capped) is None
    limiter.record_success("groq", capped, 1, 0)
    assert limiter.cooling_until("groq", capped) == datetime(2026, 10, 17)
    assert limiter.cooling_until("groq", ENTRY) is None  # no cap on this entry
    clock.t = datetime(2026, 10, 17, 0, 0, 1)
    assert limiter.cooling_until("groq", capped) is None


# --- through the chain -------------------------------------------------------


def limited(
    status: int, headers: Mapping[str, str], body: object | None = None
) -> httpx2.Response:
    return httpx2.Response(
        status, headers=dict(headers), json=body or {"error": {"message": "x"}}
    )


def sse_with_usage(text: str, prompt: int, completion: int) -> httpx2.Response:
    """A streamed reply whose last chunk before [DONE] carries the usage totals."""
    raw = openai_sse([text]).content.decode()
    usage = {
        "id": "u",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "test",
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }
    raw = raw.replace("data: [DONE]", f"data: {json.dumps(usage)}\n\ndata: [DONE]")
    return httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=raw.encode()
    )


@pytest.fixture
def make(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    fake_clock: FakeClock,
    limiter: RateLimiter,
) -> Callable[..., LLMChain]:
    def build(role: LlmRole, models: ModelsConfig | None = None) -> LLMChain:
        return LLMChain(
            models or models_cfg,
            role,
            get_secret=lambda n: Secret(f"fake-{n}") if n in ALL_KEYS else None,
            emit=events.emit,
            now=fake_clock,
            client_factory=routes.client_factory,
            limiter=limiter,
        )

    return build


async def text_of(stream: ChainStream) -> str:
    return "".join([c async for c in stream])


async def test_cooling_provider_is_skipped_then_returns(
    make: Callable[..., LLMChain],
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    clock: Clock,
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")
    chain = make("fast")
    routes.add(groq, limited(429, {"retry-after": "12"}))
    sse_route(routes, exp, ["one"])
    assert (await chain.stream(MSG)).provider == "experiential"
    # Still cooling: groq is not even asked (its queue is empty, so a call would
    # be an unrouted violation).
    sse_route(routes, exp, ["two"])
    second = await chain.stream(MSG)
    assert second.provider == "experiential"
    await text_of(second)
    assert routes.count(groq) == 1
    # After the cooldown groq is eligible again.
    clock.advance(12.1)
    sse_route(routes, groq, ["back"])
    third = await chain.stream(MSG)
    assert (third.provider, await text_of(third)) == ("groq", "back")
    # groq was asked twice in all: the 429, then the reply after the cooldown.
    assert routes.count(groq) == 2
    rows = [e for e in events.of("health.provider") if e.provider == "groq"]
    assert any(r.status == "cooling_down" and r.cooling_until_ns for r in rows)
    assert rows[-1].status != "cooling_down"


async def test_timeout_cools_only_that_model(
    make: Callable[..., LLMChain],
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    clock: Clock,
) -> None:
    """G-01-16: a slow model must not silence the provider's other models."""
    groq = host_of(models_cfg, "groq")
    chain = make("fast", two_groq())
    hang_route(routes, groq)
    sse_route(routes, groq, ["via qwen"])
    first = await chain.stream(MSG)
    assert (first.provider, first.model) == ("groq", "groq-2")
    assert await text_of(first) == "via qwen"
    assert routes.count(groq) == 2
    role = events.of("health.role")[-1]
    assert role.status == "fallback"
    assert role.entries[0].status == "cooling_down"
    assert role.entries[0].cooling_until_ns
    assert role.entries[0].detail == "timeout"
    assert role.entries[1].status == "active"
    rows = [e for e in events.of("health.provider") if e.provider == "groq"]
    assert not any(r.status == "cooling_down" for r in rows)
    # Next turn: groq-1 is still cooling, so groq-2 serves without a hung call.
    sse_route(routes, groq, ["again"])
    second = await chain.stream(MSG)
    assert second.model == "groq-2"
    await text_of(second)
    # After the cooldown groq-1 is tried again.
    clock.advance(20.1)
    sse_route(routes, groq, ["back"])
    assert (await chain.stream(MSG)).model == "groq-1"


@pytest.mark.parametrize(
    ("reason", "provider_wide"),
    [
        ("timeout", False),
        ("service_error", False),
        ("rate_limit", True),
        ("out_of_quota", True),
        ("bad_key", True),
        ("unreachable", True),
    ],
)
def test_cooldown_scope(limiter: RateLimiter, reason: str, provider_wide: bool) -> None:
    other = ChainEntry(provider="groq", model="other")
    limiter.record_failure("groq", ENTRY, reason, {}, None)
    assert limiter.cooling_until("groq", ENTRY) is not None
    assert (limiter.cooling_until("groq", other) is not None) is provider_wide
    assert (limiter.snapshot("groq")[2] is not None) is provider_wide


async def test_rate_limit_still_cools_the_whole_provider(
    make: Callable[..., LLMChain],
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")
    routes.add(groq, limited(429, {"retry-after": "12"}))
    sse_route(routes, exp, ["ok"])
    stream = await make("fast", two_groq()).stream(MSG)
    assert stream.provider == "experiential"
    assert routes.count(groq) == 1
    role = events.of("health.role")[-1]
    assert [e.status for e in role.entries[:2]] == ["cooling_down", "cooling_down"]
    assert all(e.cooling_until_ns for e in role.entries[:2])
    rows = [e for e in events.of("health.provider") if e.provider == "groq"]
    assert any(r.status == "cooling_down" and r.cooling_until_ns for r in rows)


async def test_bad_key_costs_one_call_not_two(
    make: Callable[..., LLMChain], models_cfg: ModelsConfig, routes: Routes
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")
    routes.add(groq, limited(401, {}))
    sse_route(routes, exp, ["ok"])
    stream = await make("fast", two_groq()).stream(MSG)
    assert stream.provider == "experiential"
    assert routes.count(groq) == 1


async def test_cooling_trusted_provider_never_promotes_untrusted(
    make: Callable[..., LLMChain],
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
) -> None:
    exp, nim = host_of(models_cfg, "experiential"), host_of(models_cfg, "nvidia")
    chain = make("brain")  # experiential, google (untrusted), nvidia, openrouter
    routes.add(exp, limited(429, {"retry-after": "30"}))
    sse_route(routes, nim, ["via nim"])
    stream = await chain.stream(MSG)  # private by default
    assert stream.provider == "nvidia"
    assert await text_of(stream) == "via nim"
    # Next private call: exp still cooling, google skipped by privacy, nim again.
    sse_route(routes, nim, ["again"])
    assert (await chain.stream(MSG)).provider == "nvidia"
    assert routes.count(host_of(models_cfg, "google")) == 0
    assert events.of("llm.blocked_privacy") == []


@pytest.mark.parametrize("reason", ["rate_limit", "timeout"])
async def test_only_untrusted_left_fails_closed_while_cooling(
    make: Callable[..., LLMChain],
    models_cfg: ModelsConfig,
    routes: Routes,
    limiter: RateLimiter,
    reason: str,
) -> None:
    from snow.brain.chain import PrivacyBlockedError

    for entry in (
        ChainEntry(provider="experiential", model="luna"),
        ChainEntry(provider="nvidia", model="nim-1"),
    ):
        limiter.record_failure(
            entry.provider, entry, reason, {"retry-after": "60"}, None
        )
    with pytest.raises(PrivacyBlockedError):
        await make("brain").stream(MSG)
    assert routes.total == 0


async def test_all_cooling_is_exhausted_not_hammered(
    make: Callable[..., LLMChain], routes: Routes, events: Events, limiter: RateLimiter
) -> None:
    for p in ("experiential", "groq", "google", "nvidia", "openrouter"):
        limiter.record_failure(p, ENTRY, "rate_limit", {"retry-after": "60"}, None)
    with pytest.raises(AllProvidersFailed):
        await make("fast").stream(MSG, data_class="general")
    assert routes.total == 0
    [row] = events.of("health.role")
    assert row.status == "cooling_down"
    assert all(e.status == "cooling_down" and e.cooling_until_ns for e in row.entries)


async def test_counters_reach_health_rows_and_are_shared_across_roles(
    make: Callable[..., LLMChain],
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    clock: Clock,
) -> None:
    exp = host_of(models_cfg, "experiential")
    routes.add(exp, sse_with_usage("hello", 100, 25))
    routes.add(exp, openai_sse(["abcdefgh" * 2]))  # no usage chunk: 16 // 4 = 4
    await text_of(await make("brain").stream(MSG))
    await text_of(await make("vision").stream(MSG))
    last = [e for e in events.of("health.provider") if e.provider == "experiential"][-1]
    assert (last.requests_today, last.tokens_today) == (2, 129)
    clock.t = datetime(2026, 10, 17, 0, 0, 1)
    routes.add(exp, sse_with_usage("hi", 1, 1))
    await text_of(await make("brain").stream(MSG))
    last = [e for e in events.of("health.provider") if e.provider == "experiential"][-1]
    assert (last.requests_today, last.tokens_today) == (1, 2)


async def test_daily_cap_skips_entry_until_midnight(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    fake_clock: FakeClock,
    limiter: RateLimiter,
    clock: Clock,
) -> None:
    cfg = copy.deepcopy(MODELS)
    cfg["roles"]["fast"]["chain"][0]["daily_request_cap"] = 1  # groq
    models = ModelsConfig.model_validate(cfg)
    groq, exp = host_of(models, "groq"), host_of(models, "experiential")
    chain = LLMChain(
        models,
        "fast",
        get_secret=lambda n: Secret("k") if n in ALL_KEYS else None,
        emit=events.emit,
        now=fake_clock,
        client_factory=routes.client_factory,
        limiter=limiter,
    )
    sse_route(routes, groq, ["first"])
    first = await chain.stream(MSG)
    await text_of(first)
    sse_route(routes, exp, ["second"])
    assert (await chain.stream(MSG)).provider == "experiential"  # cap reached
    clock.t = datetime(2026, 10, 17, 0, 0, 1)
    sse_route(routes, groq, ["next day"])
    assert (await chain.stream(MSG)).provider == "groq"
    await chain.aclose()


async def test_worker_shares_one_limiter_across_roles(models_cfg: ModelsConfig) -> None:
    worker = BrainWorker(Events().emit)
    chains = [await worker._chain(models_cfg, r) for r in ("brain", "fast", "vision")]  # pyright: ignore[reportPrivateUsage]
    limiters = {id(c._limiter) for c in chains}  # pyright: ignore[reportPrivateUsage]
    assert len(limiters) == 1 and chains[0]._limiter is not None  # pyright: ignore[reportPrivateUsage]
