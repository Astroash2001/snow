"""The one client every worker (and dev tool) uses to talk to the hub (CORE-03)."""

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable

from pydantic import TypeAdapter, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from snow.config.settings import run_dir
from snow.contracts.events import Event, Heartbeat
from snow.contracts.wire import (
    Command,
    CommandMsg,
    EventMsg,
    Hello,
    Role,
    Snapshot,
    SnapshotMsg,
    WireMessage,
)

log = logging.getLogger("snow.hubclient")

BACKOFF_START_S = 0.5
BACKOFF_MAX_S = 8.0
HEARTBEAT_S = 2.0

_WIRE: TypeAdapter[WireMessage] = TypeAdapter(WireMessage)  # pyright: ignore[reportInvalidTypeArguments]

EventHandler = Callable[[Event], Awaitable[None]]
CommandHandler = Callable[[Command], Awaitable[None]]
SnapshotHandler = Callable[[Snapshot], Awaitable[None]]


class HubClient:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        role: Role,
        on_event: EventHandler | None = None,
        on_command: CommandHandler | None = None,
        on_snapshot: SnapshotHandler | None = None,
    ) -> None:
        self._url = url or os.environ.get("SNOW_HUB_URL")
        self._token = token or os.environ.get("SNOW_TOKEN")
        self.role: Role = role
        self.on_event = on_event
        self.on_command = on_command
        self.on_snapshot = on_snapshot
        self.connected = asyncio.Event()
        self._ws: ClientConnection | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def _target(self) -> tuple[str, str]:
        """Env/arguments win; else read hub.json fresh so a restarted hub is found."""
        if self._url and self._token:
            return self._url, self._token
        info = json.loads((run_dir() / "hub.json").read_text(encoding="utf-8"))
        return f"ws://127.0.0.1:{info['port']}", str(info["token"])

    async def run(self) -> None:
        delay = BACKOFF_START_S
        try:
            while True:
                try:
                    url, token = self._target()
                    async with connect(url) as ws:
                        await ws.send(
                            Hello(role=self.role, token=token).model_dump_json()
                        )
                        if await self._session(ws):
                            delay = BACKOFF_START_S
                except (OSError, ValueError, KeyError, WebSocketException) as e:
                    log.warning("hub_connect_failed kind=%s", type(e).__name__)
                self.connected.clear()
                await asyncio.sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)
        finally:
            for t in list(self._tasks):
                t.cancel()

    async def _session(self, ws: ClientConnection) -> bool:
        """Receive until the socket closes. Returns True if the hub registered us."""
        registered = False
        self._ws = ws
        beat = asyncio.create_task(self._heartbeat())
        try:
            async for raw in ws:
                try:
                    msg = _WIRE.validate_json(raw)
                except ValidationError:
                    # Unknown event type: skip so workers survive catalog growth.
                    log.warning("wire_message_skipped")
                    continue
                if isinstance(msg, SnapshotMsg):
                    registered = True
                    self.connected.set()
                    if self.on_snapshot:
                        self._spawn(self.on_snapshot(msg.snapshot))
                elif isinstance(msg, EventMsg) and self.on_event:
                    self._spawn(self.on_event(msg.event))
                elif isinstance(msg, CommandMsg) and self.on_command:
                    self._spawn(self.on_command(msg.command))
        except ConnectionClosed:
            pass
        finally:
            beat.cancel()
            self._ws = None
        return registered

    def _spawn(self, coro: Awaitable[None]) -> None:
        # Handlers run as tasks so a slow one (an LLM call) never blocks receiving.
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _heartbeat(self) -> None:
        while True:
            await self.publish(
                Heartbeat(ts_ns=time.time_ns(), source=self.role, worker=self.role)
            )
            await asyncio.sleep(HEARTBEAT_S)

    async def _send(self, text: str) -> None:
        ws = self._ws
        if ws is None:
            # shortcut: drops while disconnected, add an outbox if loss ever matters.
            log.warning("send_dropped_not_connected")
            return
        try:
            await ws.send(text)
        except ConnectionClosed:
            log.warning("send_dropped_closed")

    async def publish(self, event: Event) -> None:
        await self._send(EventMsg(event=event).model_dump_json())

    async def send_command(self, command: Command) -> None:
        await self._send(CommandMsg(command=command).model_dump_json())
