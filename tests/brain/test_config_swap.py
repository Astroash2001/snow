"""CORE-04: editing models.toml changes who is called, with no code change."""

import time

import pytest

from snow.brain.worker import BrainWorker
from snow.contracts.events import Event, ReplyFinal, TranscriptFinal
from tests.brain.conftest import Routes, error_route, sse_route
from tests.conftest import InMemoryKeyring, SnowDirs

EXP = "exp.test"
GROQ = "groq.test"


def models_toml(
    *, fast_order: tuple[str, ...], groq_url: str = "https://groq.test/v1"
) -> str:
    entries = {
        "groq": '{ provider = "groq", model = "groq-1" }',
        "experiential": '{ provider = "experiential", model = "exp-1" }',
    }
    chain = ",\n  ".join(entries[p] for p in fast_order)
    return f"""
[providers.groq]
label = "Groq"
base_url = "{groq_url}"
key_name = "groq"
trust = "trusted"

[providers.experiential]
label = "Experiential Labs"
base_url = "https://exp.test/v1"
key_name = "experiential"
trust = "trusted"

[roles.fast]
chain = [
  {chain},
]
"""


async def say(worker: BrainWorker, published: list[Event]) -> ReplyFinal:
    await worker.on_event(
        TranscriptFinal(ts_ns=time.time_ns(), source="dev", text="hi")
    )
    return next(e for e in reversed(published) if isinstance(e, ReplyFinal))


@pytest.fixture
def worker_env(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> tuple[BrainWorker, list[Event], SnowDirs]:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    memory_keyring.set_password("snow", "experiential", "exp_test")
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    worker = BrainWorker(collect, client_factory=routes.client_factory)
    return worker, published, snow_dirs


async def test_reordering_fast_chain_changes_who_serves(
    worker_env: tuple[BrainWorker, list[Event], SnowDirs], routes: Routes
) -> None:
    worker, published, dirs = worker_env
    toml = dirs.config / "models.toml"

    toml.write_text(models_toml(fast_order=("groq", "experiential")), encoding="utf-8")
    sse_route(routes, GROQ, ["a"])
    first = await say(worker, published)
    assert (first.provider, first.model) == ("groq", "groq-1")

    toml.write_text(models_toml(fast_order=("experiential", "groq")), encoding="utf-8")
    sse_route(routes, EXP, ["b"])
    second = await say(worker, published)
    assert (second.provider, second.model) == ("experiential", "exp-1")
    assert (routes.count(GROQ), routes.count(EXP)) == (1, 1)


async def test_changing_a_base_url_sends_the_request_to_the_new_host(
    worker_env: tuple[BrainWorker, list[Event], SnowDirs], routes: Routes
) -> None:
    worker, published, dirs = worker_env
    toml = dirs.config / "models.toml"
    toml.write_text(models_toml(fast_order=("groq",)), encoding="utf-8")
    sse_route(routes, GROQ, ["a"])
    await say(worker, published)

    toml.write_text(
        models_toml(fast_order=("groq",), groq_url="https://elsewhere.test/v1"),
        encoding="utf-8",
    )
    sse_route(routes, "elsewhere.test", ["b"])
    final = await say(worker, published)
    assert final.text == "b"
    assert (routes.count(GROQ), routes.count("elsewhere.test")) == (1, 1)


async def test_reply_final_provider_always_equals_the_serving_entry(
    worker_env: tuple[BrainWorker, list[Event], SnowDirs], routes: Routes
) -> None:
    worker, published, dirs = worker_env
    (dirs.config / "models.toml").write_text(
        models_toml(fast_order=("groq", "experiential")), encoding="utf-8"
    )
    error_route(routes, GROQ, 503)
    sse_route(routes, EXP, ["from exp"])
    final = await say(worker, published)
    assert (final.provider, final.model, final.text) == (
        "experiential",
        "exp-1",
        "from exp",
    )
