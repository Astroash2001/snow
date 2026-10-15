"""`snow install-autostart` / `snow uninstall-autostart`: the logon task (CORE-01).

The task runs as the interactive user with RunLevel Limited, never as a Windows Service
and never elevated (T-01-27). Task Scheduler's defaults would hurt a laptop daemon, so
each is overridden: no 3-day execution limit, start and keep running on battery
(Pitfall 9). Paths are absolute and the working directory explicit (Pitfall 8).
"""

import subprocess
import sys
from pathlib import Path

from snow.config.settings import repo_root

TASK_NAME = "Snow"
_USER = '"$env:USERDOMAIN\\$env:USERNAME"'


def _q(text: str) -> str:
    """PowerShell single-quoted literal: nothing inside is interpolated."""
    return "'" + text.replace("'", "''") + "'"


def _pythonw() -> str:
    return str(repo_root() / ".venv" / "Scripts" / "pythonw.exe")


def install_script() -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$action = New-ScheduledTaskAction -Execute {_q(_pythonw())}"
            " -Argument '-m snow.hub --autostart'"
            f" -WorkingDirectory {_q(str(repo_root()))}",
            f"$trigger = New-ScheduledTaskTrigger -AtLogOn -User {_USER}",
            f"$principal = New-ScheduledTaskPrincipal -UserId {_USER}"
            " -LogonType Interactive -RunLevel Limited",
            "$settings = New-ScheduledTaskSettingsSet -RestartCount 999"
            " -RestartInterval (New-TimeSpan -Minutes 1)"
            " -ExecutionTimeLimit (New-TimeSpan -Seconds 0)"
            " -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
            " -MultipleInstances IgnoreNew -StartWhenAvailable",
            f'Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $action'
            " -Trigger $trigger -Principal $principal -Settings $settings -Force"
            " | Out-Null",
        ]
    )


def uninstall_script() -> str:
    return (
        f'Unregister-ScheduledTask -TaskName "{TASK_NAME}" -Confirm:$false'
        " -ErrorAction SilentlyContinue"
    )


def _run(script: str, argv: list[str], done: str) -> int:
    if "--print" in argv:
        print(script)
        return 0
    result = subprocess.run(  # noqa: S603 - fixed program, script built from our own paths
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"snow: PowerShell failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print(done)
    return 0


def install(argv: list[str]) -> int:
    """Register the logon task (idempotent: `-Force` replaces an existing one)."""
    if "--print" not in argv and not Path(_pythonw()).exists():
        print("snow: run `uv sync` first; .venv\\Scripts\\pythonw.exe is missing")
        return 1
    return _run(install_script(), argv, "Snow will now start when you log on.")


def uninstall(argv: list[str]) -> int:
    """Remove the logon task; fine if it was never installed."""
    return _run(uninstall_script(), argv, "Snow will no longer start at logon.")
