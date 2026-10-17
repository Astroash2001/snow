"""SPCH-02 and SPCH-03: Cartesia speaks big moments within a daily budget, and every
failure falls back to the everyday voice and recovers on its own.

A local mock WebSocket server (127.0.0.1) plays Cartesia and an `httpx2.MockTransport`
plays its REST API, so nothing real is contacted and no credits are spent. The key is a
fake. Nothing is played and no audio is written anywhere.
"""

import asyncio
import base64
import json
import logging
import socket
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import numpy as np
import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from snow.config.secrets import Secret
from snow.contracts.events import VoiceStatus, VoiceSwitch
from snow.voice.tts.base import EngineError, EngineName
from snow.voice.tts.cartesia import CartesiaEngine, classify, parse_balance
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.router import VoiceRouter
from tests.voice.test_tts_router import CFG, Bus, FakeEngine, pocket_and_kokoro, say

KEY = "sk_car_test_key_not_real"
RATE = 24000


class MockCartesia:
    """Answers like the Cartesia TTS WebSocket: audio chunks, then `flush_done`.

    `error` is sent instead of audio for the n-th transcript (1-based) the client
    sends; `drop` closes the connection at that transcript."""

    def __init__(
        self, error: dict[str, Any] | None = None, error_at: int = 1, drop_at: int = 0
    ) -> None:
        self.received: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.connections = 0
        self.error, self.error_at, self.drop_at = error, error_at, drop_at
        self.stall = False  # never answer: the reply is still being generated
        self.url = ""

    async def handler(self, ws: ServerConnection) -> None:
        self.connections += 1
        self.headers.append({k.lower(): v for k, v in ws.request.headers.items()})
        pending, transcripts = "", 0
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                ctx = msg["context_id"]
                if msg["transcript"]:
                    transcripts += 1
                    pending += msg["transcript"]
                    if transcripts == self.drop_at:
                        await ws.close(1011)
                        return
                    if self.error is not None and transcripts == self.error_at:
                        await ws.send(
                            json.dumps(
                                {"type": "error", "done": True, "context_id": ctx}
                                | self.error
                            )
                        )
                        pending = ""
                elif self.stall:
                    continue
                elif msg.get("flush") and pending:
                    for n in (1, 2):  # two audio chunks per flush, in order
                        pcm = np.full(RATE // 20, 0.1 * n, dtype="<f4").tobytes()
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "chunk",
                                    "data": base64.b64encode(pcm).decode(),
                                    "done": False,
                                    "status_code": 206,
                                    "step_time": 1,
                                    "context_id": ctx,
                                }
                            )
                        )
                    await ws.send(
                        json.dumps(
                            {
                                "type": "flush_done",
                                "done": False,
                                "flush_done": True,
                                "flush_id": transcripts,
                                "status_code": 206,
                                "context_id": ctx,
                            }
                        )
                    )
                    pending = ""
                elif msg.get("flush"):  # after an error there is nothing to flush
                    continue
                elif msg["continue"] is False:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "done",
                                "done": True,
                                "status_code": 200,
                                "context_id": ctx,
                            }
                        )
                    )
        except ConnectionClosed:
            pass

    def transcripts(self) -> list[str]:
        return [m["transcript"] for m in self.received if m["transcript"]]


@pytest.fixture
async def mock() -> AsyncIterator[MockCartesia]:
    server = MockCartesia()
    async with serve(server.handler, "127.0.0.1", 0) as running:
        port = running.sockets[0].getsockname()[1]
        server.url = f"ws://127.0.0.1:{port}/tts/websocket"
        yield server


def closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"ws://127.0.0.1:{s.getsockname()[1]}/tts/websocket"


def cfg_for(url: str, **cartesia: Any) -> TtsConfig:
    base = CFG.engines.cartesia
    changed = base.model_copy(update={"ws_url": url, "voice_id": "voice-1", **cartesia})
    return CFG.model_copy(
        update={"engines": CFG.engines.model_copy(update={"cartesia": changed})}
    )


class Rest:
    """The Cartesia REST API: `GET /voices` answers `voices_status`; anything else is a
    violation (fail closed)."""

    def __init__(self, voices_status: int = 200, balance: object = None) -> None:
        self.voices_status = voices_status
        self.balance = balance
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == "/voices":
            return httpx2.Response(self.voices_status, json={"data": []})
        if request.url.path == "/credits" and self.balance is not None:
            return httpx2.Response(200, json=self.balance)
        return httpx2.Response(599)


class World:
    def __init__(
        self,
        url: str,
        *,
        key: bool = True,
        rest: Rest | None = None,
        **cartesia: Any,
    ) -> None:
        self.now = 0.0
        self.rest = rest or Rest()
        self.cfg = cfg_for(url, **cartesia)
        self.cartesia = CartesiaEngine(
            self.cfg.engines.cartesia,
            lambda _name: Secret(KEY) if key else None,
            clock=lambda: self.now,
            transport=httpx2.MockTransport(self.rest),
        )
        self.engines: dict[EngineName, Any] = pocket_and_kokoro()
        self.engines["cartesia"] = self.cartesia
        self.bus = Bus()
        self.router = VoiceRouter(
            self.engines,
            self.cfg,
            self.bus,
            clock=lambda: self.now,  # type: ignore[arg-type]
        )

    async def start(self) -> "World":
        self.router.start()
        await self.router.wait_ready()
        return self

    def pocket(self) -> FakeEngine:
        return self.engines["pocket_tts"]


@pytest.fixture
async def world(mock: MockCartesia) -> AsyncIterator[World]:
    w = await World(mock.url).start()
    yield w
    w.router.stop()


def last_status(w: World) -> VoiceStatus:
    return w.bus.of(VoiceStatus)[-1]


# --- the happy path --------------------------------------------------


async def test_a_big_moment_is_one_context_with_the_replys_emotion(
    world: World, mock: MockCartesia
) -> None:
    audio = await say(
        world.router, "We did it!", "All green.", emotion="excited", big_moment=True
    )
    await asyncio.sleep(0.1)  # the closing message is still on its way to the server

    sent = [m for m in mock.received if m["transcript"]]
    assert [m["transcript"] for m in sent] == ["We did it! ", "All green. "]
    assert len({m["context_id"] for m in mock.received}) == 1  # one context per reply
    first = sent[0]
    assert first["model_id"] == world.cfg.engines.cartesia.model
    assert first["voice"] == {"id": "voice-1"}
    assert first["output_format"] == {
        "container": "raw",
        "encoding": "pcm_f32le",
        "sample_rate": 24000,
    }
    assert first["generation_config"] == {"emotion": "excited"}
    assert first["language"] == "en"
    # continue is true on every chunk and false on the closing one
    assert [m["continue"] for m in mock.received] == [True, True, True, True, False]
    assert mock.received[-1]["transcript"] == ""
    assert [m.get("flush", False) for m in mock.received] == [False, True] * 2 + [False]
    # audio reached playout in order: 2 chunks per sentence, 0.1 then 0.2
    assert [round(float(a[0]), 1) for a in audio] == [0.1, 0.2, 0.1, 0.2]
    assert world.pocket().texts == []  # nothing fell back
    assert world.router.take_spoken() == {"cartesia": len("We did it!All green.")}
    assert last_status(world).engine == "cartesia"
    assert last_status(world).voice_role == "big_moment"
    assert last_status(world).cartesia_reason == "ok"


async def test_the_key_travels_in_a_header_and_never_in_the_url(
    world: World, mock: MockCartesia
) -> None:
    await say(world.router, "Hello!", emotion="happy", big_moment=True)

    assert mock.headers[0]["x-api-key"] == KEY
    assert mock.headers[0]["cartesia-version"] == world.cfg.engines.cartesia.api_version
    assert KEY not in mock.url


async def test_a_normal_reply_never_opens_a_cartesia_context(
    world: World, mock: MockCartesia
) -> None:
    await say(world.router, "Just a plain answer.", big_moment=False)

    assert mock.received == [] and mock.connections == 0
    assert world.pocket().texts == ["Just a plain answer."]
    assert world.router.take_spoken() == {"pocket_tts": len("Just a plain answer.")}


async def test_an_emotion_cartesia_does_not_know_is_spoken_as_neutral(
    world: World, mock: MockCartesia
) -> None:
    await say(world.router, "Hmm.", emotion="joking/comedic", big_moment=True)

    assert mock.received[0]["generation_config"] == {"emotion": "neutral"}


async def test_talking_over_cartesia_drops_its_context_without_counting_a_failure(
    mock: MockCartesia,
) -> None:
    mock.stall = True
    w = await World(mock.url).start()
    speaking = asyncio.ensure_future(
        say(w.router, "A long answer follows.", emotion="calm", big_moment=True)
    )
    for _ in range(200):  # until the text is out and Cartesia is "generating"
        if mock.transcripts():
            break
        await asyncio.sleep(0.01)

    w.router.cancel()  # barge-in: the pipeline stops the engine, then the task
    speaking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await speaking
    await asyncio.sleep(0.05)

    assert w.cartesia._ws is None  # noqa: SLF001 - the connection is gone
    assert w.cartesia.health.state == "ok" and w.cartesia.health.fails == 0
    assert w.pocket().texts == [] and w.bus.of(VoiceSwitch) == []
    w.router.stop()


# --- failures fall back (SPCH-03) ----------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        {"status_code": 402, "title": "Payment required", "message": "no"},
        {"status_code": 429, "message": "You have no credits left"},
        {
            "status_code": 429,
            "error_code": "quota_exceeded",
            "message": "Over the limit",
        },
    ],
)
async def test_out_of_credits_speaks_the_reply_in_pocket_and_says_why(
    mock: MockCartesia, error: dict[str, Any]
) -> None:
    mock.error = error
    w = await World(mock.url).start()

    await say(w.router, "Big news.", "More news.", emotion="excited", big_moment=True)

    assert w.cartesia.health.state == "out_of_credits"
    assert w.pocket().texts == ["Big news.", "More news."]  # this and the rest
    (switch,) = w.bus.of(VoiceSwitch)
    assert (switch.from_engine, switch.to_engine, switch.switch_reason) == (
        "cartesia",
        "pocket_tts",
        "out_of_credits",
    )
    status = last_status(w)
    assert (status.cartesia_available, status.cartesia_reason) == (
        False,
        "out_of_credits",
    )
    assert status.engine == "pocket_tts"

    await say(w.router, "Again.", emotion="excited", big_moment=True)  # not contacted
    assert mock.transcripts() == ["Big news. "]
    assert len(w.bus.of(VoiceSwitch)) == 1  # announced once
    w.router.stop()


async def test_two_connection_failures_mean_unreachable_and_the_probe_restores_it() -> (
    None
):
    w = await World(closed_port_url()).start()

    await say(w.router, "First.", big_moment=True)
    assert w.cartesia.health.state == "ok"  # one failure is not yet an outage
    await say(w.router, "Second.", big_moment=True)

    assert w.cartesia.health.state == "unreachable"
    assert w.pocket().texts == ["First.", "Second."]
    assert last_status(w).cartesia_reason == "unreachable"
    assert w.bus.of(VoiceSwitch)[-1].switch_reason == "unreachable"

    w.now = 89  # not yet
    assert not await w.cartesia.maybe_probe()
    assert w.rest.requests == []
    w.now = 91
    assert await w.cartesia.maybe_probe()  # GET /voices?limit=1 answered 200
    (request,) = w.rest.requests
    assert request.url.path == "/voices" and request.url.params["limit"] == "1"
    assert request.headers["x-api-key"] == KEY
    assert w.cartesia.health.state == "ok"
    w.router.announce()
    assert last_status(w).cartesia_available is True
    w.router.stop()


async def test_a_probe_that_is_refused_keeps_cartesia_down(mock: MockCartesia) -> None:
    mock.error = {"status_code": 402, "message": "credits"}
    w = await World(mock.url, rest=Rest(voices_status=401)).start()
    await say(w.router, "Big.", big_moment=True)

    w.now = 100
    assert not await w.cartesia.maybe_probe()
    assert w.cartesia.health.state == "out_of_credits"
    w.now = 150  # the interval counts from the last try
    assert not await w.cartesia.maybe_probe()
    assert len(w.rest.requests) == 1
    w.router.stop()


async def test_the_daily_budget_sends_a_big_moment_to_pocket(
    mock: MockCartesia,
) -> None:
    w = await World(mock.url).start()
    w.router.on_snapshot(640)  # the hub has counted 640 characters today

    await say(w.router, "Twenty characters!!", big_moment=True)  # 19 + 640 = 659 > 650

    assert mock.received == []
    assert w.pocket().texts == ["Twenty characters!!"]
    assert w.bus.of(VoiceSwitch)[0].switch_reason == "budget_reached"
    assert last_status(w).cartesia_available  # ten characters are still left
    w.router.on_snapshot(650)  # the day's budget is used up
    w.router.announce()
    assert (last_status(w).cartesia_available, last_status(w).cartesia_reason) == (
        False,
        "budget_reached",
    )
    w.router.stop()


async def test_the_budget_is_checked_per_chunk_so_it_can_run_out_mid_reply(
    mock: MockCartesia,
) -> None:
    w = await World(mock.url, daily_char_budget=30).start()

    await say(
        w.router,
        "Twelve chars.",  # 13: fits
        "Another twelve.",  # 13 + 15 = 28: fits
        "This one is too much.",  # 28 + 21 > 30: spoken in pocket
        big_moment=True,
    )

    assert mock.transcripts() == ["Twelve chars. ", "Another twelve. "]
    assert w.pocket().texts == ["This one is too much."]
    assert w.router.take_spoken() == {"cartesia": 28, "pocket_tts": 21}
    assert w.bus.of(VoiceSwitch)[0].switch_reason == "budget_reached"
    w.router.stop()


async def test_the_count_starts_again_on_a_new_day(mock: MockCartesia) -> None:
    w = await World(mock.url).start()
    day = [1]
    w.cartesia._today = lambda: day[0]  # type: ignore[assignment,return-value]  # noqa: SLF001
    w.router.on_snapshot(650)
    assert w.cartesia.unavailable_reason(5) == "budget_reached"
    day[0] = 2
    assert w.cartesia.unavailable_reason(5) is None
    w.router.stop()


async def test_without_a_stored_key_cartesia_is_never_contacted(
    mock: MockCartesia,
) -> None:
    w = await World(mock.url, key=False).start()

    await say(w.router, "Good morning!", emotion="happy", big_moment=True)

    assert mock.connections == 0 and w.rest.requests == []
    assert w.pocket().texts == ["Good morning!"]
    assert w.bus.of(VoiceSwitch)[0].switch_reason == "no_key"
    assert last_status(w).cartesia_reason == "no_key"
    w.router.stop()


async def test_without_a_voice_id_cartesia_is_skipped_quietly(
    mock: MockCartesia,
) -> None:
    w = await World(mock.url, voice_id="").start()

    await say(w.router, "Good morning!", big_moment=True)

    assert mock.connections == 0 and w.bus.of(VoiceSwitch) == []
    assert w.pocket().texts == ["Good morning!"]
    assert last_status(w).cartesia_reason is None
    w.router.stop()


async def test_a_rejected_key_is_reported_as_no_key_and_retried_by_the_probe(
    mock: MockCartesia,
) -> None:
    mock.error = {"status_code": 401, "message": "Invalid API key"}
    w = await World(mock.url).start()

    await say(w.router, "Hi!", big_moment=True)

    assert w.cartesia.health.state == "no_key"
    assert w.bus.of(VoiceSwitch)[0].switch_reason == "no_key"
    w.now = 91
    assert await w.cartesia.maybe_probe()  # the user fixed the key
    assert w.cartesia.health.state == "ok"
    w.router.stop()


async def test_the_first_error_payload_is_logged_once(
    mock: MockCartesia, caplog: pytest.LogCaptureFixture
) -> None:
    mock.error = {
        "status_code": 500,
        "error_code": None,
        "title": "Oops",
        "message": "boom",
    }
    w = await World(mock.url).start()
    caplog.set_level(logging.ERROR, logger="snow.voice")

    await say(w.router, "One.", big_moment=True)
    w.cartesia.health.restore()  # a second failure must not log the payload again
    await say(w.router, "Two.", big_moment=True)

    logged = [r for r in caplog.records if r.getMessage().startswith("cartesia_error")]
    assert len(logged) == 1
    assert "status=500" in logged[0].getMessage() and "boom" in logged[0].getMessage()
    assert KEY not in caplog.text
    w.router.stop()


# --- credits ------------------------------------------------------------


async def test_credits_stay_unavailable_when_the_config_names_no_endpoint(
    mock: MockCartesia,
) -> None:
    w = await World(mock.url).start()
    await w.cartesia.maybe_credits()
    w.router.announce(force=True)

    assert (
        w.cartesia.credits_remaining is None
        and last_status(w).credits_remaining is None
    )
    assert w.rest.requests == []  # no endpoint, no call
    w.router.stop()


async def test_a_credits_endpoint_that_reports_a_balance_is_shown(
    mock: MockCartesia,
) -> None:
    rest = Rest(balance={"plan": "free", "credits": {"credits_remaining": 18250}})
    w = await World(
        mock.url, rest=rest, credits_url="https://api.cartesia.ai/credits"
    ).start()

    await w.cartesia.maybe_credits()
    w.router.announce(force=True)
    assert last_status(w).credits_remaining == 18250

    await w.cartesia.maybe_credits()  # refreshed every 10 minutes, not on each look
    assert len(rest.requests) == 1
    w.now = 601
    await w.cartesia.maybe_credits()
    assert len(rest.requests) == 2
    w.router.stop()


def test_parse_balance_finds_a_remaining_number_or_nothing() -> None:
    assert parse_balance({"balance": 12.0}) == 12
    assert parse_balance({"a": {"b": [1, 2], "remaining_credits": 7}}) == 7
    assert parse_balance({"credits": 1200}) is None  # that is usage, not a balance
    assert parse_balance([1, 2]) is None


def test_classify_reads_status_code_and_message() -> None:
    assert classify(402, None, "") == "out_of_credits"
    assert classify(429, "quota_exceeded", "") == "out_of_credits"
    assert classify(None, None, "Not enough Credits") == "out_of_credits"
    assert classify(401, None, "") == "no_key"
    assert classify(500, None, "boom") == "unreachable"
    assert classify(429, "concurrency_limited", "too many") == "unreachable"


async def test_an_engine_without_a_key_refuses_to_stream() -> None:
    engine = CartesiaEngine(CFG.engines.cartesia, lambda _n: None)
    with pytest.raises(EngineError) as raised:
        [a async for a in engine.stream("Hi", "happy")]
    assert raised.value.kind == "no_key"


def test_plain_ws_is_refused_except_on_loopback() -> None:
    bad = CFG.engines.cartesia.model_copy(update={"ws_url": "ws://api.cartesia.ai/x"})
    with pytest.raises(EngineError):
        CartesiaEngine(bad, lambda _n: None).load()
    CartesiaEngine(CFG.engines.cartesia, lambda _n: None).load()  # wss: fine
    loopback = CFG.engines.cartesia.model_copy(update={"ws_url": "ws://127.0.0.1:1/x"})
    CartesiaEngine(loopback, lambda _n: None).load()


@pytest.mark.network
@pytest.mark.slow
async def test_real_cartesia_speaks_a_short_big_moment() -> None:
    """Spends about 20 credits of the user's free plan, so it is never run by default
    (`pytest -m network`). Needs the stored key and a `voice_id` in tts.toml."""
    from snow.config.secrets import get_secret  # noqa: PLC0415

    cfg = CFG.engines.cartesia
    if get_secret(cfg.key_name) is None or not cfg.voice_id:
        pytest.skip("needs a stored Cartesia key and a voice_id in tts.toml")
    engine = CartesiaEngine(cfg, get_secret)
    engine.load()
    try:
        audio = [a async for a in engine.stream("Good morning, sir.", "content")]
        await engine.end_reply()
    finally:
        engine.cancel()
    assert audio and all(a.dtype == np.float32 for a in audio)
    assert float(np.abs(np.concatenate(audio)).max()) > 0.01
