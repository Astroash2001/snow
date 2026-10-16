"""snow dev probe-models against a fail-closed fake network."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from snow.brain.config import ModelsConfig
from snow.brain.probe import probe, rank_matches
from snow.config.secrets import Secret
from tests.conftest import openai_sse

MODEL_IDS = {
    "exp.test": ["luna", "deepseek-v4-flash"],
    "groq.test": ["openai/gpt-oss-120b"],
    "google.test": ["models/gem-2.5-flash", "models/gem-3-flash", "models/gem-3-pro"],
}


def _cfg() -> ModelsConfig:
    def prov(host: str, key: str, trust: str = "trusted") -> dict[str, str]:
        return {
            "label": key,
            "base_url": f"https://{host}/v1",
            "key_name": key,
            "trust": trust,
        }

    return ModelsConfig.model_validate(
        {
            "providers": {
                "experiential": prov("exp.test", "experiential"),
                "groq": prov("groq.test", "groq"),
                "google": prov("google.test", "google", "untrusted"),
                "nvidia": prov("nim.test", "nvidia"),
            },
            "roles": {
                "fast": {
                    "chain": [
                        {"provider": "groq", "model": "openai/gpt-oss-120b"},
                        {"provider": "google", "model": "", "match": "gem-*-flash"},
                        {"provider": "nvidia", "model": "", "match": "kimi-*"},
                    ]
                },
                "brain": {"chain": [{"provider": "experiential", "model": "luna"}]},
                "vision": {"chain": [{"provider": "experiential", "model": "luna"}]},
            },
        }
    )


class Fake:
    """Answers /models, /chat/completions and the catalog; anything else fails."""

    def __init__(self, *, tools: bool = True) -> None:
        self.tools = tools
        self.chat_bodies: list[dict[str, Any]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        host, path = request.url.host, request.url.path
        if host == "api.experientiallabs.ai" and path == "/api/models":
            model = {
                "slug": "luna",
                "input_modalities": ["text", "image"],
                "supported_params": {"tools": True, "stop": False},
            }
            return httpx2.Response(200, json={"models": [{"model": model}]})
        if path.endswith("/models") and host in MODEL_IDS:
            data = [
                {"id": i, "object": "model", "created": 0, "owned_by": "t"}
                for i in MODEL_IDS[host]
            ]
            return httpx2.Response(200, json={"object": "list", "data": data})
        if path.endswith("/chat/completions") and host in MODEL_IDS:
            body = json.loads(request.content)
            self.chat_bodies.append(body)
            if body.get("stream"):
                return openai_sse(["OK"])
            call = [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "ping", "arguments": "{}"},
                }
            ]
            message: dict[str, Any] = {"role": "assistant", "content": "red"}
            if "tools" in body and self.tools:
                message = {"role": "assistant", "content": None, "tool_calls": call}
            return httpx2.Response(
                200,
                json={
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": "stop"}
                    ],
                },
            )
        raise AssertionError(f"unrouted request: {request.method} {request.url}")

    def factory(self, **kwargs: Any) -> AsyncOpenAI:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))
        return AsyncOpenAI(http_client=client, **kwargs)

    def http(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))


def _keys(*names: str) -> Callable[[str], Secret | None]:
    return lambda name: Secret(f"fake-{name}") if name in names else None


async def _run(fake: Fake, *keys: str, latency_n: int = 0) -> dict[str, Any]:
    return await probe(
        _cfg(),
        secrets=_keys(*keys),
        client_factory=fake.factory,
        http=fake.http(),
        latency_n=latency_n,
    )


def _entry(report: dict[str, Any], role: str, provider: str) -> dict[str, Any]:
    return next(
        e for e in report["entries"] if e["role"] == role and e["provider"] == provider
    )


def test_rank_matches_ignores_unrelated_name_words() -> None:
    ids = ["gemini-omni-1.1-flash", "gemini-3.8-flash", "gemini-flash-latest"]
    assert rank_matches("gemini-*-flash", ids)[0] == "gemini-3.8-flash"


def test_rank_matches_picks_highest_version_first() -> None:
    ids = ["gem-2.5-flash", "gem-3-flash", "gem-10-flash", "gem-3-pro"]
    assert rank_matches("gem-*-flash", ids) == [
        "gem-10-flash",
        "gem-3-flash",
        "gem-2.5-flash",
    ]


async def test_glob_resolves_to_listed_id_and_report_is_json() -> None:
    report = await _run(Fake(), "experiential", "groq", "google")
    json.dumps(report)  # --json output must serialise
    google = _entry(report, "fast", "google")
    assert google["model"] == "gem-3-flash"  # "models/" prefix stripped, newest wins
    assert (google["stream"], google["tools"]) == (True, True)
    groq = _entry(report, "fast", "groq")
    assert groq["listed"] is True and groq["ttft_s"] is not None
    assert report["providers"]["groq"] == {"status": "ok", "models": 1}


async def test_keyless_provider_is_skipped_and_stays_unresolved() -> None:
    report = await _run(Fake(), "groq")
    assert report["providers"]["nvidia"]["status"] == "skipped: no key"
    nim = _entry(report, "fast", "nvidia")
    assert nim["model"] == "" and "no key" in nim["note"]


async def test_tool_call_detection_false_when_provider_ignores_tools() -> None:
    report = await _run(Fake(tools=False), "groq")
    assert _entry(report, "fast", "groq")["tools"] is False


async def test_vision_checked_only_for_vision_role_and_catalog_noted() -> None:
    report = await _run(Fake(), "experiential")
    assert _entry(report, "vision", "experiential")["vision"] is True
    brain = _entry(report, "brain", "experiential")
    assert brain["vision"] is None
    assert "input=text,image" in brain["note"]


async def test_latency_reports_p50_and_p95_per_candidate() -> None:
    report = await _run(Fake(), "groq", "experiential", latency_n=3)
    lat = report["latency"]["groq/openai/gpt-oss-120b"]
    assert lat["n"] == 3 and lat["errors"] == 0
    assert 0 <= lat["p50_s"] <= lat["p95_s"]
    assert report["latency"]["experiential/deepseek-v4-flash"]["n"] == 3


async def test_unrouted_host_fails_closed() -> None:
    fake = Fake()
    with pytest.raises(AssertionError):
        fake.handler(httpx2.Request("GET", "https://evil.test/v1/models"))
