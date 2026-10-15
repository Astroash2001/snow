"""Shared fixtures: in-memory keyring, temp dirs, in-process hub, OpenAI SSE helper."""

import json
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import keyring
import pytest
from keyring.backend import KeyringBackend
from openai import AsyncOpenAI

from snow.config.settings import repo_root
from snow.hub.eventlog import EventLog
from snow.hub.server import Hub


class InMemoryKeyring(KeyringBackend):
    priority = 1  # pyright: ignore[reportAssignmentType]

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._store.pop((service, username), None)


@pytest.fixture
def memory_keyring() -> Iterator[InMemoryKeyring]:
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@dataclass
class SnowDirs:
    data: Path
    config: Path


@pytest.fixture
def snow_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SnowDirs:
    data = tmp_path / "data"
    config = tmp_path / "config"
    shutil.copytree(repo_root() / "config", config)
    monkeypatch.setenv("SNOW_DATA_DIR", str(data))
    monkeypatch.setenv("SNOW_CONFIG_DIR", str(config))
    return SnowDirs(data=data, config=config)


@dataclass
class HubHandle:
    hub: Hub
    log: EventLog
    url: str
    token: str


@pytest.fixture
async def hub(snow_dirs: SnowDirs) -> AsyncIterator[HubHandle]:
    log = EventLog(snow_dirs.data / "snow.db")
    run = snow_dirs.data / "run"
    h = Hub(log, allowed_origins=[], run_dir=run)
    await h.start()
    token = json.loads((run / "hub.json").read_text(encoding="utf-8"))["token"]
    yield HubHandle(h, log, f"ws://127.0.0.1:{h.port}", token)
    await h.stop()
    log.close()


def openai_sse(chunks: list[str]) -> httpx2.Response:
    """A streamed chat-completions response: a delta per chunk, then stop and [DONE]."""

    def frame(delta: dict[str, str], finish: str | None) -> str:
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(body)}\n\n"

    frames = [frame({"role": "assistant", "content": ""}, None)]
    frames += [frame({"content": c}, None) for c in chunks]
    frames += [frame({}, "stop"), "data: [DONE]\n\n"]
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(frames).encode(),
    )


class MockProvider:
    """Fake provider HTTP API. openai 3.x uses httpx2, which respx cannot patch."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.responses: list[httpx2.Response] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def body(self) -> dict[str, object]:
        return json.loads(self.requests[-1].content)


@pytest.fixture
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> MockProvider:
    provider = MockProvider()

    def make(**kwargs: Any) -> AsyncOpenAI:
        # Fresh client per call: the worker closes the client it builds.
        transport = httpx2.MockTransport(provider.handler)
        return AsyncOpenAI(
            http_client=httpx2.AsyncClient(transport=transport), **kwargs
        )

    monkeypatch.setattr("snow.brain.worker.AsyncOpenAI", make)
    return provider
