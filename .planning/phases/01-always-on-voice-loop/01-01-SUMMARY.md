---
phase: 01-always-on-voice-loop
plan: 01
subsystem: infra
tags: [uv, python-3.12, pydantic, websockets, sqlite, event-log, hub]

requires: []
provides:
  - uv project with every Phase 1 runtime dependency pinned once in a hash-locked uv.lock
  - Pydantic event envelope and first event types (transcript.final, reply.delta, reply.final, heartbeat)
  - Wire protocol (hello, snapshot-first, event, command) with close codes 4400 and 4401
  - Hub, a loopback-only authenticated WebSocket server with durable persistence and broadcast
  - EventLog, SQLite WAL store with numbered migrations and a state table
affects: [01-02, 01-03, 01-04, 01-05, 01-06, 01-09]

commits: 1
plan_head_before: 69fae051a8308f383f122131309586816035d2f5
plan_head_after: 6ebcbe5482c4357f4389a38ff4649fc056e4d6ec

actuals:
  tokens: 5400
  tasks: 1
  commits: 1

tech-stack:
  added: [openai 3.29.0, pydantic 2.14.1, websockets 17.2, keyring 25.7.0, structlog 26.1.0, sounddevice 0.5.6, openwakeword 0.6.0, pipecat-ai[silero] 1.12.0, kokoro-onnx 0.6.1, psutil 7.2.2, pywin32 312, pytest, pytest-asyncio, ruff 0.17.0, pyright 1.1.414]
  patterns:
    - "Snapshot-first, then live events, on every client connection"
    - "Durable events persisted (seq assigned) before broadcast; ephemeral events broadcast only"
    - "Speech text only in the events.content column, never in the JSON payload"
    - "Per-client bounded send queue so a slow client cannot stall the hub"

key-files:
  created:
    - pyproject.toml
    - uv.lock
    - .python-version
    - src/snow/contracts/events.py
    - src/snow/contracts/wire.py
    - src/snow/hub/server.py
    - src/snow/hub/eventlog.py
    - src/snow/hub/migrations/001_init.sql
    - tests/test_hub_roundtrip.py
  modified:
    - .gitignore

key-decisions:
  - "Per-package exclude-newer overrides for openai, pydantic, pydantic-core and ruff, because their exact pinned versions were published after the 2026-10-08 global cutoff"
  - "uv environments restricted to win32 (Windows 11 is the only host; openwakeword pulls a linux-only tflite-runtime with no cp312 wheel)"
  - "pytest --basetemp=.pytest_tmp because a stale ACL-locked %TEMP%/pytest-of-avina directory breaks tmp_path"
  - "Hub registers a client and snapshots last_seq with no await in between, via a per-client queue, so no event is lost between snapshot and live stream"

requirements-completed: [CORE-03]

coverage:
  - id: D1
    description: "A dev client sending cmd.dev.say makes the hub store a durable transcript.final in SQLite and broadcast it with its seq to every connected client, snapshot first"
    requirement: CORE-03
    verification:
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_dev_say_is_stored_and_broadcast"
        status: pass
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_late_client_snapshot_reports_last_seq"
        status: pass
    human_judgment: false
  - id: D2
    description: "Durable event rows carry type, source, ts_ns, correlation_id, risk_tier and a monotonic seq; speech text only in content; ephemeral events never written"
    requirement: CORE-03
    verification:
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_ephemeral_event_is_broadcast_not_stored"
        status: pass
    human_judgment: false
  - id: D3
    description: "Hub listens on 127.0.0.1 only, requires the 256-bit token in the first hello within 2 s, rejects web Origins, validates every message and enforces source equals role"
    verification:
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_wrong_token_closes_4401"
        status: pass
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_web_origin_rejected_with_403"
        status: pass
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_oversize_dev_say_closes_4400"
        status: pass
      - kind: integration
        ref: "tests/test_hub_roundtrip.py#test_event_source_must_match_role"
        status: pass
    human_judgment: false
  - id: D4
    description: "All shared Phase 1 pins live in one hash-locked uv.lock with delayed adoption; the four gated packages are not added"
    verification:
      - kind: other
        ref: "uv lock --check; grep -ci litellm uv.lock pyproject.toml prints 0"
        status: pass
    human_judgment: false

duration: 72min
completed: 2026-10-15
status: complete
---

# Phase 1 Plan 01: Hub and Durable Event Log Summary

**Loopback-only token-authenticated WebSocket hub that validates a typed dev line, persists it as a durable transcript.final in SQLite WAL and broadcasts it to every client after a snapshot, on a uv project with all Phase 1 dependencies pinned in one hash-locked lock file**

## Performance

- **Duration:** 72 min (most of it resolving and downloading the dependency set)
- **Started:** 2026-10-15T17:55:43Z
- **Completed:** 2026-10-15T19:07:42Z
- **Tasks:** 1
- **Files modified:** 14

## Accomplishments
- Tracer slice proven end to end: `cmd.dev.say` from a `dev` client becomes a durable `transcript.final` (seq 1, text only in `content`) and reaches a `hud` client; 7 tests pass, ruff and pyright strict are clean.
- Security controls from the threat register are implemented and tested: loopback bind, `token_hex(32)` hello within 2 s (4401), Host and Origin checks (403), `extra="forbid"` validation and 1 MiB frame cap (4400), source must equal role, DevSay capped at 2000 characters.
- `Hub(event_log, *, allowed_origins, run_dir)` and `hub.json` handoff (`port`, `token`, `pid`) are in place for plans 01-03 and 01-06; `EventLog` also exposes `last_seq()` used for the snapshot.

## Task Commits

1. **Task 1: dev line through loopback hub into the durable event log and back to every client** - `6ebcbe5` (feat)

**Plan metadata:** committed separately (docs: complete plan)

Tracer gate: `<verify>` re-run after the commit (pytest, ruff, pyright all clean); tracer verified end-to-end, expansion tasks not applicable (single-task plan).

## Files Created/Modified
- `pyproject.toml` - uv project, exact Phase 1 pins, ruff, pyright strict, pytest markers
- `uv.lock` - hash-locked resolution (110 packages, win32 only)
- `.python-version` - 3.12
- `.gitignore` - venv, caches, hud build output, models, pytest temp
- `src/snow/contracts/events.py` - Envelope and the first four event types, discriminated on `type`
- `src/snow/contracts/wire.py` - Hello, EventMsg, CommandMsg, DevSay, Snapshot, SnapshotMsg, WireMessage
- `src/snow/hub/eventlog.py` - SQLite WAL event log with numbered migrations and state table
- `src/snow/hub/migrations/001_init.sql` - events and state tables, indexes
- `src/snow/hub/server.py` - Hub: security checks, hello, snapshot, publish and broadcast
- `tests/test_hub_roundtrip.py` - 7 integration tests

## Decisions Made
- Per-package `exclude-newer-package` overrides (openai, pydantic, pydantic-core, ruff) keep the plan's exact pins resolvable while the global cutoff stays `2026-10-08T00:00:00Z`.
- `environments = ["sys_platform == 'win32'"]` makes the universal lock resolvable; Windows is the only supported host.
- Per-client queue plus a writer task: the snapshot is the first queue item and registration happens synchronously, so there is no snapshot/live gap and a slow client is dropped (close 1013) instead of stalling the hub.
- Invalid hello is closed 4400, missing/late hello and wrong token 4401.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Exact pins conflicted with the global exclude-newer cutoff**
- **Found during:** Task 1 (`uv lock`)
- **Issue:** openai 3.29.0, pydantic 2.14.1 (and its pinned pydantic-core 2.50.1) and ruff 0.17.0 were published 2026-10-09 to 2026-10-11, after `exclude-newer = "2026-10-08T00:00:00Z"`, so the lock was unsatisfiable.
- **Fix:** kept the global cutoff string required by the acceptance criteria and added `exclude-newer-package` overrides for those four packages (each is pinned `==`).
- **Files modified:** pyproject.toml
- **Verification:** `uv lock` resolves; `uv lock --check` exits 0
- **Committed in:** 6ebcbe5

**2. [Rule 3 - Blocking] Universal lock failed on linux-only tflite-runtime**
- **Found during:** Task 1 (`uv lock`)
- **Issue:** openwakeword 0.6.0 requires `tflite-runtime` on linux with no cp312 wheel, so a universal resolve fails.
- **Fix:** `[tool.uv] environments = ["sys_platform == 'win32'"]`.
- **Files modified:** pyproject.toml
- **Verification:** `uv lock` resolved 110 packages
- **Committed in:** 6ebcbe5

**3. [Rule 3 - Blocking] pytest tmp_path unusable**
- **Found during:** Task 1 (first test run)
- **Issue:** `C:\Users\avina\AppData\Local\Temp\pytest-of-avina` is a stale directory that denies access (WinError 5), so every `tmp_path` fixture errored.
- **Fix:** `--basetemp=.pytest_tmp` appended to `addopts`; `.pytest_tmp/` added to `.gitignore`.
- **Files modified:** pyproject.toml, .gitignore
- **Verification:** 7 tests pass
- **Committed in:** 6ebcbe5

**4. [Rule 2 - Missing Critical] Enforce role on commands and unexpected message kinds**
- **Found during:** Task 1 (hub intake)
- **Issue:** The plan did not say what happens when a non-dev role sends a command, or a client sends a Hello/Snapshot after the handshake.
- **Fix:** such messages close the socket with 4400 (`message not allowed`); also added `EventLog.last_seq()` and extra tests (late-client snapshot, spoofed source, web origin).
- **Files modified:** src/snow/hub/server.py, src/snow/hub/eventlog.py, tests/test_hub_roundtrip.py
- **Committed in:** 6ebcbe5

---

**Total deviations:** 4 auto-fixed (3 blocking, 1 missing critical)
**Impact on plan:** Config-only workarounds for lock resolution and a local temp-dir fault, plus a small hardening. No scope creep; acceptance criteria all pass.

## Issues Encountered
- Later plans that add or bump packages published after 2026-10-08 will hit the same `exclude-newer` filter and need an `exclude-newer-package` entry in pyproject.toml.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. `snow = "snow.cli:main"` points at a module that plan 01-06 creates (declared by the plan); `uv run snow` fails until then.

## Next Phase Readiness
- Plans 01-02 to 01-06 can import `snow.contracts`, `snow.hub.Hub` and `EventLog`; gated packages (pocket-tts, moonshine-voice, chatterbox-tts, livekit-wakeword) are still to be added by plan 01-02.
- `hub.json` handoff and close codes 4400/4401 are stable; plan 01-04 extends `Snapshot` and the event catalog without renaming existing names.
- Only the 7 default-marker tests ran; nothing is marked hardware or gpu yet.

## Self-Check: PASSED

- Created files verified present on disk; commit `6ebcbe5` is an ancestor of HEAD.
- Acceptance criteria re-run: pins present, `uv lock --check` exit 0, litellm count 0 in both files, `127.0.0.1` and `token_hex(32)` in server.py, `class SnapshotMsg` and `class DevSay` in wire.py, tests pass.
- Plan verification: `uv run pytest -x -q` 7 passed; `uv run ruff check src tests` clean; `uv run pyright` 0 errors.

---
*Phase: 01-always-on-voice-loop*
*Completed: 2026-10-15*
