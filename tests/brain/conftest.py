"""Brain fixtures: a fail-closed fake provider network, fake clock, chain factory.

openai 3.29 runs on httpx2, which respx cannot patch, so provider HTTP is faked with an
`httpx2.MockTransport` injected into each AsyncOpenAI client (the 01-03 mechanism).
Routes are keyed by host. A request to a host with no queued response is recorded as a
violation and fails the test at teardown, so a test can never silently reach a provider.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from snow.brain.chain import LLMChain
from snow.brain.config import ModelsConfig
from snow.config.secrets import Secret
from snow.contracts.events import Event, LlmRole
from tests.conftest import openai_sse

Reply = httpx2.Response | Callable[[], Awaitable[httpx2.Response]]

CHAT_PATH = "/chat/completions"


def _provider(base_url: str, key_name: str, trust: str) -> dict[str, str]:
    return {
        "label": key_name,
        "base_url": base_url,
        "key_name": key_name,
        "trust": trust,
    }


def _entry(provider: str, model: str, **extra: object) -> dict[str, object]:
    return {"provider": provider, "model": model, **extra}


MODELS: dict[str, Any] = {
    "providers": {
        "experiential": _provider("https://exp.test/v1", "experiential", "trusted"),
        "groq": _provider("https://groq.test/v1", "groq", "trusted"),
        "google": _provider(
            "https://google.test/v1beta/openai/", "google", "untrusted"
        ),
        "nvidia": _provider("https://nim.test/v1", "nvidia", "trusted"),
        "openrouter": _provider("https://or.test/api/v1", "openrouter", "untrusted"),
    },
    "roles": {
        "fast": {
            "ttft_timeout_s": 0.2,
            "chain": [
                _entry("groq", "groq-1", params={"reasoning_effort": "low"}),
                _entry("experiential", "exp-1"),
                _entry("google", "gem-1"),
                _entry("nvidia", "nim-1"),
            ],
        },
        "brain": {
            "ttft_timeout_s": 0.2,
            "chain": [
                _entry(
                    "experiential",
                    "luna",
                    drop_params=["temperature"],
                    params={"temperature": 0.3, "reasoning_effort": "low"},
                ),
                _entry("google", "gem-1"),
                _entry("nvidia", "nim-1"),
                _entry("openrouter", "or-1"),
            ],
        },
        "vision": {"chain": [_entry("experiential", "luna")]},
    },
}


@pytest.fixture
def models_cfg() -> ModelsConfig:
    return ModelsConfig.model_validate(MODELS)


def host_of(models: ModelsConfig, provider: str) -> str:
    host = httpx2.URL(models.providers[provider].base_url).host
    return host


@dataclass
class Routes:
    """Per-host response queues plus request counters; unrouted hosts fail closed."""

    queues: dict[str, list[Reply]] = field(default_factory=dict[str, list[Reply]])
    calls: dict[str, int] = field(default_factory=dict[str, int])
    bodies: dict[str, list[bytes]] = field(default_factory=dict[str, list[bytes]])
    violations: list[str] = field(default_factory=list[str])

    def add(self, host: str, reply: Reply) -> None:
        self.queues.setdefault(host, []).append(reply)

    @property
    def total(self) -> int:
        return sum(self.calls.values())

    def count(self, host: str) -> int:
        return self.calls.get(host, 0)

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        queue = self.queues.get(host, [])
        if not request.url.path.endswith(CHAT_PATH) or not queue:
            self.violations.append(f"{request.method} {request.url}")
            raise AssertionError(f"unrouted request: {request.url}")
        self.calls[host] = self.calls.get(host, 0) + 1
        self.bodies.setdefault(host, []).append(request.content)
        reply = queue.pop(0)
        return reply if isinstance(reply, httpx2.Response) else await reply()

    def client_factory(self, **kwargs: Any) -> AsyncOpenAI:
        transport = httpx2.MockTransport(self.handler)
        return AsyncOpenAI(
            http_client=httpx2.AsyncClient(transport=transport), **kwargs
        )


@pytest.fixture
def routes() -> Iterator[Routes]:
    r = Routes()
    yield r
    assert r.violations == [], f"unrouted provider requests: {r.violations}"


def sse_route(routes: Routes, host: str, chunks: list[str]) -> None:
    """Queue a streamed 200 reply for `host`."""
    routes.add(host, openai_sse(chunks))


def error_route(
    routes: Routes, host: str, status: int, code: str | None = None
) -> None:
    body: dict[str, object] = {"error": {"message": "x", "type": "e", "code": code}}
    routes.add(host, httpx2.Response(status, json=body))


def midstream_error_route(routes: Routes, host: str, chunks: list[str]) -> None:
    """A 200 stream that delivers `chunks` then breaks the connection."""
    ok = openai_sse(chunks).content.decode()
    # Drop the stop frame and [DONE] so the stream ends abruptly after the text.
    cut = ok[: ok.index('"finish_reason": "stop"')]
    cut = cut[: cut.rindex("data: ")]

    async def body() -> AsyncIterator[bytes]:
        yield cut.encode()
        raise httpx2.ReadError("connection reset")

    routes.add(
        host,
        httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=body()
        ),
    )


def stall_route(routes: Routes, host: str, chunks: list[str]) -> None:
    """A 200 stream that delivers `chunks` as text and then never ends."""
    ok = openai_sse(chunks).content.decode()
    cut = ok[: ok.index('"finish_reason": "stop"')]
    cut = cut[: cut.rindex("data: ")]

    async def body() -> AsyncIterator[bytes]:
        yield cut.encode()
        await asyncio.Event().wait()

    routes.add(
        host,
        httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=body()
        ),
    )


def hang_route(routes: Routes, host: str) -> None:
    async def hang() -> httpx2.Response:
        await asyncio.sleep(30)
        return httpx2.Response(500)

    routes.add(host, hang)


@dataclass
class Events:
    items: list[Event] = field(default_factory=list[Event])

    async def emit(self, event: Event) -> None:
        self.items.append(event)

    def of(self, type_: str) -> list[Any]:
        return [e for e in self.items if e.type == type_]  # pyright: ignore[reportAttributeAccessIssue]


@pytest.fixture
def events() -> Events:
    return Events()


class FakeClock:
    """Each read advances 50 ms, so recorded latencies are deterministic."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 0.05
        return self.t


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


ChainFactory = Callable[..., LLMChain]
ALL_KEYS = ("experiential", "groq", "google", "nvidia", "openrouter")


@pytest.fixture
async def chain_factory(
    models_cfg: ModelsConfig, routes: Routes, events: Events, fake_clock: FakeClock
) -> AsyncIterator[ChainFactory]:
    made: list[LLMChain] = []

    def make(
        role: LlmRole,
        keys: tuple[str, ...] = ALL_KEYS,
        models: ModelsConfig | None = None,
    ) -> LLMChain:
        chain = LLMChain(
            models or models_cfg,
            role,
            get_secret=lambda name: Secret(f"fake-{name}") if name in keys else None,
            emit=events.emit,
            now=fake_clock,
            client_factory=routes.client_factory,
        )
        made.append(chain)
        return chain

    yield make
    for chain in made:
        await chain.aclose()
