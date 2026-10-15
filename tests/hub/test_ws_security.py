"""Hub security: auth, origin, size and the command role matrix (T-01-01, T-01-53)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from snow.hub import server
from snow.hub.eventlog import EventLog
from snow.hub.server import Hub


@pytest.fixture
async def hub(tmp_path: Path) -> AsyncIterator[tuple[Hub, EventLog, dict[str, Any]]]:
    log = EventLog(tmp_path / "snow.db")
    h = Hub(log, allowed_origins=[], run_dir=tmp_path / "run")
    await h.start()
    info = json.loads((tmp_path / "run" / "hub.json").read_text(encoding="utf-8"))
    yield h, log, info
    await h.stop()
    log.close()


async def _client(info: dict[str, Any], role: str) -> ClientConnection:
    ws = await connect(f"ws://127.0.0.1:{info['port']}")
    await ws.send(json.dumps({"kind": "hello", "role": role, "token": info["token"]}))
    await ws.recv()  # snapshot
    return ws


async def _closed_with(ws: ClientConnection) -> int | None:
    with pytest.raises(ConnectionClosed):
        await ws.recv()
    return ws.close_code


def _cmd(command: dict[str, Any]) -> str:
    return json.dumps({"kind": "command", "command": command})


async def test_wrong_token_closes_4401(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, _, info = hub
    ws = await connect(f"ws://127.0.0.1:{info['port']}")
    await ws.send(json.dumps({"kind": "hello", "role": "hud", "token": "0" * 64}))
    assert await _closed_with(ws) == 4401


async def test_missing_hello_is_closed(
    hub: tuple[Hub, EventLog, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, info = hub
    monkeypatch.setattr(server, "HELLO_TIMEOUT_S", 0.2)
    ws = await connect(f"ws://127.0.0.1:{info['port']}")
    assert await _closed_with(ws) == 4401


async def test_web_origin_rejected_with_403(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, _, info = hub
    with pytest.raises(InvalidStatus) as exc:
        await connect(
            f"ws://127.0.0.1:{info['port']}",
            additional_headers={"Origin": "https://evil.example"},
        )
    assert exc.value.response.status_code == 403


@pytest.mark.parametrize(
    ("role", "command"),
    [
        ("hud", {"type": "cmd.dev.say", "text": "hi"}),
        ("hud", {"type": "cmd.dev.kill", "worker": "voice"}),
        ("voice", {"type": "cmd.mute.set", "muted": True, "by": "hud"}),
        ("brain", {"type": "cmd.app.quit"}),
        ("dev", {"type": "cmd.mute.set", "muted": True, "by": "hud"}),
        ("dev", {"type": "cmd.app.quit"}),
    ],
)
async def test_forbidden_command_closes_4403(
    hub: tuple[Hub, EventLog, dict[str, Any]], role: str, command: dict[str, Any]
) -> None:
    _, log, info = hub
    ws = await _client(info, role)
    await ws.send(_cmd(command))
    assert await _closed_with(ws) == 4403
    assert log.rows() == []


async def test_allowed_commands_keep_the_socket_open(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, _, info = hub
    hud = await _client(info, "hud")
    await hud.send(_cmd({"type": "cmd.app.quit"}))
    await hud.send(_cmd({"type": "cmd.snapshot"}))
    assert json.loads(await hud.recv())["kind"] == "snapshot"
    await hud.close()


async def test_oversized_frame_is_rejected(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, log, info = hub
    ws = await _client(info, "dev")
    await ws.send("x" * (1_048_576 + 1))
    assert await _closed_with(ws) == 1009
    assert log.rows() == []
