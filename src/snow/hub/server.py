"""The hub: loopback WebSocket server, durable event log, broadcast (CORE-03, T-01-01).

Security (Pitfall 11): bind 127.0.0.1 only, per-launch 256-bit token in the first
Hello, Host and Origin checks, every inbound message validated with extra=forbid,
and a role matrix deciding which client may send which command (T-01-53).
"""

import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from snow.contracts.events import Event, MuteChanged, TranscriptFinal
from snow.contracts.wire import (
    COMMAND_ROLES,
    AppQuit,
    CommandMsg,
    DevKill,
    DevSay,
    EventMsg,
    Hello,
    MuteSet,
    Role,
    SnapshotMsg,
    SnapshotRequest,
    WireMessage,
)
from snow.hub.eventlog import EventLog
from snow.hub.projections import Projection, local_midnight_ns

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
HELLO_TIMEOUT_S = 2.0
MAX_MESSAGE_BYTES = 1_048_576
CLIENT_QUEUE_MAX = 1000
CLOSE_INVALID = 4400
CLOSE_AUTH = 4401
CLOSE_FORBIDDEN = 4403

_WIRE: TypeAdapter[WireMessage] = TypeAdapter(WireMessage)  # pyright: ignore[reportInvalidTypeArguments]
_ALWAYS_OK_ORIGINS = frozenset({"null", "file://"})


@dataclass(eq=False)
class _Client:
    ws: ServerConnection
    role: Role
    queue: asyncio.Queue[str] = field(
        default_factory=lambda: asyncio.Queue(CLIENT_QUEUE_MAX)
    )


class Hub:
    def __init__(
        self,
        event_log: EventLog,
        *,
        allowed_origins: list[str],
        run_dir: Path,
    ) -> None:
        self._log = event_log
        self._origins = _ALWAYS_OK_ORIGINS | set(allowed_origins)
        self._run_dir = run_dir
        self._token = secrets.token_hex(32)
        self._port = 0
        self._server: Server | None = None
        self._clients: set[_Client] = set()
        self._closing: set[asyncio.Task[None]] = set()
        self._projection = Projection()
        # Rebuild today's view from the durable log; the persisted mute wins (D-10).
        for event in event_log.replay(local_midnight_ns(time.time_ns())):
            self._projection.apply(event)
        mute = event_log.get_state("mute")
        if mute is not None:
            self._projection.set_muted(mute == "1")

    @property
    def port(self) -> int:
        return self._port

    async def start(self, port: int = 0) -> None:
        self._server = await serve(
            self._handle,
            HOST,
            port,
            max_size=MAX_MESSAGE_BYTES,
            process_request=self._check_request,
        )
        self._port = self._server.sockets[0].getsockname()[1]
        self._run_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._run_dir / "hub.json.tmp"
        tmp.write_text(
            json.dumps({"port": self._port, "token": self._token, "pid": os.getpid()}),
            encoding="utf-8",
        )
        tmp.replace(self._run_dir / "hub.json")

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        (self._run_dir / "hub.json").unlink(missing_ok=True)

    def _check_request(
        self, connection: ServerConnection, request: Request
    ) -> Response | None:
        host = request.headers.get("Host")
        if host != f"{HOST}:{self._port}":
            return connection.respond(HTTPStatus.FORBIDDEN, "bad host\n")
        origin = request.headers.get("Origin")
        if origin is not None and origin not in self._origins:
            return connection.respond(HTTPStatus.FORBIDDEN, "bad origin\n")
        return None

    def _snapshot_json(self) -> str:
        snapshot = self._projection.snapshot().model_copy(
            update={"last_seq": self._log.last_seq()}
        )
        return SnapshotMsg(snapshot=snapshot).model_dump_json()

    async def _handle(self, ws: ServerConnection) -> None:
        client = await self._authenticate(ws)
        if client is None:
            return
        # Register and snapshot with no await between, so no event can fall
        # in the gap between the snapshot and the live stream.
        client.queue.put_nowait(self._snapshot_json())
        self._clients.add(client)
        writer = asyncio.create_task(self._writer(client))
        try:
            async for raw in ws:
                if not await self._on_message(client, raw):
                    return
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(client)
            writer.cancel()

    async def _authenticate(self, ws: ServerConnection) -> _Client | None:
        try:
            raw = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S)
        except TimeoutError:
            await ws.close(CLOSE_AUTH, "hello timeout")
            return None
        except ConnectionClosed:
            return None
        try:
            hello = Hello.model_validate_json(raw)
        except ValidationError:
            await ws.close(CLOSE_INVALID, "invalid hello")
            return None
        if not hmac.compare_digest(hello.token.encode(), self._token.encode()):
            await ws.close(CLOSE_AUTH, "bad token")
            return None
        return _Client(ws=ws, role=hello.role)

    async def _writer(self, client: _Client) -> None:
        with contextlib.suppress(ConnectionClosed):
            while True:
                await client.ws.send(await client.queue.get())

    async def _on_message(self, client: _Client, raw: str | bytes) -> bool:
        """Handle one inbound message. Returns False when the socket was closed."""
        try:
            msg = _WIRE.validate_json(raw)
        except ValidationError:
            await client.ws.close(CLOSE_INVALID, "invalid message")
            return False
        if isinstance(msg, EventMsg):
            if msg.event.source != client.role:
                await client.ws.close(CLOSE_INVALID, "source must equal role")
                return False
            self._publish(msg.event)
        elif isinstance(msg, CommandMsg):
            if client.role not in COMMAND_ROLES[msg.command.type]:
                await client.ws.close(CLOSE_FORBIDDEN, "command not allowed for role")
                return False
            self._on_command(client, msg.command)
        else:
            await client.ws.close(CLOSE_INVALID, "message not allowed")
            return False
        return True

    def _on_command(
        self,
        client: _Client,
        cmd: MuteSet | AppQuit | SnapshotRequest | DevSay | DevKill,
    ) -> None:
        match cmd:
            case MuteSet():
                self._on_mute_set(cmd)
            case SnapshotRequest():
                client.queue.put_nowait(self._snapshot_json())
            case DevSay():
                # D-07: developer-only test input standing in for speech.
                self._publish(
                    TranscriptFinal(
                        ts_ns=time.time_ns(),
                        source="dev",
                        correlation_id=f"dev-{uuid.uuid4().hex}",
                        turn_id=uuid.uuid4().hex,
                        text=cmd.text,
                        stt_source="dev",
                    )
                )
            case AppQuit() | DevKill():
                # Accepted and logged here; acted on by the supervisor (plan 01-14).
                log.info("command accepted: %s from %s", cmd.type, client.role)

    def _on_mute_set(self, cmd: MuteSet) -> None:
        voice = next((c for c in self._clients if c.role == "voice"), None)
        if voice is not None:
            # The voice worker closes the mic, then reports mute.changed itself.
            self._send(voice, CommandMsg(command=cmd).model_dump_json())
            return
        # No voice worker: the mic is already closed, so the hub records the change.
        self._publish(
            MuteChanged(ts_ns=time.time_ns(), source="hub", muted=cmd.muted, by=cmd.by)
        )

    def _publish(self, event: Event) -> None:
        """Persist durable events (assigning seq), project, then broadcast to all."""
        if event.durable:
            event = event.model_copy(update={"seq": self._log.append(event)})
        if isinstance(event, MuteChanged):
            self._log.set_state("mute", "1" if event.muted else "0")
        self._projection.apply(event)
        text = EventMsg(event=event).model_dump_json()
        for client in list(self._clients):
            self._send(client, text)

    def _send(self, client: _Client, text: str) -> None:
        try:
            client.queue.put_nowait(text)
        except asyncio.QueueFull:
            # Slow consumer: drop it rather than stall everyone else.
            self._clients.discard(client)
            task = asyncio.create_task(client.ws.close(1013, "slow consumer"))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)
