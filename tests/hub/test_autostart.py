"""Autostart script text, single instance, quit semantics and the HUD --autostart flag.

SAFETY: nothing here registers or removes a real scheduled task. Install/uninstall are
checked through `--print` and by capturing the PowerShell invocation.
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest

from snow import cli
from snow.common.hubclient import HubClient
from snow.config.settings import repo_root
from snow.contracts.wire import AppQuit
from tests.conftest import SnowDirs


def _print_script(command: str, capsys: pytest.CaptureFixture[str], *flags: str) -> str:
    assert cli.main([command, "--print", *flags]) == 0
    return capsys.readouterr().out


def test_install_print_has_every_laptop_daemon_setting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _print_script("install-autostart", capsys)
    pythonw = repo_root() / ".venv" / "Scripts" / "pythonw.exe"
    for needle in (
        "-AtLogOn",
        "-ExecutionTimeLimit (New-TimeSpan -Seconds 0)",
        "-AllowStartIfOnBatteries",
        "-DontStopIfGoingOnBatteries",
        "-MultipleInstances IgnoreNew",
        "-RestartCount 999",
        "-RunLevel Limited",
        "-m snow.hub --autostart",
        str(pythonw),
        f"-WorkingDirectory '{repo_root()}'",
        "Register-ScheduledTask",
        '-TaskName "Snow"',
        "-Force",
    ):
        assert needle in script, needle
    assert pythonw.is_absolute()


def test_install_never_asks_for_elevation_or_a_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _print_script("install-autostart", capsys)
    assert "Highest" not in script
    assert "New-Service" not in script
    assert "sc.exe" not in script


def test_uninstall_print_removes_the_task(capsys: pytest.CaptureFixture[str]) -> None:
    script = _print_script("uninstall-autostart", capsys)
    assert 'Unregister-ScheduledTask -TaskName "Snow" -Confirm:$false' in script


def test_print_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise AssertionError("--print must not start a process")

    monkeypatch.setattr(subprocess, "run", boom)
    _print_script("install-autostart", capsys)
    _print_script("uninstall-autostart", capsys)


def test_install_runs_powershell_noninteractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cli.main(["install-autostart"]) == 0
    assert cli.main(["uninstall-autostart"]) == 0
    assert [c[:4] for c in calls] == [
        ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    ] * 2
    assert "Register-ScheduledTask" in calls[0][4]
    assert "Unregister-ScheduledTask" in calls[1][4]


def test_install_reports_a_powershell_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "Access is denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cli.main(["install-autostart"]) == 1
    assert "Access is denied" in capsys.readouterr().err


# --- real hub processes ------------------------------------------------------------


def _write_config(snow_dirs: SnowDirs, workers: str = "") -> None:
    (snow_dirs.config / "snow.toml").write_text(
        f"[hub]\nallowed_origins = []\n{workers}", encoding="utf-8"
    )


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        parent = psutil.Process(proc.pid)
        victims = [*parent.children(recursive=True), parent]
    except psutil.NoSuchProcess:
        return
    for p in victims:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    proc.wait(10)


@pytest.fixture
def mutex_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A private mutex name so tests never collide with a real running Snow."""
    name = f"Local\\SnowHubTest{uuid.uuid4().hex}"
    monkeypatch.setenv("SNOW_HUB_MUTEX", name)
    return {**os.environ, "SNOW_HUB_MUTEX": name}


@pytest.fixture
def hubs() -> Iterator[list[subprocess.Popen[bytes]]]:
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for proc in started:
        _kill_tree(proc)


def _start_hub(
    hubs: list[subprocess.Popen[bytes]], env: dict[str, str], *args: str
) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "snow.hub", *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    hubs.append(proc)
    return proc


async def _wait_for_hub_json(
    snow_dirs: SnowDirs, proc: subprocess.Popen[bytes]
) -> None:
    hub_json = snow_dirs.data / "run" / "hub.json"
    deadline = time.monotonic() + 20
    while not hub_json.exists():
        assert proc.poll() is None, "hub exited early"
        assert time.monotonic() < deadline, "hub.json never appeared"
        await asyncio.sleep(0.1)


async def test_quit_from_the_hud_stops_everything_with_exit_code_zero(
    snow_dirs: SnowDirs,
    mutex_env: dict[str, str],
    hubs: list[subprocess.Popen[bytes]],
) -> None:
    sleeper = json.dumps(["{python}", "-c", "import time; time.sleep(600)"])
    _write_config(snow_dirs, f"[workers.brain]\ncommand = {sleeper}\n")
    hub = _start_hub(hubs, mutex_env)
    await _wait_for_hub_json(snow_dirs, hub)
    await asyncio.sleep(1)  # let the worker start
    children = psutil.Process(hub.pid).children(recursive=True)
    assert children, "the brain worker never started"

    client = HubClient(role="hud")
    runner = asyncio.create_task(client.run())
    try:
        async with asyncio.timeout(15):
            await client.connected.wait()
            await client.send_command(AppQuit())
        assert await asyncio.to_thread(hub.wait, 15) == 0
    finally:
        runner.cancel()
    await asyncio.sleep(0.5)
    assert not any(c.is_running() for c in children), "a worker survived Quit"
    assert not (snow_dirs.data / "run" / "hub.json").exists()


async def test_a_second_hub_says_it_is_already_running_and_exits_zero(
    snow_dirs: SnowDirs,
    mutex_env: dict[str, str],
    hubs: list[subprocess.Popen[bytes]],
) -> None:
    _write_config(snow_dirs)
    first = _start_hub(hubs, mutex_env)
    await _wait_for_hub_json(snow_dirs, first)
    second = _start_hub(hubs, mutex_env)
    out, _ = await asyncio.to_thread(second.communicate, None, 20)
    assert second.returncode == 0
    assert b"Snow is already running" in out
    assert first.poll() is None, "the first hub must keep running"


@pytest.mark.parametrize(
    ("flag", "expected"), [("--autostart", ["--autostart"]), ("", [])]
)
async def test_autostart_flag_reaches_the_hud_worker_only_when_given(
    snow_dirs: SnowDirs,
    mutex_env: dict[str, str],
    hubs: list[subprocess.Popen[bytes]],
    tmp_path: Path,
    flag: str,
    expected: list[str],
) -> None:
    out = tmp_path / "hud-args.jsonl"
    code = (
        "import json, sys; "
        "open(sys.argv[1], 'a').write(json.dumps(sys.argv[2:]) + chr(10))"
    )
    command = json.dumps(["{python}", "-c", code, str(out)])
    _write_config(snow_dirs, f"[workers.hud]\ncommand = {command}\n")
    hub = _start_hub(hubs, mutex_env, *([flag] if flag else []))
    await _wait_for_hub_json(snow_dirs, hub)
    deadline = time.monotonic() + 20
    while not out.exists():
        assert time.monotonic() < deadline, "the HUD worker never ran"
        await asyncio.sleep(0.1)
    first_launch = json.loads(out.read_text("utf-8").splitlines()[0])
    assert first_launch == expected
