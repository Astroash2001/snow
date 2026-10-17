"""Groq first, Moonshine when Groq cannot answer in time (VOIC-04, D-38, T-01-38).

Groq is faked at the HTTP layer (a fail-closed MockTransport), so the real GroqStt error
mapping is in play; the clock is fake so cooldowns need no waiting.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

import httpx2
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.contracts.events import SttStatus, TranscriptFinal
from snow.voice.config import SttConfig, VoiceConfig
from snow.voice.stt_groq import GroqStt, SttUnavailable
from snow.voice.stt_router import SttRouter
from tests.voice.conftest import FakeGroq, FakeLocalStt, RunFixture

T0 = 1000.0
PCM = b"\x00\x00" * 1600


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


class Slow(FakeGroq):
    """A Groq that answers after `delay_s` of real time."""

    delay_s: float = 0.0

    async def handler(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, request: httpx2.Request
    ) -> httpx2.Response:
        await asyncio.sleep(self.delay_s)
        return super().handler(request)


class Harness:
    def __init__(
        self, key: bool = True, local: bool = True, deadline_s: float = 2.5
    ) -> None:
        self.groq = Slow(text="from groq")
        self.handler: Callable[[httpx2.Request], Any] = self.groq.handler
        self.key = key
        self.clock = Clock()
        self.seen: list[tuple[str, str, int | None]] = []
        cfg: SttConfig = load_config("voice.toml", VoiceConfig).stt
        cfg = cfg.model_copy(update={"final_deadline_s": deadline_s})
        stt = GroqStt(
            cfg.groq,
            lambda _n: Secret("gsk_test_key_not_real") if self.key else None,
            transport=httpx2.MockTransport(lambda r: self.handler(r)),
        )
        self.router = SttRouter(
            stt, cfg, self.publish, has_local=local, clock=self.clock
        )
        self.router.announce()  # the pipeline does this in start()

    def publish(self, cls: type[SttStatus], **fields: object) -> None:
        assert cls is SttStatus
        e = SttStatus(
            ts_ns=0,
            source="voice",
            stt_source=fields["stt_source"],  # type: ignore[arg-type]
            status_reason=fields["status_reason"],  # type: ignore[arg-type]
            retry_after_ns=fields["retry_after_ns"],  # type: ignore[arg-type]
        )
        self.seen.append((e.stt_source, e.status_reason, e.retry_after_ns))

    async def turn(self, local_text: str = "from local") -> tuple[str, str]:
        done: Future[str] = Future()
        done.set_result(local_text)
        return await self.router.final(PCM, 16000, done)


def ns(t: float) -> int:
    return int(t * 1e9)


async def test_groq_in_time_is_the_final_and_primary_is_announced_once() -> None:
    h = Harness()
    for _ in range(3):
        assert await h.turn() == ("from groq", "groq")
    assert h.seen == [("groq", "primary", None)]
    assert h.router.health() == ("running", "Groq cloud")


async def test_rate_limit_waits_out_retry_after_then_returns_to_groq() -> None:
    h = Harness()
    h.groq.fail_with, h.groq.retry_after = 429, "30"
    assert await h.turn() == ("from local", "local")
    assert h.seen[-1] == ("local", "rate_limited", ns(T0 + 30))
    assert h.router.health() == ("running", "Local fallback")
    h.groq.fail_with = None
    h.clock.now = T0 + 29
    assert await h.turn() == ("from local", "local")
    assert len(h.groq.requests) == 1  # not called again inside retry-after
    h.clock.now = T0 + 31
    assert await h.turn() == ("from groq", "groq")
    assert h.seen[-1] == ("groq", "primary", None)


async def test_unreachable_is_retried_after_sixty_seconds() -> None:
    h = Harness()

    def refuse(request: httpx2.Request) -> httpx2.Response:
        h.groq.requests.append(request)
        raise httpx2.ConnectError("network down")

    h.handler = refuse
    assert await h.turn() == ("from local", "local")
    assert h.seen[-1] == ("local", "unreachable", ns(T0 + 60))
    h.clock.now = T0 + 59
    await h.turn()
    assert len(h.groq.requests) == 1
    h.clock.now = T0 + 61
    await h.turn()
    assert len(h.groq.requests) == 2


async def test_no_key_runs_local_only_and_notices_a_stored_key() -> None:
    h = Harness(key=False)
    assert h.seen == [("local", "no_key", ns(T0 + 60))]
    assert h.router.health() == ("running", "Local only (no Groq key)")
    assert await h.turn() == ("from local", "local")
    assert h.groq.requests == []
    h.key = True  # `snow setup` stored one
    assert await h.turn() == ("from groq", "groq")
    assert h.seen[-1] == ("groq", "primary", None)


async def test_a_slow_groq_costs_one_turn_and_three_misses_start_a_cooldown() -> None:
    h = Harness(deadline_s=0.05)
    h.groq.delay_s = 0.3
    for _ in range(2):
        assert await h.turn() == ("from local", "local")
    assert h.seen == [("groq", "primary", None)]  # no cooldown, no noise
    assert await h.turn() == ("from local", "local")
    assert h.seen[-1] == ("local", "unreachable", ns(T0 + 60))
    await h.turn()
    assert h.groq.requests == []  # late answers never finished; none during cooldown
    h.groq.delay_s = 0.0
    h.clock.now = T0 + 61
    assert await h.turn() == ("from groq", "groq")


async def test_a_fast_answer_resets_the_miss_count() -> None:
    h = Harness(deadline_s=0.05)
    h.groq.delay_s = 0.3
    await h.turn()
    await h.turn()
    h.groq.delay_s = 0.0
    assert (await h.turn())[1] == "groq"
    h.groq.delay_s = 0.3
    await h.turn()
    await h.turn()
    assert h.seen == [("groq", "primary", None)]  # two misses again, still no cooldown


async def test_without_a_local_model_groq_failure_is_unavailable() -> None:
    h = Harness(local=False)
    assert h.router.health() == ("running", None)
    h.groq.fail_with = 429
    with pytest.raises(SttUnavailable):
        await h.router.final(PCM, 16000, None)
    assert h.router.health() == ("down", "Groq unavailable")


async def test_a_local_model_that_never_loaded_is_unavailable_too() -> None:
    h = Harness()
    h.groq.fail_with = 429
    broken: Future[str] = Future()
    broken.set_exception(RuntimeError("no model"))
    with pytest.raises(SttUnavailable):
        await h.router.final(PCM, 16000, broken)


# --- through the pipeline --------------------------------------------------------


async def test_pipeline_uses_the_local_final_when_groq_is_limited(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    groq.fail_with, groq.retry_after = 429, "30"
    local = FakeLocalStt()
    run = await run_fixture("wake_cmd_gap150", "unused", local=local)
    finals = [e for e in run.hub.events if isinstance(e, TranscriptFinal)]
    assert len(finals) == 1
    assert finals[0].text == "what is the capital of France"
    assert finals[0].stt_source == "local"
    assert [(s.stt_source, s.status_reason) for s in run.hub.stt] == [
        ("groq", "primary"),
        ("local", "rate_limited"),
    ]
    assert run.hub.stt[-1].retry_after_ns is not None
    rows = [h.detail for h in run.hub.health if h.name == "speech_to_text"]
    assert rows[-1] == "Local fallback"


async def test_pipeline_groq_in_time_announces_primary_once(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    run = await run_fixture(
        "wake_cmd_gap150", "Hey Jarvis, what is the capital of France?"
    )
    assert [(s.stt_source, s.status_reason) for s in run.hub.stt] == [
        ("groq", "primary")
    ]
