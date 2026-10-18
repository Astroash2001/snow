"""Supervisor: restart policy on a fake clock, plus real crash, kill and job tests."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import psutil
import pytest

from snow.config.settings import load_config
from snow.contracts.events import Event, HealthSubsystem, WorkerExited, WorkerStarted
from snow.hub.__main__ import SnowConfig
from snow.hub.supervisor import TICK_S, Supervisor, WorkerSpec, scrub_env
from tests.conftest import HubHandle


class FakeProc:
    _pids = iter(range(5000, 10**6))

    def __init__(self) -> None:
        self.pid = next(self._pids)
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code

    def kill(self) -> None:
        self.code = -9

    terminate = kill


class FakeHub:
    def __init__(self) -> None:
        self.heartbeats: dict[str, float] = {}
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, kind)]

    def health(self, name: str) -> list[tuple[str, str | None]]:
        return [
            (e.status, e.detail) for e in self.of(HealthSubsystem) if e.name == name
        ]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def _never(_: float) -> None:
    await asyncio.Event().wait()


class Rig:
    """Supervisor over fake processes; the test drives `tick()` by hand."""

    def __init__(self, workers: tuple[str, ...] = ("brain",)) -> None:
        self.hub = FakeHub()
        self.clock = Clock()
        self.procs: list[FakeProc] = []
        self.argvs: list[list[str]] = []

        def launch(name: str, argv: list[str], env: Mapping[str, str]) -> Any:
            self.argvs.append(argv)
            self.procs.append(FakeProc())
            return self.procs[-1]

        specs = {n: WorkerSpec(command=["x", n]) for n in workers}
        self.sup = Supervisor(
            specs,
            self.hub,
            None,
            self.clock,
            _never,
            env={},
            launch=launch,
            jitter=lambda: 1.0,
        )

    @property
    def proc(self) -> FakeProc:
        return self.procs[-1]

    def beat(self, name: str = "brain") -> None:
        self.hub.heartbeats[name] = self.clock.t

    def advance(self, seconds: float) -> None:
        self.clock.t += seconds
        self.sup.tick()

    def idle(self, seconds: float) -> None:
        """Time passes one supervisor tick at a time with no heartbeats."""
        for _ in range(round(seconds / TICK_S)):
            self.advance(TICK_S)

    def run_for(self, seconds: float) -> None:
        """Time passes while the worker stays alive and keeps beating."""
        self.clock.t += seconds
        self.beat()
        self.sup.tick()

    def crash(self, code: int = 3) -> None:
        self.proc.code = code
        self.sup.tick()

    def spawned(self) -> int:
        return len(self.procs)

    def expect_restart_after(self, delay: float) -> None:
        before = self.spawned()
        self.advance(delay - 0.01)
        assert self.spawned() == before, f"restarted before {delay}s"
        self.advance(0.02)
        assert self.spawned() == before + 1, f"not restarted after {delay}s"
        self.beat()
        self.sup.tick()


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    r = Rig()
    r.sup.start()
    r.beat()
    r.sup.tick()
    yield r
    await r.sup.stop_all()


async def test_crash_is_reported_then_restarted_with_doubling_delay(rig: Rig) -> None:
    rig.crash(3)
    exited = rig.hub.of(WorkerExited)[0]
    assert (exited.worker, exited.cause, exited.exit_code) == ("brain", "crash", 3)
    rig.expect_restart_after(0.5)
    started = rig.hub.of(WorkerStarted)
    assert [s.restart_count for s in started] == [0, 1]
    for delay in (1, 2, 4):
        rig.crash(3)
        rig.expect_restart_after(delay)


async def test_delay_caps_at_30_seconds(rig: Rig) -> None:
    delays = [0.5, 1, 2, 4, 8, 16, 30, 30]
    for delay in delays:
        # 40 s runs: under the 60 s stable mark, and spaced to avoid the breaker
        rig.run_for(40)
        rig.crash(1)
        rig.expect_restart_after(delay)


async def test_stable_minute_resets_the_delay(rig: Rig) -> None:
    rig.crash()
    rig.expect_restart_after(0.5)
    rig.crash()
    rig.expect_restart_after(1)
    rig.run_for(61)
    rig.crash()
    rig.expect_restart_after(0.5)


TIMING = load_config("snow.toml", SnowConfig).supervisor


async def test_no_heartbeat_for_hang_after_is_a_hang(rig: Rig) -> None:
    rig.idle(TIMING.hang_after_s - TICK_S)
    assert rig.proc.code is None, "alive one tick before the limit"
    rig.beat()
    rig.idle(TIMING.hang_after_s - TICK_S)
    assert rig.proc.code is None, "a fresh heartbeat resets the timer"
    rig.idle(TICK_S * 2)
    assert rig.proc.code == -9
    rig.advance(0)
    assert rig.hub.of(WorkerExited)[-1].cause == "hang"
    rig.expect_restart_after(0.5)


async def test_slow_warning_comes_once_and_rearms_on_a_beat(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="snow.hub.supervisor")
    rig.idle(TIMING.slow_after_s - TICK_S)
    assert "worker_slow" not in caplog.text
    rig.idle(TICK_S * 2)
    rig.idle(TICK_S * 4)
    assert caplog.text.count("worker_slow") == 1
    assert rig.proc.code is None
    rig.beat()
    rig.idle(TICK_S)
    rig.idle(TIMING.slow_after_s + TICK_S)
    assert caplog.text.count("worker_slow") == 2


async def test_a_tick_gap_of_exactly_sleep_gap_is_not_a_resume(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="snow.hub.supervisor")
    rig.beat()
    rig.advance(TIMING.sleep_gap_s)
    assert "hub_resumed" not in caplog.text


async def test_a_resume_resets_heartbeats_and_kills_no_one(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="snow.hub.supervisor")
    rig.beat()
    rig.advance(TIMING.sleep_gap_s + 0.01)
    assert "hub_resumed" in caplog.text
    rig.beat()
    rig.advance(3600)  # laptop slept for an hour
    assert rig.proc.code is None
    assert rig.hub.heartbeats["brain"] == rig.clock.t
    # a worker that stays silent after the resume is still killed
    rig.idle(TIMING.hang_after_s - TICK_S)
    assert rig.proc.code is None
    rig.idle(TICK_S * 2)
    assert rig.proc.code == -9


async def test_supervised_workers_get_the_stall_dump_env_and_extras_do_not() -> None:
    envs: dict[str, Mapping[str, str]] = {}

    def launch(name: str, argv: list[str], env: Mapping[str, str]) -> Any:
        envs[name] = env
        return FakeProc()

    sup = Supervisor(
        {"brain": WorkerSpec(command=["x"]), "tool": WorkerSpec(command=["x"])},
        FakeHub(),
        None,
        env={"A": "1"},
        launch=launch,
        timing=TIMING,
    )
    sup.start()
    await sup.stop_all()
    assert envs["brain"] == {"A": "1", "SNOW_STALL_DUMP_S": f"{TIMING.slow_after_s:g}"}
    assert envs["tool"] == {"A": "1"}


async def test_stale_heartbeat_of_the_old_process_does_not_count(rig: Rig) -> None:
    rig.crash()
    rig.expect_restart_after(0.5)
    assert rig.hub.health("brain")[-1][0] == "running"  # the new process reported
    rig.crash()
    rig.advance(0.6)  # respawned; the old heartbeat was discarded at spawn
    rig.advance(0.1)
    assert rig.hub.health("brain")[-1][0] == "restarting"


async def test_five_exits_in_two_minutes_trip_the_breaker(rig: Rig) -> None:
    rig.crash()
    for delay in (0.5, 1, 2, 4):
        rig.expect_restart_after(delay)
        rig.crash()
    assert rig.hub.health("brain")[-1] == ("down", "Could not restart. See logs.")
    before = rig.spawned()
    rig.advance(59)
    assert rig.spawned() == before, "no spinning while the breaker is open"
    rig.advance(2)
    assert rig.spawned() == before + 1, "one retry per minute"
    assert rig.hub.health("brain")[-1][0] == "down", "stays Down until healthy"
    rig.crash()
    rig.advance(59)
    assert rig.spawned() == before + 1
    rig.advance(2)
    assert rig.spawned() == before + 2


async def test_health_goes_starting_running_restarting_running(rig: Rig) -> None:
    rig.crash()
    rig.expect_restart_after(0.5)
    assert rig.hub.health("brain") == [
        ("starting", None),
        ("running", None),
        ("restarting", "Snow is restarting it automatically."),
        ("running", None),
    ]


async def test_dev_kill_is_cause_killed_and_restarts(rig: Rig) -> None:
    assert rig.sup.kill("brain") is True
    rig.sup.tick()
    assert rig.hub.of(WorkerExited)[-1].cause == "killed"
    rig.expect_restart_after(0.5)
    assert rig.sup.kill("voice") is False


async def test_hud_restart_gets_the_restarted_flag() -> None:
    r = Rig(("hud",))
    r.sup.start()
    r.crash()
    r.expect_restart_after(0.5)
    assert "--restarted" not in r.argvs[0]
    assert r.argvs[1][-1] == "--restarted"
    await r.sup.stop_all()


async def test_stop_all_terminates_children_and_reports_quit(rig: Rig) -> None:
    await rig.sup.stop_all()
    assert rig.proc.code is not None
    assert rig.hub.of(WorkerExited)[-1].cause == "quit"
    rig.advance(60)  # a stopped supervisor never restarts anything
    assert rig.spawned() == 1


def test_scrub_env_is_the_one_in_the_supervisor() -> None:
    assert scrub_env({"A_KEY": "1", "B": "2"}, "ws://x", "t") == {
        "B": "2",
        "SNOW_HUB_URL": "ws://x",
        "SNOW_TOKEN": "t",
    }


# --- real processes ------------------------------------------------------------


@pytest.fixture
def reaper() -> Iterator[Callable[[int], None]]:
    """Kill any process this test started, even when an assertion fails."""
    pids: list[int] = []
    yield pids.append
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass


async def _wait_for(check: Callable[[], bool], limit_s: float = 30.0) -> None:
    deadline = time.monotonic() + limit_s
    while not check():
        assert time.monotonic() < deadline, "timed out waiting for the supervisor"
        await asyncio.sleep(0.1)


def _events(h: HubHandle, type_: str) -> list[dict[str, Any]]:
    return [json.loads(r["payload"]) for r in h.log.rows([type_])]


def _real_supervisor(
    h: HubHandle, role: str, extra_env: dict[str, str]
) -> tuple[Supervisor, Any]:
    from snow.hub.jobobject import create_kill_on_close_job

    env = scrub_env({**os.environ, **extra_env}, h.url, h.token)
    spec = WorkerSpec(command=["{python}", "tests/fixtures/fake_worker.py", role])
    job = create_kill_on_close_job()
    sup = Supervisor({role: spec}, h.hub, job, env=env)
    h.hub.on_kill = sup.kill
    return sup, job


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
async def test_real_crash_restarts_the_process(hub: HubHandle) -> None:
    sup, job = _real_supervisor(
        hub, "brain", {"FAKE_EXIT_AFTER_S": "0.5", "FAKE_EXIT_CODE": "3"}
    )
    sup.start()
    try:
        await _wait_for(lambda: len(_events(hub, "worker.started")) >= 2)
        exited = _events(hub, "worker.exited")[0]
        assert (exited["cause"], exited["exit_code"]) == ("crash", 3)
        assert _events(hub, "worker.started")[1]["restart_count"] == 1
    finally:
        await sup.stop_all()
        job.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
async def test_real_dev_kill_through_the_hub_restarts_and_reports_running(
    hub: HubHandle,
) -> None:
    from snow.common.hubclient import HubClient
    from snow.contracts.wire import DevKill

    sup, job = _real_supervisor(hub, "brain", {})
    sup.start()
    dev = HubClient(hub.url, hub.token, role="dev")
    runner = asyncio.create_task(dev.run())

    def statuses() -> list[str]:
        return [
            e["status"]
            for e in _events(hub, "health.subsystem")
            if e["name"] == "brain"
        ]

    try:
        await _wait_for(lambda: "running" in statuses())
        await dev.connected.wait()
        await dev.send_command(DevKill(worker="brain"))
        await _wait_for(lambda: statuses().count("running") >= 2)
        assert [e["cause"] for e in _events(hub, "worker.exited")] == ["killed"]
        assert statuses() == ["starting", "running", "restarting", "running"]
    finally:
        runner.cancel()
        await sup.stop_all()
        job.close()


# --- Job Object (T-01-26) ----------------------------------------------------

OWNER = """
import subprocess, sys, time
from snow.hub.jobobject import assign, create_kill_on_close_job
job = create_kill_on_close_job()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
assign(job, child)
print(child.pid, flush=True)
time.sleep(600)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_killing_the_job_owner_kills_its_child_within_two_seconds(
    tmp_path: Path, reaper: Callable[[int], None]
) -> None:
    script = tmp_path / "owner.py"
    script.write_text(OWNER, encoding="utf-8")
    owner = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script)], stdout=subprocess.PIPE, text=True
    )
    reaper(owner.pid)
    assert owner.stdout is not None
    child_pid = int(owner.stdout.readline())
    reaper(child_pid)
    assert psutil.pid_exists(child_pid)
    psutil.Process(owner.pid).kill()  # hard kill: no cleanup code runs
    owner.wait(10)
    deadline = time.monotonic() + 2
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid), "orphan survived its job owner"
