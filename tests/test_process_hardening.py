"""Priority, QoS opt-out, the stall dump: struct layout, failure paths, a real child."""

import asyncio
import ctypes
import faulthandler
import json
import logging
import subprocess
import sys
from typing import Any

import psutil
import pytest

from snow.common import hubclient, priority

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only API")

CHILD = """
import json, sys, time
import psutil
from snow.common.hubclient import arm_stall_dump
from snow.common.priority import raise_priority, read_throttling
ok = raise_priority()
print(json.dumps({"ok": ok, "nice": psutil.Process().nice(), "read": read_throttling(),
                  "above": psutil.ABOVE_NORMAL_PRIORITY_CLASS}), flush=True)
arm_stall_dump(0.2)
time.sleep(1.0)
"""


def test_throttling_struct_and_constants() -> None:
    assert priority.PROCESS_POWER_THROTTLING == 4
    assert priority.THROTTLING_VERSION == 1
    assert priority.EXECUTION_SPEED == 1
    assert ctypes.sizeof(priority.PowerThrottlingState) == 12
    names = [f[0] for f in priority.PowerThrottlingState._fields_]  # pyright: ignore[reportPrivateUsage]
    assert names == ["Version", "ControlMask", "StateMask"]


@WINDOWS
def test_a_failing_qos_call_is_logged_and_returns_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class K32:
        def __init__(self) -> None:
            self.GetCurrentProcess = lambda: 1
            self.SetProcessInformation = lambda *a: 0

    monkeypatch.setattr(priority, "_kernel32", K32)
    monkeypatch.setattr(psutil.Process, "nice", lambda *a: None)
    caplog.set_level(logging.WARNING, logger="snow.process")
    assert priority.raise_priority() is False
    assert "process_priority_failed step=qos" in caplog.text


@WINDOWS
def test_access_denied_on_priority_is_logged_and_returns_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def deny(*a: Any) -> None:
        raise psutil.AccessDenied()

    monkeypatch.setattr(priority, "_kernel32", lambda: _OkK32())
    monkeypatch.setattr(psutil.Process, "nice", deny)
    caplog.set_level(logging.WARNING, logger="snow.process")
    assert priority.raise_priority() is False
    assert "process_priority_failed step=priority" in caplog.text


class _OkK32:
    def __init__(self) -> None:
        self.GetCurrentProcess = lambda: 1
        self.SetProcessInformation = lambda *a: 1


@WINDOWS
def test_a_real_child_runs_above_normal_with_throttling_off_and_dumps_stacks() -> None:
    done = subprocess.run(  # noqa: S603 - our own interpreter and a fixed script
        [sys.executable, "-c", CHILD],
        creationflags=subprocess.CREATE_NO_WINDOW,  # same class as a supervised worker
        capture_output=True,
        timeout=60,
        check=True,
    )
    report = json.loads(done.stdout.decode().splitlines()[0])
    assert report["ok"] is True
    assert report["nice"] == report["above"]
    if report["read"] is not None:  # GetProcessInformation may not support this class
        control, state = report["read"]
        assert control & priority.EXECUTION_SPEED
        assert not state & priority.EXECUTION_SPEED
    assert "most recent call first" in done.stderr.decode()


async def test_heartbeat_arms_the_stall_dump_and_cancels_it_at_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed: list[float] = []
    cancelled: list[bool] = []
    monkeypatch.setattr(hubclient, "arm_stall_dump", armed.append)
    monkeypatch.setattr(
        faulthandler, "cancel_dump_traceback_later", lambda: cancelled.append(True)
    )
    monkeypatch.setattr(hubclient, "HEARTBEAT_S", 0.01)
    monkeypatch.setenv("SNOW_STALL_DUMP_S", "6")
    client = hubclient.HubClient("ws://x", "t", role="voice")

    async def publish(_: object) -> None: ...

    monkeypatch.setattr(client, "publish", publish)
    task = asyncio.create_task(client._heartbeat())  # pyright: ignore[reportPrivateUsage]
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert armed
    assert set(armed) == {6.0}
    assert cancelled == [True]


@pytest.mark.parametrize("value", [None, "", "abc", "0", "-3"])
async def test_heartbeat_never_arms_without_a_valid_setting(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    armed: list[float] = []
    monkeypatch.setattr(hubclient, "arm_stall_dump", armed.append)
    monkeypatch.setattr(hubclient, "HEARTBEAT_S", 0.01)
    if value is None:
        monkeypatch.delenv("SNOW_STALL_DUMP_S", raising=False)
    else:
        monkeypatch.setenv("SNOW_STALL_DUMP_S", value)
    client = hubclient.HubClient("ws://x", "t", role="voice")

    async def publish(_: object) -> None: ...

    monkeypatch.setattr(client, "publish", publish)
    task = asyncio.create_task(client._heartbeat())  # pyright: ignore[reportPrivateUsage]
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert armed == []
