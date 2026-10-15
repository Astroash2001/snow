"""Subsystem health in the snapshot: worker exits, component rows, the event log row."""

import sqlite3
import time
from typing import Literal

import pytest

from snow.contracts.events import HealthSubsystem, MuteChanged, WorkerExited
from snow.contracts.wire import Snapshot
from snow.hub import projections, supervisor
from snow.hub.projections import Projection
from tests.conftest import HubHandle

Owner = Literal["hub", "voice", "brain", "hud"]
Status = Literal["running", "starting", "restarting", "down"]


def _row(name: str, owner: Owner, status: Status = "running") -> HealthSubsystem:
    return HealthSubsystem(
        ts_ns=1, source="hub", name=name, label=name, owner=owner, status=status
    )


def _by_name(snapshot: Snapshot) -> dict[str, HealthSubsystem]:
    return {s.name: s for s in snapshot.subsystems}


def test_worker_exit_marks_its_component_rows_down_until_it_reports_again() -> None:
    p = Projection()
    for row in (
        _row("voice", "voice"),
        _row("wake_word", "voice"),
        _row("speech_to_text", "voice"),
        _row("brain", "brain"),
        _row("event_log", "hub"),
    ):
        p.apply(row)
    p.apply(WorkerExited(ts_ns=2, source="hub", worker="voice", pid=1, cause="crash"))
    rows = _by_name(p.snapshot())
    for name in ("wake_word", "speech_to_text"):
        assert rows[name].status == "down"
        assert rows[name].detail == "Snow is restarting it automatically."
    # The worker's own row belongs to the supervisor; other owners are untouched.
    assert rows["voice"].status == "running"
    assert rows["brain"].status == "running"
    assert rows["event_log"].status == "running"
    p.apply(_row("wake_word", "voice"))
    assert _by_name(p.snapshot())["wake_word"].status == "running"


async def test_event_log_row_is_running_after_the_database_opens(
    hub: HubHandle,
) -> None:
    hub.hub.report_event_log()
    rows = _by_name(hub.hub._projection.snapshot())  # noqa: SLF001
    assert rows["event_log"].status == "running"
    assert rows["event_log"].owner == "hub"
    assert rows["event_log"].label == "Event log"


async def test_event_log_row_goes_down_when_an_append_raises_and_recovers(
    hub: HubHandle, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_append = hub.log.append

    def boom(_: object) -> int:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(hub.log, "append", boom)
    event = MuteChanged(ts_ns=time.time_ns(), source="hub", muted=True, by="hud")
    hub.hub.publish(event)  # must not raise: Snow keeps running
    row = _by_name(hub.hub._projection.snapshot())["event_log"]  # noqa: SLF001
    assert row.status == "down"
    assert row.detail == "Could not save events. See logs."

    monkeypatch.setattr(hub.log, "append", real_append)
    hub.hub.publish(event)
    row = _by_name(hub.hub._projection.snapshot())["event_log"]  # noqa: SLF001
    assert row.status == "running"


def test_supervisor_and_projection_use_the_same_restarting_words() -> None:
    assert supervisor.RESTARTING_DETAIL == projections.RESTARTING_DETAIL
