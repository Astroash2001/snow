"""Tracer for CORE-03: dev line -> hub -> SQLite -> broadcast to every client."""

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

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


async def _client(
    info: dict[str, Any], role: str, token: str | None = None
) -> ClientConnection:
    ws = await connect(f"ws://127.0.0.1:{info['port']}")
    hello = {"kind": "hello", "role": role, "token": token or info["token"]}
    await ws.send(json.dumps(hello))
    return ws


async def _recv(ws: ClientConnection) -> dict[str, Any]:
    return json.loads(await ws.recv())


async def test_dev_say_is_stored_and_broadcast(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, log, info = hub
    assert set(info) == {"port", "token", "pid"}
    a = await _client(info, "hud")
    b = await _client(info, "dev")
    assert (await _recv(a))["kind"] == "snapshot"
    assert (await _recv(b))["kind"] == "snapshot"

    await b.send(
        json.dumps(
            {"kind": "command", "command": {"type": "cmd.dev.say", "text": "hello"}}
        )
    )
    msg = await _recv(a)
    assert msg["kind"] == "event"
    assert msg["event"]["type"] == "transcript.final"
    assert msg["event"]["source"] == "dev"
    assert msg["event"]["seq"] == 1
    assert msg["event"]["text"] == "hello"

    rows = log.rows(["transcript.final"])
    assert len(rows) == 1
    assert rows[0]["content"] == "hello"
    assert "text" not in json.loads(rows[0]["payload"])
    assert rows[0]["risk_tier"] == "free"
    assert rows[0]["correlation_id"].startswith("dev-")
    await a.close()
    await b.close()


async def test_late_client_snapshot_reports_last_seq(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, _, info = hub
    b = await _client(info, "dev")
    await _recv(b)
    await b.send(
        json.dumps({"kind": "command", "command": {"type": "cmd.dev.say", "text": "x"}})
    )
    await _recv(b)
    late = await _client(info, "hud")
    assert (await _recv(late))["snapshot"]["last_seq"] == 1
    await late.close()
    await b.close()


async def test_wrong_token_closes_4401(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, _, info = hub
    ws = await _client(info, "hud", token="0" * 64)
    with pytest.raises(ConnectionClosed):
        await ws.recv()
    assert ws.close_code == 4401


async def test_oversize_dev_say_closes_4400(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, log, info = hub
    ws = await _client(info, "dev")
    await _recv(ws)
    await ws.send(
        json.dumps(
            {"kind": "command", "command": {"type": "cmd.dev.say", "text": "x" * 2001}}
        )
    )
    with pytest.raises(ConnectionClosed):
        await ws.recv()
    assert ws.close_code == 4400
    assert log.rows() == []


async def test_ephemeral_event_is_broadcast_not_stored(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, log, info = hub
    a = await _client(info, "hud")
    b = await _client(info, "dev")
    await _recv(a)
    await _recv(b)
    beat = {
        "kind": "event",
        "event": {
            "type": "heartbeat",
            "ts_ns": time.time_ns(),
            "source": "dev",
            "worker": "t",
        },
    }
    await b.send(json.dumps(beat))
    msg = await _recv(a)
    assert msg["event"]["type"] == "heartbeat"
    assert msg["event"]["seq"] is None
    assert log.rows() == []
    await a.close()
    await b.close()


async def test_event_source_must_match_role(
    hub: tuple[Hub, EventLog, dict[str, Any]],
) -> None:
    _, log, info = hub
    ws = await _client(info, "dev")
    await _recv(ws)
    spoof = {
        "kind": "event",
        "event": {
            "type": "transcript.final",
            "ts_ns": 1,
            "source": "voice",
            "text": "spoof",
        },
    }
    await ws.send(json.dumps(spoof))
    with pytest.raises(ConnectionClosed):
        await ws.recv()
    assert ws.close_code == 4400
    assert log.rows() == []


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
