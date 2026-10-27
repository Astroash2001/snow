"""Tracer for CORE-04, SAFE-09: dev line -> hub -> brain -> provider -> event log."""

import asyncio
import json
import time

import httpx2

from snow.brain.worker import BrainWorker
from snow.common.hubclient import HubClient
from snow.config.secrets import Secret, get_secret
from snow.contracts.events import Event, ReplyDelta, ReplyFinal, TranscriptFinal
from snow.contracts.wire import DevSay
from tests.conftest import (
    HubHandle,
    InMemoryKeyring,
    MockProvider,
    SnowDirs,
    openai_sse,
)

GROQ = "https://api.groq.com/openai/v1/chat/completions"


async def _next_final(inbox: asyncio.Queue[Event]) -> tuple[list[str], ReplyFinal]:
    deltas: list[str] = []
    async with asyncio.timeout(10):
        while True:
            ev = await inbox.get()
            if isinstance(ev, ReplyDelta):
                deltas.append(ev.text)
            elif isinstance(ev, ReplyFinal):
                return deltas, ev


async def test_dev_line_gets_llm_reply_and_both_sides_are_durable(
    hub: HubHandle,
    snow_dirs: SnowDirs,
    memory_keyring: InMemoryKeyring,
    mock_provider: MockProvider,
) -> None:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    mock_provider.responses += [
        openai_sse(["Good evening", ", sir."]),
        openai_sse(["Again."]),
    ]
    inbox: asyncio.Queue[Event] = asyncio.Queue()

    async def collect(ev: Event) -> None:
        inbox.put_nowait(ev)

    brain = HubClient(hub.url, hub.token, role="brain")
    brain.on_event = BrainWorker(brain.publish).on_event
    dev = HubClient(hub.url, hub.token, role="dev", on_event=collect)
    runners = [asyncio.create_task(brain.run()), asyncio.create_task(dev.run())]
    try:
        async with asyncio.timeout(10):
            await brain.connected.wait()
            await dev.connected.wait()

        await dev.send_command(DevSay(text="hello"))
        deltas, final = await _next_final(inbox)

        assert deltas == ["Good evening", ", sir."]
        assert final.text == "Good evening, sir."
        assert final.provider == "groq"
        rows = hub.log.rows(
            ["transcript.final", "reply.final", "reply.delta", "heartbeat"]
        )
        assert [r["type"] for r in rows] == ["transcript.final", "reply.final"]
        assert rows[0]["seq"] < rows[1]["seq"]
        assert json.loads(rows[1]["payload"])["model"] == "openai/gpt-oss-120b"
        assert str(mock_provider.requests[-1].url) == GROQ
        assert mock_provider.body()["model"] == "openai/gpt-oss-120b"
        assert mock_provider.requests[-1].headers["authorization"] == "Bearer gsk_test"

        # CORE-04: editing models.toml changes the next request with no code change.
        toml = snow_dirs.config / "models.toml"
        toml.write_text(
            toml.read_text(encoding="utf-8").replace(
                "openai/gpt-oss-120b", "test/other-model"
            ),
            encoding="utf-8",
        )
        await dev.send_command(DevSay(text="again"))
        await _next_final(inbox)
        assert mock_provider.body()["model"] == "test/other-model"
    finally:
        for t in runners:
            t.cancel()
        await asyncio.gather(*runners, return_exceptions=True)


async def test_provider_failure_before_first_token_publishes_no_reply(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, mock_provider: MockProvider
) -> None:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    # A 5xx cools only that model (quick 261026-nvh), so both groq entries are tried.
    mock_provider.responses += [httpx2.Response(500, json={"error": "boom"})] * 2
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    await BrainWorker(collect).on_event(
        TranscriptFinal(ts_ns=time.time_ns(), source="dev", text="hi")
    )
    assert len(mock_provider.requests) == 2  # one per groq model, then spent
    types = {ev.type for ev in published}
    assert {"llm.call", "llm.exhausted"} <= types
    assert not types & {"reply.delta", "reply.final"}


def test_secret_repr_is_masked_and_comes_only_from_keyring(
    memory_keyring: InMemoryKeyring,
) -> None:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    secret = get_secret("groq")
    assert isinstance(secret, Secret)
    assert repr(secret) == "Secret('***')"
    assert "gsk_test" not in f"{secret} {secret!r}"
    assert secret.reveal() == "gsk_test"
    assert get_secret("missing") is None
