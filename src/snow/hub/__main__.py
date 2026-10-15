"""`python -m snow.hub` / `snow run`: the hub and its supervised workers (CORE-02).

The hub is a per-user process, never a Windows Service: Session 0 has no microphone or
desktop (D-40). The supervisor restarts crashed or hung workers; all children live in a
Job Object so none outlives the hub.
"""

import asyncio
import contextlib
import json
import logging
import os
import sys

from pydantic import BaseModel, ConfigDict, Field

from snow.config.settings import data_dir, load_config, run_dir
from snow.hub.eventlog import EventLog
from snow.hub.jobobject import JobHandle
from snow.hub.server import Hub
from snow.hub.supervisor import Supervisor, WorkerSpec, scrub_env
from snow.logging import configure

__all__ = ["main", "scrub_env"]

log = logging.getLogger("snow.hub")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HubSettings(_Strict):
    allowed_origins: list[str] = Field(default_factory=list[str])
    retention_days: int = 30


class SnowConfig(_Strict):
    hub: HubSettings = HubSettings()
    workers: dict[str, WorkerSpec] = Field(default_factory=dict[str, WorkerSpec])


async def _run() -> None:
    config = load_config("snow.toml", SnowConfig)
    event_log = EventLog(data_dir() / "data" / "snow.db")
    hub = Hub(event_log, allowed_origins=config.hub.allowed_origins, run_dir=run_dir())
    await hub.start()
    hub.report_event_log()
    token = str(json.loads((run_dir() / "hub.json").read_text("utf-8"))["token"])
    env = scrub_env(dict(os.environ), f"ws://127.0.0.1:{hub.port}", token)
    log.info("hub_started port=%d", hub.port)
    job: JobHandle | None = None
    if sys.platform == "win32":
        from snow.hub.jobobject import create_kill_on_close_job  # noqa: PLC0415

        job = create_kill_on_close_job()
    supervisor = Supervisor(config.workers, hub, job, env=env)
    hub.on_kill = supervisor.kill
    supervisor.start()
    try:
        await hub.quit_requested.wait()
        log.info("hub_quitting")
    finally:
        await supervisor.stop_all()
        await hub.stop()
        event_log.close()
        if job is not None:  # pyright: ignore[reportUnnecessaryComparison]
            job.close()


def main() -> int:
    configure("hub")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
