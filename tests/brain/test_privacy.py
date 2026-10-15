"""SAFE-12: private data never reaches an untrusted provider; blocking sends nothing."""

import time

import pytest
from openai.types.chat import ChatCompletionMessageParam

from snow.brain.chain import PrivacyBlockedError
from snow.brain.config import ModelsConfig
from snow.brain.worker import BrainWorker
from snow.contracts.events import Event, ReplyFinal, TranscriptFinal
from tests.brain.conftest import (
    ChainFactory,
    Events,
    Routes,
    error_route,
    host_of,
    sse_route,
)
from tests.conftest import InMemoryKeyring, SnowDirs

MSG: list[ChatCompletionMessageParam] = [{"role": "user", "content": "my diary"}]
UNTRUSTED_ONLY = ("google", "openrouter")


async def test_private_call_with_only_untrusted_providers_sends_nothing(
    routes: Routes, events: Events, chain_factory: ChainFactory
) -> None:
    with pytest.raises(PrivacyBlockedError):
        await chain_factory("brain", keys=UNTRUSTED_ONLY).stream(
            MSG, data_class="private"
        )
    assert routes.total == 0  # the zero-request proof
    [blocked] = events.of("llm.blocked_privacy")
    assert (blocked.role, blocked.data_class) == ("brain", "private")
    assert events.of("llm.exhausted") == []


async def test_call_without_data_class_fails_closed(
    routes: Routes, events: Events, chain_factory: ChainFactory
) -> None:
    with pytest.raises(PrivacyBlockedError):
        await chain_factory("brain", keys=UNTRUSTED_ONLY).stream(MSG)
    assert routes.total == 0
    assert len(events.of("llm.blocked_privacy")) == 1


async def test_general_data_may_use_untrusted_providers(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    google = host_of(models_cfg, "google")
    sse_route(routes, google, ["ok"])
    stream = await chain_factory("brain", keys=UNTRUSTED_ONLY).stream(
        MSG, data_class="general"
    )
    assert stream.provider == "google"
    assert routes.count(google) == 1
    assert events.of("llm.blocked_privacy") == []


async def test_private_call_skips_untrusted_entry_and_uses_next_trusted(
    models_cfg: ModelsConfig,
    routes: Routes,
    events: Events,
    chain_factory: ChainFactory,
) -> None:
    exp, google, nim = (
        host_of(models_cfg, p) for p in ("experiential", "google", "nvidia")
    )
    error_route(routes, exp, 503)
    sse_route(routes, nim, ["ok"])
    stream = await chain_factory("brain").stream(MSG, data_class="private")
    assert (stream.provider, stream.index) == ("nvidia", 2)
    assert routes.count(google) == 0
    assert events.of("llm.switch")[0].to_provider == "nvidia"


async def test_conversation_turn_with_only_untrusted_keys_is_blocked_end_to_end(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    (snow_dirs.config / "models.toml").write_text(
        """
[providers.google]
label = "Google AI Studio"
base_url = "https://google.test/v1beta/openai/"
key_name = "google"
trust = "untrusted"

[roles.fast]
chain = [{ provider = "google", model = "gem-1" }]
""",
        encoding="utf-8",
    )
    memory_keyring.set_password("snow", "google", "g_test")
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    worker = BrainWorker(collect, client_factory=routes.client_factory)
    await worker.on_event(
        TranscriptFinal(ts_ns=time.time_ns(), source="dev", text="private words")
    )
    assert routes.total == 0
    assert not [e for e in published if isinstance(e, ReplyFinal)]
    assert [e.type for e in published if e.type.startswith("llm.")] == [
        "llm.blocked_privacy"
    ]
