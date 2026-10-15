---
phase: 01-always-on-voice-loop
plan: 04
subsystem: infra
tags: [pydantic, json-schema, websocket, event-catalog, projection, sqlite]

requires:
  - phase: 01-01
    provides: Hub, EventLog, Envelope, WireMessage, snapshot-first protocol
provides:
  - Complete Phase 1 event catalog (28 event types) and command set as Pydantic models
  - Full Snapshot and TranscriptRow models
  - Projection reducer (events -> client snapshot)
  - Hub snapshot-first with today's replay, persisted mute, command role matrix (4403)
  - snow.contracts.export with --check drift gate; committed JSON Schema and golden samples
affects: [01-03, 01-06, 01-07, 01-08, 01-09, 01-14]

commits: 3
plan_head_before: 119910d1e082bdb968d49d0f4eceecead716a39c
plan_head_after: b7ea68c8515b68c9ad4335cca157def0e7fa9d10

actuals:
  tokens: 21000
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Contract frozen as Pydantic models; JSON Schema and golden samples generated and drift-gated"
    - "Projection is a pure reducer; hub applies it to every published event and to today's replayed rows"
    - "Role matrix (COMMAND_ROLES) lives in the contract; hub closes forbidden commands with 4403"

key-files:
  created:
    - src/snow/hub/projections.py
    - src/snow/contracts/export.py
    - contracts/events.schema.json
    - contracts/samples/events.json
    - contracts/samples/conversation-12.jsonl
    - tests/hub/test_eventlog.py
    - tests/hub/test_projections.py
    - tests/hub/test_ws_security.py
    - tests/contracts/test_catalog.py
  modified:
    - src/snow/contracts/events.py
    - src/snow/contracts/wire.py
    - src/snow/hub/server.py
    - src/snow/hub/eventlog.py

key-decisions:
  - "Snapshot embeds the latest HealthSubsystem/HealthProvider/HealthRole/VoiceStatus/SttStatus event objects, so the HUD reads one shape for live and snapshot data"
  - "System transcript rows carry space-separated key=value facts in text plus system_event; the HUD owns the wording"
  - "Mute is restored from the state table after replay, so the persisted value always wins"
  - "Export --check compares line-ending-insensitively because git may check files out with CRLF"

patterns-established:
  - "EventLog.replay(since_ts_ns) rebuilds typed events from rows (content column folded back into its field); unknown types skipped"

requirements-completed: [CORE-03, VOIC-03]

duration: 40min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 04: Event Catalog, Snapshot Projection and Generated Contract Summary

**Full Phase 1 event catalog and command set frozen as Pydantic models, a Projection that gives every connecting client the current state first (mute persisted across restarts, role matrix closing forbidden commands with 4403), and a drift-gated JSON Schema plus golden samples including a 12-turn scripted stream**

## Accomplishments
- 28 event types, `Tone`, `ChainEntryStatus`, 5 commands and the full `Snapshot`; the exported schema contains every type.
- `Projection` builds presence, mode, mute, transcript rows (interrupted replies keep only the spoken text, empty replies add no row), health lists, voice/STT status and Cartesia characters since local midnight.
- Hub: sends the projected snapshot first, rebuilds it from today's durable rows on construction, persists `state['mute']` on every `mute.changed`, routes `cmd.mute.set` to the voice client or records it itself when none is connected, answers `cmd.snapshot`, closes forbidden commands with 4403.
- `python -m snow.contracts.export [--check]` regenerates `contracts/events.schema.json`, `samples/events.json` (one sample per event and command type plus a snapshot) and `samples/conversation-12.jsonl` (116 lines).
- Full suite: 38 tests pass; ruff and pyright strict clean; `export --check` exits 0.

## Task Commits
1. **Task 1 (tracer): catalog, projection, hub snapshot, mute persistence, role matrix** - `76cca7c` (feat)
2. **Task 2 RED: failing catalog freshness and hub security tests** - `8bca13f` (test)
3. **Task 2 GREEN: export, schema, samples** - `b7ea68c` (feat)

Tracer gate: `<verify>` (pytest on hub/roundtrip tests plus pyright) re-run after the commit and passed before expansion.

## TDD Gate (Task 2)
- RED: target `tests/contracts/test_catalog.py::test_committed_files_are_fresh` failed on its assertion (`export --check` exited non-zero because the module did not exist). The other five catalog tests failed with `FileNotFoundError` on the missing sample files. Semantic assessment: the freshness test failed for the planned reason; the sample-file tests are load failures by nature (the files are the output under test). The `test_ws_security.py` tests passed at RED because the behaviour they cover was implemented in Task 1 (the 4403 matrix); they are regression coverage, not RED evidence. The RED evidence classifier was not run (the plan is `type: execute`, not `type: tdd`).
- GREEN: `b7ea68c`. REFACTOR: none.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Compatibility] `TranscriptFinal.stt_source` defaults to `"dev"`**
- **Issue:** Plan 01-03 runs in parallel and builds `TranscriptFinal(text=...)` against the 01-01 shape. A required `stt_source` would break its merge.
- **Fix:** default `"dev"` (the hub's dev path also sets it explicitly). Real speech-to-text must set it; change to required once 01-03 and 01-09 have merged.
- **Files:** src/snow/contracts/events.py

**2. [Rule 3 - Blocking] Role-matrix close code changed from 4400 to 4403 for non-dev commands**
- 01-01 closed non-dev commands with 4400; the plan mandates 4403 for forbidden commands. No existing test depended on the old code.

**3. [Rule 2 - Missing] Added `EventLog.replay()`**
- Needed to rebuild the projection from durable rows; not named in the plan's file list but inside `eventlog.py`, already in scope for the hub.

No changes to pyproject.toml or uv.lock; no tests/conftest.py created.

## Decisions Made
See key-decisions. Also: a `reply.interrupted` with no matching snow row adds an interrupted snow row (so spoken text is never lost), and `Hub` replays in `__init__` rather than `start()` so tests can inspect state without a socket.

## Issues Encountered
None blocking.

## Known Stubs
None. `cmd.app.quit` and `cmd.dev.kill` are accepted and logged only; plan 01-14 implements them (as the plan states).

## Threat Flags
None beyond the plan's register. T-01-53 mitigated and covered by `tests/hub/test_ws_security.py::test_forbidden_command_closes_4403` (6 role/command pairs).

## Self-Check: PASSED
- Files verified present: events.py, wire.py, projections.py, export.py, server.py, contracts/events.schema.json, contracts/samples/events.json, contracts/samples/conversation-12.jsonl, four test modules.
- Commits `76cca7c`, `8bca13f`, `b7ea68c` are ancestors of HEAD.
- `uv run pytest -q` 38 passed; `uv run ruff check src tests` clean; `uv run pyright` 0 errors; `uv run python -m snow.contracts.export --check` exit 0.
