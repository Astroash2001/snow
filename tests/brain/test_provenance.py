"""CORE-10, D-28: every call and reply records its source; health shows who serves."""

import time

from openai.types.chat import ChatCompletionMessageParam

from snow.brain.config import ModelsConfig
from snow.brain.worker import BrainWorker
from snow.contracts.events import Event, ReplyFinal, TranscriptFinal
from snow.contracts.wire import Snapshot
from tests.brain.conftest import (
    ChainFactory,
    Events,
    Routes,
    error_route,
    host_of,
    sse_route,
)
from tests.conftest import InMemoryKeyring, SnowDirs

MSG: list[ChatCompletionMessageParam] = [{"role": "user", "content": "hi"}]


async def test_failover_is_visible_in_calls_and_health_row(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    error_route(routes, host_of(models_cfg, "groq"), 503)
    sse_route(routes, host_of(models_cfg, "experiential"), ["ok"])
    stream = await chain_factory("fast").stream(MSG)
    _ = [c async for c in stream]
    calls = events.of("llm.call")
    assert [(c.provider, c.model, c.outcome) for c in calls] == [
        ("groq", "groq-1", "error"),
        ("experiential", "exp-1", "ok"),
    ]
    assert all(c.provider and c.model and c.data_class == "private" for c in calls)
    role = events.of("health.role")[-1]
    assert (role.status, role.active_provider, role.active_index) == (
        "fallback",
        "experiential",
        1,
    )
    assert [e.status for e in role.entries][:2] == ["failing", "active"]
    providers = {p.provider: p.status for p in events.of("health.provider")}
    assert providers["groq"] == "failing" and providers["experiential"] == "active"


async def test_primary_serving_reports_active_index_zero(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    sse_route(routes, host_of(models_cfg, "groq"), ["ok"])
    await chain_factory("fast").stream(MSG)
    role = events.of("health.role")[-1]
    assert (role.status, role.active_index) == ("active", 0)


async def test_switch_notice_is_returned_once_for_a_limit_switch(
    models_cfg: ModelsConfig, routes: Routes, chain_factory: ChainFactory
) -> None:
    error_route(routes, host_of(models_cfg, "groq"), 429)
    sse_route(routes, host_of(models_cfg, "experiential"), ["ok"])
    chain = chain_factory("fast")
    await chain.stream(MSG)
    notice = chain.take_switch_notice()
    assert notice is not None and notice.switch_reason == "rate_limit"
    assert chain.take_switch_notice() is None


async def test_non_limit_switch_leaves_no_notice(
    models_cfg: ModelsConfig, routes: Routes, chain_factory: ChainFactory
) -> None:
    error_route(routes, host_of(models_cfg, "groq"), 503)
    sse_route(routes, host_of(models_cfg, "experiential"), ["ok"])
    chain = chain_factory("fast")
    await chain.stream(MSG)
    assert chain.take_switch_notice() is None


async def test_announce_reports_configured_and_unconfigured_roles(
    events: Events, routes: Routes, chain_factory: ChainFactory
) -> None:
    await chain_factory("fast", keys=("groq",)).announce()
    await chain_factory("vision", keys=()).announce()
    fast, vision = events.of("health.role")
    assert (fast.role, fast.status) == ("fast", "not_used_yet")
    assert (vision.role, vision.status) == ("vision", "not_configured")
    assert routes.total == 0


async def test_worker_startup_publishes_all_providers_and_three_roles(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    memory_keyring.set_password("snow", "experiential", "exp_test")
    sse_route(routes, "api.groq.com", ["[[content]] Yes."])  # startup ack-pool refill
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    await BrainWorker(collect, client_factory=routes.client_factory).on_snapshot(
        Snapshot()
    )
    # The first health.role per role is the announce row, before any call (plan 01-16
    # fills the ack pool at startup, so the fast role is used once afterwards).
    first: dict[str, str] = {}
    last: dict[str, str] = {}
    for e in published:
        if e.type == "health.role":
            first.setdefault(e.role, e.status)
            last[e.role] = e.status
    assert first == {
        "brain": "not_used_yet",
        "fast": "not_used_yet",
        "vision": "not_used_yet",
    }
    assert last["fast"] == "active"
    providers: dict[str, str] = {}
    for e in published:
        if e.type == "health.provider":
            providers.setdefault(e.provider, e.status)  # the announce row
    assert set(providers) == {"experiential", "groq", "google", "nvidia", "openrouter"}
    assert providers["groq"] == "ready" and providers["google"] == "not_configured"


async def test_reply_final_carries_the_serving_provider_and_model(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    sse_route(routes, "api.groq.com", ["hello"])
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    await BrainWorker(collect, client_factory=routes.client_factory).on_event(
        TranscriptFinal(ts_ns=time.time_ns(), source="dev", text="hi")
    )
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    assert final.provider == "groq" and final.model == "openai/gpt-oss-120b"
    call = next(e for e in published if e.type == "llm.call")
    assert (call.provider, call.model) == (final.provider, final.model)
