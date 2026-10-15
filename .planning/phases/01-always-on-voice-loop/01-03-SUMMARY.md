---
phase: 01-always-on-voice-loop
plan: 03
subsystem: brain
tags: [openai-sdk, keyring, hubclient, config, streaming]

requires:
  - phase: 01-always-on-voice-loop/01-01
    provides: Hub, EventLog, event contracts, wire protocol
provides:
  - BrainWorker answering transcript.final with streamed reply.delta then one reply.final
  - HubClient shared by every worker and dev tool (hello, snapshot-first, backoff, heartbeat)
  - get_secret / Secret over Windows Credential Manager (keyring service "snow")
  - load_config and data/config/run directory helpers
  - config/models.toml and config/persona.toml, skeleton JSON logger
  - tests/conftest.py fixtures (memory_keyring, snow_dirs, hub, mock_provider, openai_sse)
affects: [01-06, 01-08, 01-11, 01-16]

commits: 1
plan_head_before: 119910d1e082bdb968d49d0f4eceecead716a39c
plan_head_after: 96c535ccf690c82f6a020983c6f414968127504a

actuals:
  tokens: 9500
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Config re-read every turn, so a models.toml edit applies with no restart"
    - "Handlers run as tasks off the HubClient receive loop so an LLM call never blocks it"
    - "Pydantic config models forbid extras, so no key field can be added to TOML"

key-files:
  created:
    - src/snow/config/settings.py
    - src/snow/config/secrets.py
    - src/snow/logging.py
    - src/snow/common/hubclient.py
    - src/snow/brain/config.py
    - src/snow/brain/worker.py
    - src/snow/brain/__main__.py
    - config/models.toml
    - config/persona.toml
    - tests/conftest.py
    - tests/test_skeleton_turn.py
  modified: []

key-decisions:
  - "Provider HTTP is mocked with httpx2.MockTransport injected by monkeypatching snow.brain.worker.AsyncOpenAI, because openai 3.29 runs on httpx2 and respx cannot patch it"
  - "Per-model params go to the request via extra_body (typed, accepts any key), with drop_params filtering them"
  - "A mid-stream error after the first token still publishes reply.final with the text so far; failure before the first token publishes nothing"

requirements-completed: [CORE-04, SAFE-09]

coverage:
  - id: D1
    description: "A dev line gets a streamed LLM reply from the first fast chain entry; transcript.final and reply.final are stored with provider and model recorded"
    requirement: CORE-04
    verification:
      - kind: integration
        ref: "tests/test_skeleton_turn.py#test_dev_line_gets_llm_reply_and_both_sides_are_durable"
        status: pass
    human_judgment: false
  - id: D2
    description: "Provider, base URL and model come only from models.toml; editing the model string changes the next request body"
    requirement: CORE-04
    verification:
      - kind: integration
        ref: "tests/test_skeleton_turn.py#test_dev_line_gets_llm_reply_and_both_sides_are_durable"
        status: pass
    human_judgment: false
  - id: D3
    description: "API key is read from keyring service snow at call time, never from env/TOML; Secret repr is masked"
    requirement: SAFE-09
    verification:
      - kind: unit
        ref: "tests/test_skeleton_turn.py#test_secret_repr_is_masked_and_comes_only_from_keyring"
        status: pass
    human_judgment: false
  - id: D4
    description: "A provider failure before the first token publishes no reply.final and logs only an error kind"
    verification:
      - kind: unit
        ref: "tests/test_skeleton_turn.py#test_provider_failure_before_first_token_publishes_no_reply"
        status: pass
    human_judgment: false

duration: 25min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 03: Brain Worker and Shared HubClient Summary

**A dev line is answered by a streamed reply from the config-chosen Groq fast model through the plain openai SDK, key from Credential Manager only, with both turn sides stored as durable events**

## Accomplishments
- Tracer slice proven end to end: `cmd.dev.say` -> hub -> `BrainWorker` -> provider -> `reply.delta`/`reply.final` -> SQLite and the dev client; event-log types filter to exactly `["transcript.final", "reply.final"]` with ascending seq, provider `groq` and model recorded in the reply row.
- CORE-04: editing `config/models.toml` changes the next request body (`test/other-model`) with no code change; models are re-read each turn.
- SAFE-09: `get_secret` uses `keyring.get_password("snow", ...)` and nothing else; `Secret` prints `Secret('***')`; config models forbid extras so no key field can exist in TOML.
- `HubClient`: Hello, snapshot-first, reconnect backoff 0.5 s doubling to 8 s (re-reading `hub.json` each attempt), 2 s heartbeat, unknown event types logged and skipped, handlers spawned as tasks.
- Verified: `uv run pytest -q` 10 passed (7 hub + 3 new), `ruff check` clean, `ruff format --check` clean, `pyright` strict 0 errors, litellm count 0 in uv.lock and pyproject.toml.

Tracer gate: `<verify>` commands re-run after the commit; tracer verified end to end (single-task plan, nothing to expand).

## Task Commits
1. **Task 1: Snow answers a typed line through the first fast provider** - `96c535c` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] respx cannot mock openai 3.29**
- **Found during:** Task 1 (first test run reached the real Groq API and got a 401)
- **Issue:** openai 3.29.0 uses `httpx2` (its own `DefaultAsyncHttpxClient` subclasses `httpx2.AsyncClient`); respx 0.23 only patches `httpx`.
- **Fix:** `tests/conftest.py` gains `MockProvider` and fixture `mock_provider`, which monkeypatches `snow.brain.worker.AsyncOpenAI` to inject `httpx2.MockTransport` (fresh client per call because the worker closes it). `openai_sse` returns an `httpx2.Response`. Test asserts the request URL, Authorization header and body model the same way the plan intended. respx stays in the dev group, unused. `httpx2` is imported by tests as a transitive dependency of openai, not added to pyproject.toml.
- **Files modified:** tests/conftest.py, tests/test_skeleton_turn.py
- **Committed in:** 96c535c

**2. [Rule 2 - Missing Critical] Extra tests beyond the plan's single test**
- Added a provider-500 test (no `reply.final` published, one request, `max_retries=0` honoured) covering the plan's recalled edge case, plus a config validator rejecting chain entries that name an unknown provider.

---

**Total deviations:** 1 blocking (test-side), 1 small addition. No changes to pyproject.toml, uv.lock, src/snow/contracts or src/snow/hub.

## Issues Encountered
- Plan said `Hub(event_log, allowed_origins=[], run_dir=...)`; used as-is. The existing `tests/test_hub_roundtrip.py` defines its own local `hub` fixture which shadows the new conftest `hub` fixture; both pass.

## Known Stubs
- `config/persona.toml` is a short placeholder prompt (plan 01-16 replaces it); `config/models.toml` has only Groq `fast` (plan 01-08 fills every provider and role). Both are intentional per the plan.
- `snow.logging` is stdlib JSON lines without redaction until plan 01-11.
- `HubClient._send` drops messages while disconnected (marked `shortcut:` in code).

## Threat Flags
None. T-01-03 mitigations are implemented as planned; T-01-SC: no new packages.

## Next Phase Readiness
- Plan 01-06 can launch `python -m snow.brain` (it reads `SNOW_HUB_URL`/`SNOW_TOKEN` or `run/hub.json`) and make the dev command exit non-zero on no reply; plan 01-08 replaces `_pick` with the real chain and records `llm.call` errors.

## Self-Check: PASSED
- All 11 created source/config/test files exist; commit `96c535c` is an ancestor of HEAD.
- pytest 10 passed, ruff and pyright clean, `max_retries=0` and `get_secret(` in worker.py, `keyring.get_password` in secrets.py, no `os.environ` in secrets.py, no key-like strings in models.toml.

---
*Phase: 01-always-on-voice-loop*
*Completed: 2026-10-16*
