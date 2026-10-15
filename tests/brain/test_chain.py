"""CORE-08: the chain moves to the next entry before the first token, never after."""

import json

import httpx2
import pytest
from openai.types.chat import ChatCompletionMessageParam

from snow.brain.chain import (
    AllProvidersFailed,
    ChainStream,
    MidStreamError,
    SwitchReason,
    classify,
)
from snow.brain.config import ModelsConfig
from tests.brain.conftest import (
    ChainFactory,
    Events,
    Routes,
    error_route,
    hang_route,
    host_of,
    midstream_error_route,
    sse_route,
)

MSG: list[ChatCompletionMessageParam] = [{"role": "user", "content": "hi"}]


async def text_of(stream: ChainStream) -> str:
    return "".join([c async for c in stream])


async def test_first_entry_serves_and_call_is_recorded(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    groq = host_of(models_cfg, "groq")
    sse_route(routes, groq, ["Good ", "evening"])
    stream = await chain_factory("fast").stream(MSG)
    assert (stream.provider, stream.model, stream.index) == ("groq", "groq-1", 0)
    assert await text_of(stream) == "Good evening"
    [call] = events.of("llm.call")
    assert (call.outcome, call.provider, call.model) == ("ok", "groq", "groq-1")
    assert call.ttft_ms is not None and call.total_ms >= call.ttft_ms
    assert events.of("llm.switch") == []
    # Per-model params reach the wire (D-23).
    assert json.loads(routes.bodies[groq][0])["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [
        (429, None, "rate_limit"),
        (429, "insufficient_quota", "out_of_quota"),
        (429, "key_daily_cap", "out_of_quota"),
        (503, None, "service_error"),
        (401, None, "bad_key"),
        (400, "unsupported_parameter", "config_error"),
    ],
)
async def test_http_failure_moves_to_next_entry_and_calls_each_route_once(
    status: int,
    code: str | None,
    reason: SwitchReason,
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")
    error_route(routes, groq, status, code)
    sse_route(routes, exp, ["ok"])
    stream = await chain_factory("fast").stream(MSG)
    assert (stream.provider, stream.index) == ("experiential", 1)
    assert await text_of(stream) == "ok"
    assert (routes.count(groq), routes.count(exp)) == (1, 1)  # no SDK retries
    [switch] = events.of("llm.switch")
    assert (switch.from_provider, switch.to_provider) == ("groq", "experiential")
    assert switch.switch_reason == reason
    errors = [c for c in events.of("llm.call") if c.outcome == "error"]
    assert [(c.provider, c.error_kind) for c in errors] == [("groq", reason)]


async def test_connection_error_is_unreachable(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")

    async def refuse() -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    routes.add(groq, refuse)
    sse_route(routes, exp, ["ok"])
    stream = await chain_factory("fast").stream(MSG)
    assert stream.provider == "experiential"
    assert events.of("llm.switch")[0].switch_reason == "unreachable"
    assert routes.count(groq) == 1


async def test_ttft_deadline_counts_as_failure(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")
    hang_route(routes, groq)
    sse_route(routes, exp, ["ok"])
    stream = await chain_factory("fast").stream(MSG)
    assert stream.provider == "experiential"
    assert events.of("llm.switch")[0].switch_reason == "timeout"


async def test_keyless_entry_is_skipped_and_reported_not_configured(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    exp = host_of(models_cfg, "experiential")
    sse_route(routes, exp, ["ok"])
    stream = await chain_factory("fast", keys=("experiential",)).stream(MSG)
    assert (stream.provider, stream.index) == ("experiential", 1)
    assert routes.count(host_of(models_cfg, "groq")) == 0
    assert events.of("llm.switch") == []  # skipping is not a failure switch
    [role] = events.of("health.role")
    assert role.entries[0].status == "not_configured"
    assert role.entries[0].detail == "No key stored"


async def test_unresolved_model_is_skipped(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    raw = models_cfg.model_dump()
    raw["roles"]["fast"]["chain"][0]["model"] = ""
    sse_route(routes, host_of(models_cfg, "experiential"), ["ok"])
    stream = await chain_factory(
        "fast", models=ModelsConfig.model_validate(raw)
    ).stream(MSG)
    assert stream.provider == "experiential"
    [role] = events.of("health.role")
    assert "probe-models" in (role.entries[0].detail or "")


async def test_error_after_first_token_does_not_fail_over(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    groq, exp = host_of(models_cfg, "groq"), host_of(models_cfg, "experiential")
    midstream_error_route(routes, groq, ["Half a", " sentence"])
    sse_route(routes, exp, ["never used"])
    stream = await chain_factory("fast").stream(MSG)
    got: list[str] = []
    with pytest.raises(MidStreamError):
        async for chunk in stream:
            got.append(chunk)
    assert got[0] == "Half a"
    assert routes.count(exp) == 0
    assert events.of("llm.switch") == []
    [call] = events.of("llm.call")
    assert (call.outcome, call.provider) == ("error", "groq")


async def test_exhausted_chain_raises_and_emits(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    hosts = [
        host_of(models_cfg, p) for p in ("groq", "experiential", "google", "nvidia")
    ]
    for h in hosts:
        error_route(routes, h, 500)
    with pytest.raises(AllProvidersFailed):
        await chain_factory("fast").stream(MSG, data_class="general")
    assert [routes.count(h) for h in hosts] == [1, 1, 1, 1]
    assert len(events.of("llm.exhausted")) == 1
    assert len([c for c in events.of("llm.call") if c.outcome == "error"]) == 4
    assert events.of("health.role")[-1].status == "failing"


async def test_all_keyless_raises_without_any_request(
    routes: Routes, events: Events, chain_factory: ChainFactory
) -> None:
    with pytest.raises(AllProvidersFailed):
        await chain_factory("fast", keys=()).stream(MSG)
    assert routes.total == 0
    assert len(events.of("llm.exhausted")) == 1
    assert events.of("health.role")[-1].status == "not_configured"


async def test_secret_never_appears_in_events(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    error_route(routes, host_of(models_cfg, "groq"), 401)
    sse_route(routes, host_of(models_cfg, "experiential"), ["ok"])
    await text_of(await chain_factory("fast").stream(MSG))
    dump = " ".join(e.model_dump_json() for e in events.items)
    assert "fake-groq" not in dump and "fake-experiential" not in dump


def test_classify_unknown_error_is_service_error() -> None:
    assert classify(RuntimeError("x")) == "service_error"
    assert classify(TimeoutError()) == "timeout"
