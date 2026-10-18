"""Supervisor: starts the voice, brain and HUD processes and heals them (CORE-02, D-40).

Policy (Pattern 5): a dead or hung worker is restarted with a delay of 0.5 s doubling to
30 s (plus or minus 20 % jitter, reset after 60 s stable). Five exits within two minutes
trip a breaker: the worker shows Down and is retried once a minute instead of spinning.
Health is published as `health.subsystem` events so the HUD shows every transition.

A worker that stops beating is warned about after `slow_after_s` (it then writes its
own Python stacks to its .err file) and killed after `hang_after_s`. A supervisor tick
gap above `sleep_gap_s` means the PC slept: heartbeats are reset instead of judged.
The values come from snow.toml [supervisor].
"""

import asyncio
import logging
import random
import subprocess
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, get_args

from pydantic import BaseModel, ConfigDict

from snow.config.settings import data_dir, repo_root
from snow.contracts.events import (
    Event,
    HealthSubsystem,
    Worker,
    WorkerExited,
    WorkerStarted,
)
from snow.hub.jobobject import JobHandle, assign

log = logging.getLogger("snow.hub.supervisor")

BACKOFF_START_S = 0.5
BACKOFF_MAX_S = 30.0
JITTER = 0.2
STABLE_S = 60.0
BREAKER_EXITS = 5
BREAKER_WINDOW_S = 120.0
BREAKER_RETRY_S = 60.0
BREAKER_DETAIL = "Could not restart. See logs."
# Same words the projection puts on a dead worker's component rows (test-guarded).
RESTARTING_DETAIL = "Snow is restarting it automatically."
TICK_S = 0.25
STOP_WAIT_S = 5.0

_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LABELS: dict[str, str] = {"voice": "Voice", "brain": "Brain", "hud": "HUD"}
_WATCHED = frozenset({"voice", "brain"})  # the HUD does not send heartbeats
_SUPERVISED: tuple[str, ...] = get_args(Worker)

Cause = Literal["crash", "hang", "killed", "quit"]
Status = Literal["running", "starting", "restarting", "down"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SupervisorConfig(_Strict):
    """Defaults mirror snow.toml [supervisor]; some tests omit that section."""

    slow_after_s: float = 6.0
    hang_after_s: float = 20.0
    sleep_gap_s: float = 3.0


class WorkerSpec(_Strict):
    command: list[str]
    enabled: bool = True


class HubLike(Protocol):
    """What the supervisor needs from the hub."""

    heartbeats: dict[str, float]

    def publish(self, event: Event) -> None: ...


Launcher = Callable[
    [str, list[str], Mapping[str, str]], "subprocess.Popen[bytes] | None"
]


def scrub_env(env: dict[str, str], hub_url: str, token: str) -> dict[str, str]:
    """Copy of `env` minus secret-looking variables, plus the hub address (T-01-55)."""
    clean = {
        k: v for k, v in env.items() if not any(w in k.upper() for w in _SECRET_WORDS)
    }
    clean["SNOW_HUB_URL"] = hub_url
    clean["SNOW_TOKEN"] = token
    return clean


def _argv(command: list[str]) -> list[str]:
    argv = [sys.executable if c == "{python}" else c for c in command]
    first = Path(argv[0])
    if not first.is_absolute() and ("/" in argv[0] or "\\" in argv[0]):
        argv[0] = str(repo_root() / first)
    return argv


def _launch(
    name: str, argv: list[str], env: Mapping[str, str]
) -> "subprocess.Popen[bytes] | None":
    try:
        # Worker stderr goes to a file so an import-time crash is diagnosable.
        logs = data_dir() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / f"{name}.err").open("ab") as err:
            return subprocess.Popen(  # noqa: S603 - argv comes from the user's own snow.toml
                argv,
                env=dict(env),
                cwd=repo_root(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                creationflags=_NO_WINDOW,
            )
    except OSError as e:
        log.error("worker_launch_failed worker=%s kind=%s", name, type(e).__name__)
        return None


def _jitter() -> float:
    return random.uniform(1 - JITTER, 1 + JITTER)  # noqa: S311 - spreads restarts, not security


@dataclass
class _State:
    name: Worker
    spec: WorkerSpec
    proc: "subprocess.Popen[bytes] | None" = None
    pid: int = 0
    spawns: int = 0
    backoff: float = BACKOFF_START_S
    started_at: float = 0.0
    next_spawn: float = 0.0
    cause: Cause | None = None
    exits: deque[float] = field(default_factory=deque[float])
    status: Status | None = None
    detail: str | None = None
    slow: bool = False


class Supervisor:
    def __init__(
        self,
        workers: Mapping[str, WorkerSpec],
        hub: HubLike,
        job: JobHandle | None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        *,
        env: Mapping[str, str],
        launch: Launcher = _launch,
        jitter: Callable[[], float] = _jitter,
        timing: SupervisorConfig | None = None,
    ) -> None:
        self._hub = hub
        self._job = job
        self._clock = clock
        self._sleep = sleep
        self._env = env
        self._launch = launch
        self._jitter = jitter
        self._timing = timing or SupervisorConfig()
        self._last_tick: float | None = None
        self._stopping = False
        self._task: asyncio.Task[None] | None = None
        self._states = {
            n: _State(name=n, spec=s)  # pyright: ignore[reportArgumentType]
            for n, s in workers.items()
            if s.enabled and n in _SUPERVISED
        }
        # Any other [workers.*] entry is a dev helper: started once, never restarted.
        self._extras = [
            (n, s) for n, s in workers.items() if s.enabled and n not in _SUPERVISED
        ]
        self._extra_procs: list[subprocess.Popen[bytes]] = []

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        for name, spec in self._extras:
            proc = self._launch(name, _argv(spec.command), self._env)
            if proc is not None:
                if self._job is not None:
                    assign(self._job, proc)
                self._extra_procs.append(proc)
        for state in self._states.values():
            self._spawn(state)
        self._task = asyncio.create_task(self._run())

    async def stop_all(self) -> None:
        """Terminate every child and wait up to 5 s (quit and shutdown)."""
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        live = [(s, s.proc) for s in self._states.values() if s.proc is not None]
        procs = [p for _, p in live] + self._extra_procs
        for p in procs:
            if p.poll() is None:
                p.terminate()
        deadline = time.monotonic() + STOP_WAIT_S
        while time.monotonic() < deadline and any(  # noqa: ASYNC110 - Popen has no awaitable wait
            p.poll() is None for p in procs
        ):
            await asyncio.sleep(0.05)
        for p in procs:
            if p.poll() is None:
                p.kill()
        for state, proc in live:
            self._hub.publish(
                WorkerExited(
                    ts_ns=time.time_ns(),
                    source="hub",
                    worker=state.name,
                    pid=state.pid,
                    exit_code=proc.poll(),
                    cause="quit",
                )
            )
            state.proc = None

    def kill(self, worker: str) -> bool:
        """`snow dev kill`: terminate a worker; the loop restarts it."""
        state = self._states.get(worker)  # pyright: ignore[reportArgumentType]
        if state is None or state.proc is None or state.proc.poll() is not None:
            return False
        state.cause = "killed"
        state.proc.kill()
        return True

    # --- the watch loop ------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("supervisor_tick_failed")  # keep supervising
            await self._sleep(TICK_S)

    def tick(self) -> None:
        if self._stopping:
            return
        now = self._clock()
        if (
            self._last_tick is not None
            and now - self._last_tick > self._timing.sleep_gap_s
        ):
            # The monotonic clock keeps counting through sleep, so after a resume
            # every heartbeat looks stale: forgive them once, kill no healthy worker.
            log.warning("hub_resumed gap_s=%.1f", now - self._last_tick)
            for name in self._hub.heartbeats:
                self._hub.heartbeats[name] = now
        self._last_tick = now
        for state in self._states.values():
            self._watch(state)

    def _watch(self, w: _State) -> None:
        now = self._clock()
        if w.proc is None:
            if now >= w.next_spawn:
                self._spawn(w)
            return
        code = w.proc.poll()
        if code is not None:
            self._on_exit(w, code)
            return
        if now - w.started_at >= STABLE_S:
            w.backoff = BACKOFF_START_S
        beat = self._hub.heartbeats.get(w.name)
        if beat is None:
            return
        if w.status != "running":
            self._health(w, "running")
        if w.name not in _WATCHED or w.cause is not None:
            return
        silent = now - beat
        if silent > self._timing.hang_after_s:
            log.warning("worker_hung worker=%s silent_s=%.1f", w.name, silent)
            w.cause = "hang"
            w.proc.kill()
        elif silent > self._timing.slow_after_s:
            if not w.slow:
                w.slow = True
                log.warning("worker_slow worker=%s silent_s=%.1f", w.name, silent)
        else:
            w.slow = False

    # --- transitions ---------------------------------------------------------

    def _spawn(self, w: _State) -> None:
        argv = _argv(w.spec.command)
        if w.name == "hud" and w.spawns:
            argv.append("--restarted")  # reopen without popping the dashboard
        self._hub.heartbeats.pop(w.name, None)  # only THIS process's beats count
        env = {**self._env, "SNOW_STALL_DUMP_S": f"{self._timing.slow_after_s:g}"}
        proc = self._launch(w.name, argv, env)
        w.started_at = self._clock()
        w.cause = None
        w.slow = False
        restart_count = w.spawns
        w.spawns += 1
        if proc is None:
            w.pid = 0
            w.proc = None
            self._record_exit(w, None, "crash")
            return
        if self._job is not None:
            try:
                assign(self._job, proc)
            except OSError as e:
                log.error(
                    "job_assign_failed worker=%s kind=%s", w.name, type(e).__name__
                )
        w.proc, w.pid = proc, proc.pid
        self._hub.publish(
            WorkerStarted(
                ts_ns=time.time_ns(),
                source="hub",
                worker=w.name,
                pid=proc.pid,
                restart_count=restart_count,
            )
        )
        log.info("worker_started worker=%s pid=%d", w.name, proc.pid)
        if restart_count == 0:
            self._health(w, "starting")
        elif w.status != "down":  # a breaker retry stays Down until proven healthy
            self._health(w, "restarting", RESTARTING_DETAIL)

    def _on_exit(self, w: _State, code: int) -> None:
        cause: Cause = w.cause or "crash"
        log.warning("worker_exited worker=%s code=%d cause=%s", w.name, code, cause)
        self._hub.publish(
            WorkerExited(
                ts_ns=time.time_ns(),
                source="hub",
                worker=w.name,
                pid=w.pid,
                exit_code=code,
                cause=cause,
            )
        )
        w.proc = None
        self._record_exit(w, code, cause)

    def _record_exit(self, w: _State, code: int | None, cause: Cause) -> None:
        now = self._clock()
        if code is None:  # launch failure: nothing exited, so no worker.exited event
            log.warning("worker_launch_failed_exit worker=%s cause=%s", w.name, cause)
        w.exits.append(now)
        while w.exits and now - w.exits[0] > BREAKER_WINDOW_S:
            w.exits.popleft()
        if len(w.exits) >= BREAKER_EXITS:
            w.next_spawn = now + BREAKER_RETRY_S
            self._health(w, "down", BREAKER_DETAIL)
            return
        w.next_spawn = now + w.backoff * self._jitter()
        w.backoff = min(w.backoff * 2, BACKOFF_MAX_S)
        self._health(w, "restarting", RESTARTING_DETAIL)

    def _health(self, w: _State, status: Status, detail: str | None = None) -> None:
        if (w.status, w.detail) == (status, detail):
            return
        w.status, w.detail = status, detail
        self._hub.publish(
            HealthSubsystem(
                ts_ns=time.time_ns(),
                source="hub",
                name=w.name,
                label=_LABELS[w.name],
                owner=w.name,
                status=status,
                detail=detail,
            )
        )
