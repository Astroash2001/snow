"""Job Object that kills every member when the hub's handle closes (CORE-02, T-01-26).

If the hub dies for any reason, Windows closes its job handle and terminates the voice,
brain and HUD processes with it, so no orphan keeps the microphone open. Nested jobs
are fine on Windows 8 and later, so a Task Scheduler job around the hub is no problem.
"""

import subprocess
from dataclasses import dataclass
from typing import Any

import win32api
import win32job

_ACCESS = 0x0100 | 0x0001  # PROCESS_SET_QUOTA | PROCESS_TERMINATE, all assignment needs


@dataclass
class JobHandle:
    handle: Any  # PyHANDLE; the pywin32 stubs type it as None

    def close(self) -> None:
        """Close the handle; with KILL_ON_JOB_CLOSE this terminates every member."""
        win32api.CloseHandle(self.handle)


def create_kill_on_close_job() -> JobHandle:
    kind: Any = win32job.JobObjectExtendedLimitInformation  # pyright: ignore[reportUnknownMemberType]
    handle: Any = win32job.CreateJobObject(None, "")  # pyright: ignore[reportUnknownMemberType]
    info: Any = win32job.QueryInformationJobObject(handle, kind)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    info["BasicLimitInformation"]["LimitFlags"] |= (
        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE  # pyright: ignore[reportUnknownMemberType]
    )
    win32job.SetInformationJobObject(handle, kind, info)  # pyright: ignore[reportUnknownMemberType]
    return JobHandle(handle)


def assign(job: JobHandle, popen: "subprocess.Popen[bytes]") -> None:
    """Put a freshly started child in the job.

    shortcut: a grandchild started before this call escapes the job; fine for our
    workers, which spawn nothing in their first milliseconds.
    """
    proc = win32api.OpenProcess(_ACCESS, False, popen.pid)  # pyright: ignore[reportUnknownMemberType]
    try:
        win32job.AssignProcessToJobObject(job.handle, proc)  # pyright: ignore[reportUnknownMemberType]
    finally:
        win32api.CloseHandle(proc)
