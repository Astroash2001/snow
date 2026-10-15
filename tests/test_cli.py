"""CLI dispatch and the real hub launch (CORE-01, CORE-03, T-01-55).

SAFETY: the launched brain subprocess reads the REAL Windows Credential Manager and the
launcher scrubs PYTHON_KEYRING_BACKEND, so no fake keyring can reach it. The temp
models.toml therefore points every provider at http://127.0.0.1:9/v1 (nothing listens
there), so no key the user has stored can ever be sent to a real provider.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest

from snow import cli
from snow.common.hubclient import HubClient
from snow.contracts.events import Event, Heartbeat, TranscriptFinal
from snow.contracts.wire import DevSay
from snow.hub.__main__ import scrub_env
from tests.conftest import SnowDirs

ENVDUMP = (
    "import json, os, sys; open(sys.argv[1], 'w').write(json.dumps(sorted(os.environ)))"
)


def test_help_lists_phase_1_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in ("run", "setup", "dev say", "dev kill", "dev inject-wav"):
        assert name in out


def test_missing_module_is_not_available_in_this_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(cli.COMMANDS, "ghost", "snow.no_such_module:main")
    assert cli.main(["ghost"]) == 2
    assert "snow: 'ghost' is not available in this build" in capsys.readouterr().err


def test_dispatch_passes_remaining_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("snow.devtools.say", lambda argv: calls.append(argv) or 0)
    assert cli.main(["dev", "say", "hi", "--timeout", "1"]) == 0
    assert calls == [["hi", "--timeout", "1"]]


def test_scrub_env_removes_secret_names_and_adds_hub_address() -> None:
    env = scrub_env(
        {
            "PATH": "p",
            "Api_Key": "1",
            "X_TOKEN": "2",
            "MY_SECRET": "3",
            "DB_PASSWORD": "4",
        },
        "ws://127.0.0.1:1",
        "tok",
    )
    assert env == {"PATH": "p", "SNOW_HUB_URL": "ws://127.0.0.1:1", "SNOW_TOKEN": "tok"}


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
def launched_hub(snow_dirs: SnowDirs, tmp_path: Path) -> Iterator[list[str]]:
    """Real hub process with brain and env-dump workers; yields the dumped env names."""
    envdump = tmp_path / "env.json"
    worker = json.dumps(["{python}", "-c", ENVDUMP, str(envdump)])
    (snow_dirs.config / "snow.toml").write_text(
        "[hub]\nallowed_origins = []\n"
        '[workers.brain]\ncommand = ["{python}", "-m", "snow.brain"]\n'
        f"[workers.envdump]\ncommand = {worker}\n",
        encoding="utf-8",
    )
    models = snow_dirs.config / "models.toml"
    models.write_text(
        re.sub(
            r'base_url = ".*"',
            'base_url = "http://127.0.0.1:9/v1"',
            models.read_text("utf-8"),
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "FAKE_API_KEY": "leak-1", "SOME_SECRET": "leak-2"}
    hub = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "snow.hub"], env=env, stdout=subprocess.DEVNULL
    )
    try:
        hub_json = snow_dirs.data / "run" / "hub.json"
        deadline = time.monotonic() + 20
        while not hub_json.exists():
            assert hub.poll() is None, "hub exited early"
            assert time.monotonic() < deadline, "hub.json never appeared"
            time.sleep(0.1)
        while not envdump.exists():
            assert time.monotonic() < deadline, "env dump never written"
            time.sleep(0.1)
        yield json.loads(envdump.read_text("utf-8"))
    finally:
        _kill_tree(hub)


async def test_hub_launches_workers_with_scrubbed_env(launched_hub: list[str]) -> None:
    inbox: asyncio.Queue[Event] = asyncio.Queue()

    async def collect(ev: Event) -> None:
        inbox.put_nowait(ev)

    dev = HubClient(role="dev", on_event=collect)
    runner = asyncio.create_task(dev.run())
    try:
        async with asyncio.timeout(15):
            await dev.connected.wait()
            await dev.send_command(DevSay(text="ping"))
            saw_echo = saw_brain = False
            while not (saw_echo and saw_brain):
                ev = await inbox.get()
                saw_echo |= isinstance(ev, TranscriptFinal) and ev.text == "ping"
                saw_brain |= isinstance(ev, Heartbeat) and ev.worker == "brain"
        names = launched_hub
        assert "SNOW_HUB_URL" in names
        assert "SNOW_TOKEN" in names
        assert "FAKE_API_KEY" not in names
        assert "SOME_SECRET" not in names

        # No usable provider (unroutable base_url): `snow dev say` gives up with exit 1.
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "snow.cli", "dev", "say", "ping", "--timeout", "2"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 1
        assert "no reply" in result.stderr
    finally:
        runner.cancel()
