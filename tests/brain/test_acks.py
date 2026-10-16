"""SPCH-01, CORE-10, D-09, D-17, D-28, D-41: ack pool, silence, cancel, facts."""

import asyncio
import json
import time
from typing import Any

import pytest

from snow.brain.worker import BrainWorker
from snow.contracts.events import (
    AckRequested,
    Event,
    ReplyDelta,
    ReplyFinal,
    SttStatus,
    TranscriptFinal,
    TurnCancelled,
    VoiceSwitch,
)
from snow.contracts.wire import Snapshot
from tests.brain.conftest import Routes, error_route, hang_route, sse_route
from tests.conftest import InMemoryKeyring, SnowDirs

GROQ = "api.groq.com"
EXP = "api.experientiallabs.ai"


def pool_reply(n: int, prefix: str = "line") -> list[str]:
    return ["\n".join(f"[[content]] {prefix} {i}" for i in range(n))]


def make_worker(
    routes: Routes, memory_keyring: InMemoryKeyring, *keys: str
) -> tuple[BrainWorker, list[Event]]:
    for key in keys or ("groq",):
        memory_keyring.set_password("snow", key, f"{key}_test")
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    return BrainWorker(collect, client_factory=routes.client_factory), published


def wake() -> AckRequested:
    return AckRequested(ts_ns=time.time_ns(), source="voice", turn_id="w1")


def heard(text: str, turn_id: str | None = None) -> TranscriptFinal:
    return TranscriptFinal(
        ts_ns=time.time_ns(), source="voice", text=text, turn_id=turn_id
    )


def body(routes: Routes, host: str, n: int = -1) -> dict[str, Any]:
    return json.loads(routes.bodies[host][n])


def system_of(routes: Routes, host: str, n: int = -1) -> str:
    return str(body(routes, host, n)["messages"][0]["content"])


# --- pool ---------------------------------------------------------------------


async def test_startup_fills_the_pool_with_one_general_call_carrying_no_user_text(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, GROQ, pool_reply(8))
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_snapshot(Snapshot())
    assert len(worker.acks) == 8 and routes.total == 1
    [call] = [e for e in published if e.type == "llm.call"]
    assert (call.role, call.data_class) == ("fast", "general")
    messages = body(routes, GROQ)["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "8" in messages[1]["content"] and "{n}" not in messages[1]["content"]


async def test_pool_ignores_model_chatter_and_duplicates(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    text = "Here are your lines:\n[[calm]] One\n[[calm]] One\n\n[[curious]] Two"
    sse_route(routes, GROQ, [text])
    worker, _ = make_worker(routes, memory_keyring)
    await worker.on_snapshot(Snapshot())
    assert len(worker.acks) == 2


async def test_ack_request_is_served_from_the_pool_instantly_with_no_network(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, GROQ, pool_reply(8))
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_snapshot(Snapshot())
    published.clear()
    started = time.perf_counter()
    await worker.on_event(wake())
    assert time.perf_counter() - started < 0.02
    assert [e.type for e in published] == ["reply.delta", "reply.final"]
    delta, final = published
    assert isinstance(delta, ReplyDelta) and isinstance(final, ReplyFinal)
    assert delta.text == final.text == "line 0"
    assert (final.reply_source, final.big_moment, final.emotion) == (
        "ack_pool",
        False,
        "content",
    )
    assert (final.provider, final.model) == ("groq", "openai/gpt-oss-120b")
    assert final.turn_id == "w1"
    assert routes.total == 1  # no new call while the pool is above its minimum


async def test_pool_refills_in_the_background_when_it_runs_low(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, GROQ, pool_reply(8))
    worker, _ = make_worker(routes, memory_keyring)
    await worker.on_snapshot(Snapshot())
    for _ in range(5):
        await worker.on_event(wake())
    assert routes.total == 1 and len(worker.acks) == 3
    sse_route(routes, GROQ, pool_reply(5, "fresh"))
    await worker.on_event(wake())  # leaves 2, below the minimum of 3
    task = worker.acks.ensure_refill()
    assert task is not None
    await task
    assert routes.total == 2 and len(worker.acks) == 7


# --- silence when no model can answer (D-41) -------------------------------------


async def test_empty_pool_and_every_provider_down_is_silent(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    error_route(routes, GROQ, 500)  # one failure cools groq, sparing its 2nd entry
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(wake())
    assert not [e for e in published if isinstance(e, ReplyDelta)]
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    assert final.reply_source == "fallback"
    assert (final.text, final.emotion, final.big_moment) == ("", "neutral", False)
    assert (final.provider, final.model) == (None, None)
    assert "llm.exhausted" in {e.type for e in published}


async def test_deadline_expiry_is_silent_and_the_refill_keeps_running(
    snow_dirs: SnowDirs,
    memory_keyring: InMemoryKeyring,
    routes: Routes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("snow.brain.worker.ACK_DEADLINE_S", 0.05)
    hang_route(routes, GROQ)
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(wake())
    assert not [e for e in published if isinstance(e, ReplyDelta)]
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    assert (final.reply_source, final.text, final.provider) == ("fallback", "", None)
    task = worker.acks.ensure_refill()
    assert task is not None and not task.done()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# --- cancellation -----------------------------------------------------------------


async def test_turn_cancelled_stops_the_stream_without_a_reply_final(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, GROQ, ["[[content]] First part, ", "second part, ", "third."])
    started = asyncio.Event()
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)
        if isinstance(ev, ReplyDelta):
            started.set()
            await asyncio.sleep(30)  # the reply is mid-stream when the cancel lands

    memory_keyring.set_password("snow", "groq", "groq_test")
    worker = BrainWorker(collect, client_factory=routes.client_factory)
    turn = asyncio.ensure_future(worker.on_event(heard("tell me a story", "t1")))
    await asyncio.wait_for(started.wait(), 5)
    await worker.on_event(
        TurnCancelled(ts_ns=1, source="voice", turn_id="t1", cancel_reason="barge_in")
    )
    with pytest.raises(asyncio.CancelledError):
        await turn
    assert not [e for e in published if isinstance(e, ReplyFinal)]
    [call] = [e for e in published if e.type == "llm.call"]
    assert (call.outcome, call.turn_id) == ("cancelled", "t1")


async def test_cancelling_another_turn_leaves_the_active_one_alone(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, GROQ, ["[[content]] Fine."])
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(
        TurnCancelled(ts_ns=1, source="voice", turn_id="other", cancel_reason="mute")
    )
    await worker.on_event(heard("hello", "t2"))
    assert [e for e in published if isinstance(e, ReplyFinal)]


# --- one-time context facts ---------------------------------------------------------


async def test_limit_switch_is_mentioned_once_in_the_next_request_only(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    error_route(routes, GROQ, 429)
    sse_route(routes, EXP, ["[[content]] One."])
    sse_route(routes, EXP, ["[[content]] Two."])
    sse_route(routes, EXP, ["[[content]] Three."])
    worker, _ = make_worker(routes, memory_keyring, "groq", "experiential")
    for text in ("a", "b", "c"):
        await worker.on_event(heard(text))
    marker = "provider was just switched from groq to experiential"
    assert marker not in system_of(routes, EXP, 0)  # the call that caused the switch
    assert marker in system_of(routes, EXP, 1) and "a rate limit" in system_of(
        routes, EXP, 1
    )
    assert marker not in system_of(routes, EXP, 2)


async def test_voice_switch_becomes_a_one_time_fact(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, GROQ, ["[[content]] One."])
    sse_route(routes, GROQ, ["[[content]] Two."])
    worker, _ = make_worker(routes, memory_keyring)
    await worker.on_event(
        VoiceSwitch(
            ts_ns=1,
            source="voice",
            from_engine="cartesia",
            to_engine="pocket_tts",
            switch_reason="out_of_credits",
        )
    )
    await worker.on_event(heard("a"))
    await worker.on_event(heard("b"))
    assert "from cartesia to pocket_tts" in system_of(routes, GROQ, 0)
    assert "from cartesia to pocket_tts" not in system_of(routes, GROQ, 1)


async def test_stt_fallback_is_one_fact_per_episode(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    for _ in range(3):
        sse_route(routes, GROQ, ["[[content]] Ok."])
    worker, _ = make_worker(routes, memory_keyring)

    def stt(reason: str) -> SttStatus:
        return SttStatus(
            ts_ns=1,
            source="voice",
            stt_source="groq" if reason == "primary" else "local",
            status_reason=reason,  # pyright: ignore[reportArgumentType]
        )

    await worker.on_event(stt("primary"))  # healthy: nothing to say
    await worker.on_event(stt("unreachable"))
    await worker.on_event(stt("unreachable"))  # same episode
    await worker.on_event(heard("a"))
    await worker.on_event(heard("b"))
    await worker.on_event(stt("primary"))
    await worker.on_event(stt("offline"))  # a new episode
    await worker.on_event(heard("c"))
    marker = "Speech recognition fell back to local"
    assert system_of(routes, GROQ, 0).count(marker) == 1
    assert marker not in system_of(routes, GROQ, 1)
    assert system_of(routes, GROQ, 2).count(marker) == 1
