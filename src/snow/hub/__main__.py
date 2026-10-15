"""`python -m snow.hub` / `snow run`: the hub and its supervised workers (CORE-01/02).

The hub is a per-user process, never a Windows Service: Session 0 has no microphone or
desktop (D-40). Task Scheduler starts it at logon with `--autostart` (plain `snow run`
omits the flag). Quit from the HUD ends it with exit code 0, so Task Scheduler (which
restarts only failed runs) leaves Snow quit until the next logon.
"""

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import sys
import time

from pydantic import BaseModel, ConfigDict, Field

from snow.config.settings import data_dir, load_config, run_dir
from snow.hub.eventlog import EventLog
from snow.hub.jobobject import JobHandle
from snow.hub.server import Hub
from snow.hub.supervisor import Supervisor, WorkerSpec, scrub_env
from snow.logging import configure

__all__ = ["main", "scrub_env"]

log = logging.getLogger("snow.hub")

MUTEX_NAME = r"Local\SnowHub"
RETENTION_EVERY_S = 24 * 3600
_NS_PER_DAY = 86_400 * 10**9


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HubSettings(_Strict):
    allowed_origins: list[str] = Field(default_factory=list[str])
    retention_days: int = 30


class SnowConfig(_Strict):
    hub: HubSettings = HubSettings()
    workers: dict[str, WorkerSpec] = Field(default_factory=dict[str, WorkerSpec])


def _acquire_single_instance() -> object | None:
    """Named mutex `Local\\SnowHub` (per logon session). None means another hub runs.

    The returned handle must stay referenced for the life of the process.
    """
    if sys.platform != "win32":
        return object()
    import win32api  # noqa: PLC0415 - Windows only
    import win32event  # noqa: PLC0415
    import winerror  # noqa: PLC0415

    # SNOW_HUB_MUTEX lets tests run a hub beside a real one.
    name = os.environ.get("SNOW_HUB_MUTEX", MUTEX_NAME)
    handle: object = win32event.CreateMutex(None, False, name)  # pyright: ignore[reportUnknownMemberType, reportArgumentType]
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:  # pyright: ignore[reportUnknownMemberType]
        return None
    return handle


async def _retention(event_log: EventLog, days: int) -> None:
    """Erase speech text older than `days` at start and every 24 h (D-19, T-01-29)."""
    while True:
        try:
            erased = event_log.purge_content(time.time_ns() - days * _NS_PER_DAY)
            log.info("retention_purge erased=%d", erased)
        except sqlite3.Error as e:  # try again tomorrow; never take the hub down
            log.error("retention_purge_failed kind=%s", type(e).__name__)
        await asyncio.sleep(RETENTION_EVERY_S)


async def _run(autostart: bool) -> None:
    config = load_config("snow.toml", SnowConfig)
    event_log = EventLog(data_dir() / "data" / "snow.db")
    hub = Hub(event_log, allowed_origins=config.hub.allowed_origins, run_dir=run_dir())
    await hub.start()
    hub.report_event_log()
    token = str(json.loads((run_dir() / "hub.json").read_text("utf-8"))["token"])
    env = scrub_env(dict(os.environ), f"ws://127.0.0.1:{hub.port}", token)
    log.info("hub_started port=%d autostart=%s", hub.port, autostart)
    workers = dict(config.workers)
    if autostart and "hud" in workers:
        # The shell then opens only the mini indicator (plan 01-27).
        hud = workers["hud"]
        extended = [*hud.command, "--autostart"]
        workers["hud"] = hud.model_copy(update={"command": extended})
    job: JobHandle | None = None
    if sys.platform == "win32":
        from snow.hub.jobobject import create_kill_on_close_job  # noqa: PLC0415

        job = create_kill_on_close_job()
    supervisor = Supervisor(workers, hub, job, env=env)
    hub.on_kill = supervisor.kill
    retention = asyncio.create_task(_retention(event_log, config.hub.retention_days))
    supervisor.start()
    try:
        await hub.quit_requested.wait()
        log.info("hub_quitting")
    finally:
        retention.cancel()
        await supervisor.stop_all()
        await hub.stop()
        event_log.close()
        if job is not None:  # pyright: ignore[reportUnnecessaryComparison]
            job.close()


def main(argv: list[str] | None = None) -> int:
    configure("hub")  # first: pythonw has no console to show a crash
    args = sys.argv[1:] if argv is None else argv
    mutex = _acquire_single_instance()
    if mutex is None:
        print("Snow is already running")
        return 0
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run("--autostart" in args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
