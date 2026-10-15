"""`python -m snow.hub` / `snow run`: start the hub and its workers (CORE-01, CORE-03).

The hub is a per-user process, never a Windows Service: Session 0 has no microphone or
desktop (D-40). Plan 01-14 replaces this launcher with the supervisor and a Job Object.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from snow.config.settings import data_dir, load_config, repo_root, run_dir
from snow.hub.eventlog import EventLog
from snow.hub.server import Hub
from snow.logging import configure

log = logging.getLogger("snow.hub")

_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_POLL_S = 1.0
_TERMINATE_WAIT_S = 3.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HubSettings(_Strict):
    allowed_origins: list[str] = Field(default_factory=list[str])
    retention_days: int = 30


class WorkerSpec(_Strict):
    command: list[str]
    enabled: bool = True


class SnowConfig(_Strict):
    hub: HubSettings = HubSettings()
    workers: dict[str, WorkerSpec] = Field(default_factory=dict[str, WorkerSpec])


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
    name: str, spec: WorkerSpec, env: dict[str, str]
) -> subprocess.Popen[bytes] | None:
    try:
        # Worker stderr goes to a file so an import-time crash is diagnosable.
        with (data_dir() / "logs" / f"{name}.err").open("ab") as err:
            return subprocess.Popen(  # noqa: S603 - argv comes from the user's own snow.toml
                _argv(spec.command),
                env=env,
                cwd=repo_root(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
                creationflags=_NO_WINDOW,
            )
    except OSError as e:
        log.error("worker_launch_failed worker=%s kind=%s", name, type(e).__name__)
        return None


async def _run() -> None:
    config = load_config("snow.toml", SnowConfig)
    event_log = EventLog(data_dir() / "data" / "snow.db")
    hub = Hub(event_log, allowed_origins=config.hub.allowed_origins, run_dir=run_dir())
    await hub.start()
    token = str(json.loads((run_dir() / "hub.json").read_text("utf-8"))["token"])
    env = scrub_env(dict(os.environ), f"ws://127.0.0.1:{hub.port}", token)
    log.info("hub_started port=%d", hub.port)
    procs: dict[str, subprocess.Popen[bytes]] = {}
    for name, spec in config.workers.items():
        if spec.enabled and (proc := _launch(name, spec, env)) is not None:
            procs[name] = proc
            log.info("worker_started worker=%s pid=%d", name, proc.pid)
    try:
        while True:
            await asyncio.sleep(_POLL_S)
            for name, proc in list(procs.items()):
                if (code := proc.poll()) is not None:
                    log.warning("worker_exited worker=%s code=%d", name, code)
                    del procs[name]
    finally:
        for proc in procs.values():
            proc.terminate()
        for proc in procs.values():
            try:
                proc.wait(_TERMINATE_WAIT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
        await hub.stop()
        event_log.close()


def main() -> int:
    configure("hub")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
