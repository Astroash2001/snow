"""Process priority and Windows QoS for the processes that must keep real time.

Windows can classify a windowless background process as low QoS and, on battery,
schedule it on efficiency cores at a low clock speed. Snow's voice must keep real
time, so the voice worker and the hub opt out: power throttling off for execution
speed (HighQoS) and ABOVE_NORMAL priority. HIGH and REALTIME are never used: they can
starve the audio threads of other apps. Windows does not hand ABOVE_NORMAL down to
child processes, so the brain and the HUD are unaffected.

Verified against Microsoft Learn (PROCESS_INFORMATION_CLASS,
PROCESS_POWER_THROTTLING_STATE, SetProcessInformation) and processthreadsapi.h:
ProcessPowerThrottling is 4, the state struct is three ULONGs (Version, ControlMask,
StateMask), CURRENT_VERSION is 1, EXECUTION_SPEED is 0x1, and HighQoS is
ControlMask = EXECUTION_SPEED with StateMask = 0.
"""

import ctypes
import logging
import sys
from ctypes import wintypes

import psutil

log = logging.getLogger("snow.process")

PROCESS_POWER_THROTTLING = 4
THROTTLING_VERSION = 1
EXECUTION_SPEED = 0x1


class PowerThrottlingState(ctypes.Structure):
    _fields_ = (
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    )


def _kernel32() -> "ctypes.WinDLL":  # pyright: ignore[reportUnknownParameterType]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit types: without them the 64-bit pseudo-handle is truncated to a C int.
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    for name in ("SetProcessInformation", "GetProcessInformation"):
        fn = getattr(k32, name)
        fn.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        fn.restype = wintypes.BOOL
    return k32  # pyright: ignore[reportUnknownVariableType]


def raise_priority() -> bool:
    """Opt out of power throttling and go ABOVE_NORMAL; never raises."""
    if sys.platform != "win32":
        return False
    ok = True
    try:
        k32 = _kernel32()
        state = PowerThrottlingState(THROTTLING_VERSION, EXECUTION_SPEED, 0)
        # Only the current-process pseudo-handle is used: no handle to another process.
        if not k32.SetProcessInformation(
            k32.GetCurrentProcess(),
            PROCESS_POWER_THROTTLING,
            ctypes.byref(state),
            ctypes.sizeof(state),
        ):
            ok = False
            log.warning(
                "process_priority_failed step=qos winerror=%d", ctypes.get_last_error()
            )
    except (OSError, AttributeError) as e:
        ok = False
        log.warning("process_priority_failed step=qos kind=%s", type(e).__name__)
    try:
        psutil.Process().nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
    except (psutil.Error, OSError) as e:
        ok = False
        log.warning("process_priority_failed step=priority kind=%s", type(e).__name__)
    if ok:
        log.info("process_priority qos=high priority=above_normal")
    return ok


def read_throttling() -> tuple[int, int] | None:
    """(ControlMask, StateMask) as Windows reports them, or None if the call fails."""
    if sys.platform != "win32":
        return None
    k32 = _kernel32()
    state = PowerThrottlingState(THROTTLING_VERSION, 0, 0)
    if not k32.GetProcessInformation(
        k32.GetCurrentProcess(),
        PROCESS_POWER_THROTTLING,
        ctypes.byref(state),
        ctypes.sizeof(state),
    ):
        return None
    return state.ControlMask, state.StateMask
