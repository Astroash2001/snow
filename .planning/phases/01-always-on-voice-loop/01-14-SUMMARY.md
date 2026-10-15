---
phase: 01-always-on-voice-loop
plan: 14
subsystem: infra
tags: [supervisor, job-object, task-scheduler, autostart, heartbeat, backoff, retention, pywin32]

requires:
  - phase: 01-always-on-voice-loop
    provides: "Hub, EventLog, Projection/Snapshot, command role matrix, env scrub and launcher (plans 01-01, 01-04, 01-06)"
provides:
  - "Supervisor: spawn, heartbeat hang watch, 0.5 s to 30 s jittered backoff, crash-loop breaker, dev kill, stop_all"
  - "Job Object with KILL_ON_JOB_CLOSE so no worker outlives the hub"
  - "snow install-autostart / uninstall-autostart (Task Scheduler logon task, RunLevel Limited)"
  - "Single-instance hub (Local\\SnowHub mutex), clean quit with exit code 0, --autostart passed to the HUD"
  - "Subsystem health (workers, component rows, event_log) in the snapshot"
  - "EventLog.purge_content: 30-day transcript retention at start and every 24 h"
affects: [01-27 HUD shell (--autostart / --restarted flags), 01-11 logging, phase verification]

actuals:
  tokens: 30000
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Injectable clock/sleep/launcher/jitter so restart policy is tested on a fake clock, with real subprocess tests for crash, kill and the Job Object"
    - "Hub.heartbeats (monotonic last sign of life per role) is the supervisor's only liveness input"

key-files:
  created:
    - src/snow/hub/supervisor.py
    - src/snow/hub/jobobject.py
    - src/snow/hub/autostart.py
    - tests/fixtures/fake_worker.py
    - tests/hub/test_supervisor.py
    - tests/hub/test_health.py
    - tests/hub/test_autostart.py
    - tests/hub/test_retention.py
  modified:
    - src/snow/hub/__main__.py
    - src/snow/hub/server.py
    - src/snow/hub/projections.py
    - src/snow/hub/eventlog.py

key-decisions:
  - "Worker names outside voice/brain/hud (the test_cli env-dump helper) are launched once and never supervised, because worker.* events only allow the three real workers"
  - "A breaker retry keeps the row Down until a heartbeat proves it healthy, so the HUD does not flicker Down/Restarting every minute"
  - "event_log health row is published by the entry point (Hub.report_event_log), not inside Hub.start(), so the many hub tests that assert an empty log keep working"
  - "SNOW_HUB_MUTEX env var overrides the mutex name so tests can run a hub beside a real Snow"
  - "Hub.publish is now public (was _publish); the supervisor emits through it"

patterns-established:
  - "Supervisor.tick() is synchronous and clock-driven; the async loop only calls it every 250 ms"

requirements-completed: [CORE-01, CORE-02, QUAL-03]

duration: 55min
completed: 2026-10-16
status: complete
plan_head_before: 72d4282e3d69e0322d788ec00438b4f133f13e10
plan_head_after: 0ce28eab19705c2792ff0a32bcbf212aee12bcb7
commits: 3
---

# Phase 1 Plan 14: Supervisor, Autostart and Retention Summary

**Per-worker supervisor with heartbeat hang detection, jittered backoff and a crash-loop breaker inside a kill-on-close Job Object, plus a Task Scheduler logon task, single-instance hub, clean quit and 30-day transcript purge.**

## Accomplishments

- Killed, crashed or hung voice/brain/HUD workers come back by themselves: `worker.exited` (cause crash, hang or killed) then `worker.started(restart_count=n)`, with the health row going Starting, Running, Restarting, Running. Delays are 0.5 s doubling to 30 s with plus or minus 20 % jitter, reset after 60 s stable.
- Six seconds with no heartbeat (voice and brain) kills and restarts the worker with cause `hang`. Heartbeats from a previous process are discarded at spawn, so a stale one cannot fake health.
- Five exits in 120 s open the breaker: row Down with "Could not restart. See logs." and one retry per 60 s, staying Down until the retry proves healthy.
- Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: a real-process test hard-kills the owner and the child is gone within 2 s (T-01-26).
- When a worker exits the projection marks that worker's component rows (wake_word, speech_to_text) Down with "Snow is restarting it automatically." until the worker reports again. The `event_log` row (owner hub) is Running after open and goes Down, unsaved but broadcast, if an append raises, then recovers.
- `snow install-autostart` builds a PowerShell script with `-AtLogOn`, `-RunLevel Limited`, `-ExecutionTimeLimit (New-TimeSpan -Seconds 0)`, battery flags, `-RestartCount 999`, `-MultipleInstances IgnoreNew`, absolute `.venv\Scripts\pythonw.exe` and `-m snow.hub --autostart`; `uninstall-autostart` unregisters. Both are idempotent and support `--print`. A parse-only test confirms both scripts are valid PowerShell.
- Hub takes the `Local\SnowHub` mutex (second hub prints "Snow is already running", exit 0), appends `--autostart` to the HUD command when launched with it, and on `cmd.app.quit` stops all workers and exits 0.
- `EventLog.purge_content` nulls `content` older than `retention_days` (default 30) at hub start and every 24 h; metadata rows stay and replay skips textless rows.

## Task Commits

1. **Task 1 (tracer): supervisor, Job Object, health** - `76bfa65` (feat)
2. **Task 2 RED: autostart, single instance, quit, retention tests** - `b6fa67b` (test)
3. **Task 2 GREEN: autostart, mutex, quit, purge** - `0ce28ea` (feat)

Tracer gate: Task 1 `<verify>` re-run end to end before expansion, passed (auto mode).

## Verification

- `uv run pytest tests -q`: 109 passed (58 in `tests/hub`). `uv run ruff check src tests` and `uv run pyright`: clean.
- Existing `tests/test_cli.py` launch smoke test (scrubbed env, unroutable provider) still passes unchanged; `scrub_env` is re-exported from `snow.hub.__main__`.
- Acceptance greps for both tasks pass (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, AssignProcessToJobObject, both health strings, -AtLogOn, -RunLevel Limited, ExecutionTimeLimit, --autostart, "Snow is already running", def purge_content).
- No leaked python or electron processes after the test run.

## Deviations from Plan

**1. [Rule 3 - Blocking] Unsupervised helper workers**
- **Found during:** Task 1
- **Issue:** `tests/test_cli.py` launches an `envdump` worker that exits at once; `worker.started`/`exited` only accept voice, brain, hud, so supervising it would raise and restart-loop.
- **Fix:** Config entries other than voice/brain/hud are launched once inside the Job Object and never restarted.
- **Files modified:** src/snow/hub/supervisor.py
- **Commit:** 76bfa65

**2. [Rule 1 - Bug] Hub.start() health row broke existing tests**
- **Found during:** Task 1
- **Issue:** Publishing the `event_log` durable row inside `Hub.start()` made nine existing hub tests (which assert an empty log) fail.
- **Fix:** Added public `Hub.report_event_log()`, called from `__main__` after `start()`.
- **Files modified:** src/snow/hub/server.py, src/snow/hub/__main__.py
- **Commit:** 76bfa65

**3. Test-only environment override.** `SNOW_HUB_MUTEX` overrides the mutex name so mutex tests do not collide with a real Snow. Also `Hub._publish` became public `publish`. Both within owned files.

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug), 1 small addition. **Impact:** none on scope; no contracts, cli.py, config, logging or pyproject edits were needed.

## Pending Human Checks (not performed, per instructions)

- **Task 1:** with `uv run snow run` active, `uv run snow dev kill brain`, `... voice`, then end electron.exe in Task Manager; each returns within seconds and HUD Subsystems rows show Restarting then Running; closing the hub terminal leaves no Snow python/electron process.
- **Task 2:** build the HUD, run the real `uv run snow install-autostart`, reboot, log in, say the wake phrase (proves keyring and workers work in the logon session, assumption A14), then choose Quit Snow from the tray (plan 01-27) and confirm Snow stays quit for 3 minutes (assumption A7).
- The real `install-autostart` and `uninstall-autostart` were never executed here; only `--print`, a captured PowerShell invocation and a parse-only syntax check.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model. T-01-26 (Job Object, tested), T-01-27 (RunLevel Limited, no service, asserted by test), T-01-28 (backoff, breaker, 60 s cadence, tested on fake clock), T-01-29 (purge, tested) are mitigated.

## Notes for Other Plans

- `--restarted` is appended to the HUD argv on every restart and `--autostart` on a logon launch; plan 01-27 must honour both.
- Known limits: a grandchild spawned before `AssignProcessToJobObject` returns would escape the job (commented `shortcut:` in jobobject.py). Replay of a purged row is skipped, so purged days show no transcript text after a hub restart (intended).
- At hub start, component rows replayed from today's log can still read Running until the worker reports; the supervisor's own worker row is accurate immediately.

## Self-Check: PASSED

- Created files exist: supervisor.py, jobobject.py, autostart.py, fake_worker.py, test_supervisor.py, test_health.py, test_autostart.py, test_retention.py.
- Commits 76bfa65, b6fa67b, 0ce28ea are on this branch.
