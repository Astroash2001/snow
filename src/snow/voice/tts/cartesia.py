"""Cartesia sonic-3.6, the big-moment voice (D-33, SPCH-02, SPCH-03).

Only replies the LLM marks as big moments come here, inside a daily character
budget that protects the free plan. Everything else, and every failure, goes to
the everyday voice: the engine classifies what went wrong (`CartesiaHealth`), the
router falls back, and a free authenticated probe brings Cartesia back on its
own. Reply text and the key (in a header, never a URL or a log) are all that
leave the PC; no audio is written anywhere.

One context is open per reply on one warm WebSocket, so prosody carries across
sentences. Each router chunk is followed by a flush: that is how the end of a
chunk is known, so a failure between chunks never repeats or drops audio.

Shortcut: a connection that dies in the middle of a chunk makes the router speak
that whole chunk again in the next voice, so its first words may repeat (a
clause, well under a second); upgrade by reporting how many samples were pushed
if that is ever heard.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast
from urllib.parse import urlparse

import httpx2
import numpy as np
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus, WebSocketException
from websockets.protocol import State

from snow.config.secrets import Secret
from snow.voice.tts.base import (
    EngineError,
    EngineLoadError,
    EngineName,
    ErrorKind,
    Samples,
)
from snow.voice.tts.config import CartesiaConfig

log = logging.getLogger("snow.voice")

CartesiaState = Literal[
    "ok", "out_of_credits", "unreachable", "no_key", "budget_reached"
]

# generation_config.emotion must match exactly (volume-speed-emotion guide); anything
# else would be rejected or undefined, so it becomes neutral.
EMOTIONS = frozenset(
    "neutral happy excited enthusiastic elated euphoric triumphant amazed surprised "
    "flirtatious curious content peaceful serene calm grateful affectionate trust "
    "sympathetic anticipation mysterious angry mad outraged frustrated agitated "
    "threatened disgusted contempt envious sarcastic ironic sad dejected melancholic "
    "disappointed hurt guilty bored tired rejected nostalgic wistful apologetic "
    "hesitant insecure confused resigned anxious panicked alarmed scared proud "
    "confident distant skeptical contemplative determined".split()
)

_CONNECT_TIMEOUT_S = 5.0
_RECV_TIMEOUT_S = 6.0  # silence from Cartesia this long counts as a failed attempt
_HTTP_TIMEOUT_S = 5.0
_CREDITS_EVERY_S = 600.0
_UNREACHABLE_AFTER = 2  # consecutive failures
_BALANCE_KEYS = ("credits_remaining", "remaining_credits", "remaining", "balance")


def classify(status: int | None, error_code: str | None, message: str) -> ErrorKind:
    """What a Cartesia error means for Snow (research Pattern 9). Failed requests
    cost no credits, so a wrong guess costs nothing but a fallback."""
    text = f"{error_code or ''} {message}".lower()
    if status == 402 or "credit" in text or "quota" in text:
        return "out_of_credits"
    if status in (401, 403):
        return "no_key"  # the key is missing or rejected: the probe notices a fix
    return "unreachable"


class CartesiaHealth:
    """`ok` until a failure says otherwise; out_of_credits and no_key are certain
    at once, a plain connection failure only on the second in a row."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self.state: CartesiaState = "ok"
        self.fails = 0
        self.since = clock()  # the last change, which the probe interval counts from

    def _set(self, state: CartesiaState) -> None:
        if state != self.state:
            self.state, self.since = state, self._clock()

    def failure(self, kind: ErrorKind) -> None:
        if kind == "unreachable":
            self.fails += 1
            if self.fails >= _UNREACHABLE_AFTER:
                self._set("unreachable")
        elif kind in ("out_of_credits", "no_key"):
            self._set(kind)

    def success(self) -> None:
        self.fails = 0

    def restore(self) -> None:
        self.fails = 0
        self._set("ok")


def parse_balance(data: object) -> int | None:
    """A remaining-credits number anywhere in a JSON reply, else None."""
    if isinstance(data, dict):
        found: dict[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
        for key in _BALANCE_KEYS:
            value = found.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return int(value)
        for value in found.values():
            if (inner := parse_balance(value)) is not None:
                return inner
    return None


@dataclass
class _Context:
    id: str
    emotion: str
    base: dict[str, Any]  # every field a continuation must repeat unchanged


class CartesiaEngine:
    name: EngineName = "cartesia"

    def __init__(
        self,
        cfg: CartesiaConfig,
        get_secret: Callable[[str], Secret | None],
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._cfg = cfg
        self._get_secret = get_secret
        self._clock = clock
        self._today = today
        self._transport = transport  # tests inject a fail-closed mock transport
        self.sample_rate = cfg.sample_rate
        self.voice_name = cfg.voice_name or "Cartesia"
        self.health = CartesiaHealth(clock)
        self.credits_remaining: int | None = None
        self._ws: ClientConnection | None = None
        self._ctx: _Context | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._base, self._since, self._day = 0, 0, today()  # characters spoken today
        self._last_probe = self._last_credits = float("-inf")
        self._error_logged = self._shape_logged = False
        self._closing: set[asyncio.Future[None]] = set()
        self._aborted = False  # cancel() ran: a dying socket is not an outage

    # --- the engine contract ------------------------------------------------------

    def load(self) -> None:
        url = urlparse(self._cfg.ws_url)
        local = url.hostname in ("127.0.0.1", "localhost", "::1")
        if url.scheme != "wss" and not (url.scheme == "ws" and local):
            raise EngineLoadError  # the key travels in a header: encrypted or loopback

    def cancel(self) -> None:
        """Barge-in or a newer reply: drop the connection, which stops the context."""
        self._aborted = True
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._drop)

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        self._loop = asyncio.get_running_loop()
        self._aborted = False
        secret = self._get_secret(self._cfg.key_name)
        if secret is None:
            raise EngineError("no_key")
        emotion = emotion if emotion in EMOTIONS else "neutral"
        counted = False
        try:
            await self._send(secret, text, emotion)
            ctx, ws = self._ctx, self._ws
            assert ctx is not None and ws is not None  # noqa: S101 - set by _send
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), _RECV_TIMEOUT_S)
                except (TimeoutError, OSError, WebSocketException) as e:
                    if self._aborted:  # the user talked over Snow; not a failure
                        raise asyncio.CancelledError from e
                    raise self._failed("unreachable") from e
                if (msg := _message(raw)) is None:
                    continue
                if msg.get("context_id") not in (None, ctx.id):
                    continue  # the tail of an earlier reply's context
                kind = msg.get("type")
                if kind == "chunk" and msg.get("data"):
                    audio = _decode(msg["data"])
                    if not counted:  # credits are spent from the first audio on
                        counted, self._since = True, self._since + len(text)
                        self.health.success()
                    yield audio
                elif kind in ("flush_done", "done"):
                    return
                elif kind == "error":
                    raise self._failed(_error_kind(msg), msg)
        except asyncio.CancelledError:
            self._drop()  # the context would keep generating
            raise
        except EngineError:
            self._drop()
            raise
        except ValueError as e:  # a message that is not what it says
            self._drop()
            raise self._failed("unreachable") from e

    async def end_reply(self) -> None:
        """The reply is over: close its context (`continue: false`, no more text)."""
        ctx, ws, self._ctx = self._ctx, self._ws, None
        if ctx is None or ws is None:
            return
        try:
            close = {**ctx.base, "transcript": "", "continue": False}
            await ws.send(json.dumps(close))
        except (OSError, WebSocketException):
            self._drop()

    # --- sending ------------------------------------------------------------------

    def _headers(self, secret: Secret) -> dict[str, str]:
        key = secret.reveal()
        return {
            "X-API-Key": key,
            "Authorization": f"Bearer {key}",
            "Cartesia-Version": self._cfg.api_version,
        }

    async def _open(self, secret: Secret) -> ClientConnection:
        ws = self._ws
        if ws is not None and ws.state is State.OPEN:
            return ws
        self._drop()
        try:
            ws = await asyncio.wait_for(
                connect(
                    self._cfg.ws_url,
                    additional_headers=self._headers(secret),
                    open_timeout=_CONNECT_TIMEOUT_S,
                ),
                _CONNECT_TIMEOUT_S + 1,
            )
        except InvalidStatus as e:
            raise self._failed(
                classify(e.response.status_code, None, e.response.reason_phrase)
            ) from e
        except (TimeoutError, OSError, WebSocketException) as e:
            raise self._failed("unreachable") from e
        self._ws = ws
        return ws

    async def _send(self, secret: Secret, text: str, emotion: str) -> None:
        """Put one chunk on the reply's context and flush, so its end is announced."""
        for attempt in (0, 1):
            reused = self._ws is not None
            ws = await self._open(secret)
            ctx = self._context(emotion)
            try:
                # Transcripts are joined verbatim, so each chunk ends with the space
                # between it and the next one.
                await ws.send(
                    json.dumps({**ctx.base, "transcript": f"{text} ", "continue": True})
                )
            except (OSError, WebSocketException) as e:
                self._drop()
                if attempt or not reused:  # a connection that idled out gets one retry
                    raise self._failed("unreachable") from e
                continue
            try:
                flush = {**ctx.base, "transcript": "", "continue": True, "flush": True}
                await ws.send(json.dumps(flush))
            except (OSError, WebSocketException) as e:
                self._drop()
                raise self._failed("unreachable") from e
            return

    def _context(self, emotion: str) -> _Context:
        """The reply's open context; a new one when there is none (fields must not
        change inside a context, so another emotion starts another)."""
        ctx = self._ctx
        if ctx is None or ctx.emotion != emotion:
            base: dict[str, Any] = {
                "model_id": self._cfg.model,
                "voice": {"id": self._cfg.voice_id},
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_f32le",
                    "sample_rate": self._cfg.sample_rate,
                },
                "language": "en",
                "generation_config": {"emotion": emotion},
                "context_id": uuid.uuid4().hex,
            }
            ctx = self._ctx = _Context(base["context_id"], emotion, base)
        return ctx

    def _failed(
        self, kind: ErrorKind, msg: dict[str, Any] | None = None
    ) -> EngineError:
        """Record a failure for health; the returned error carries it to the router."""
        if msg is not None and not self._error_logged:
            self._error_logged = True  # the first payload shows the real shape (A12)
            log.error(
                "cartesia_error status=%s code=%s title=%s message=%s",
                msg.get("status_code"),
                msg.get("error_code"),
                str(msg.get("title"))[:80],
                str(msg.get("message"))[:200],
            )
        self.health.failure(kind)
        log.error("tts_failed engine=cartesia kind=%s", kind)
        return EngineError(kind)

    def _drop(self) -> None:
        ws, self._ws, self._ctx = self._ws, None, None
        if ws is not None:
            task = asyncio.ensure_future(ws.close())
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    # --- budget and availability (SPCH-03) ----------------------------------------

    def set_base(self, chars_today: int) -> None:
        """The hub's count of Cartesia characters today (`tts.spoken` projection)."""
        self._base, self._since, self._day = chars_today, 0, self._today()

    def chars_today(self) -> int:
        if self._today() != self._day:  # a new day starts a new budget
            self._base, self._since, self._day = 0, 0, self._today()
        return self._base + self._since

    def unavailable_reason(self, chars: int) -> CartesiaState | None:
        """Why this chunk cannot go to Cartesia, or None when it can."""
        if self._get_secret(self._cfg.key_name) is None:
            return "no_key"
        if self.health.state != "ok":
            return self.health.state
        if self.chars_today() + max(chars, 1) > self._cfg.daily_char_budget:
            return "budget_reached"
        return None

    def status(self) -> tuple[bool, CartesiaState | None]:
        """(available, reason) for the voice card; reason None if not set up."""
        if not self._cfg.enabled or not self._cfg.voice_id:
            return False, None
        reason = self.unavailable_reason(0)
        return reason is None, reason or "ok"

    # --- keeping it healthy -------------------------------------------------------

    async def maintain(self) -> None:
        """Probe when down, refresh credits, keep a connection warm."""
        await self.maybe_probe()
        await self.maybe_credits()
        await self.warm()

    async def warm(self) -> None:
        secret = self._get_secret(self._cfg.key_name)
        if secret is None or not self._cfg.voice_id or self.health.state != "ok":
            return
        try:
            await self._open(secret)
        except EngineError:
            pass  # recorded; two in a row mark Cartesia unreachable

    def _client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=self._transport, timeout=_HTTP_TIMEOUT_S)

    async def maybe_probe(self) -> bool:
        """While unavailable, ask Cartesia for one voice every `probe_interval_s`. Free:
        no credits are spent. A 200 restores it."""
        secret = self._get_secret(self._cfg.key_name)
        if secret is None or self.health.state == "ok":
            return False
        now = self._clock()
        if now - max(self.health.since, self._last_probe) < self._cfg.probe_interval_s:
            return False
        self._last_probe = now
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self._cfg.api_base}/voices",
                    params={"limit": 1},
                    headers=self._headers(secret),
                )
        except httpx2.HTTPError:
            return False
        if response.status_code != 200:
            return False
        self.health.restore()
        return True

    async def maybe_credits(self) -> None:
        """Remaining credits, when the config names an endpoint that reports them."""
        secret = self._get_secret(self._cfg.key_name)
        if not self._cfg.credits_url or secret is None:
            return
        now = self._clock()
        if now - self._last_credits < _CREDITS_EVERY_S:
            return
        self._last_credits = now
        self.credits_remaining = await self.fetch_credits(secret)

    async def fetch_credits(self, secret: Secret) -> int | None:
        try:
            async with self._client() as client:
                response = await client.get(
                    self._cfg.credits_url, headers=self._headers(secret)
                )
            data = _message(response.content) if response.status_code == 200 else None
        except (httpx2.HTTPError, ValueError):
            return None
        if data is not None and not self._shape_logged:
            self._shape_logged = True  # the shape, never the values
            log.info("cartesia_credits_shape keys=%s", sorted(data))
        return parse_balance(data)


def _error_kind(msg: dict[str, Any]) -> ErrorKind:
    status = msg.get("status_code")
    return classify(
        status if isinstance(status, int) else None,
        str(msg["error_code"]) if msg.get("error_code") else None,
        f"{msg.get('title', '')} {msg.get('message', '')}",
    )


def _message(raw: str | bytes) -> dict[str, Any] | None:
    msg: Any = json.loads(raw)
    return cast("dict[str, Any]", msg) if isinstance(msg, dict) else None


def _decode(data: str) -> Samples:
    raw = base64.b64decode(data, validate=True)
    return np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<f4").astype(np.float32)
