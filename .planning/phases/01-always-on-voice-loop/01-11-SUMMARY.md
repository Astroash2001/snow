---
phase: 01-always-on-voice-loop
plan: 11
subsystem: security
tags: [secrets, keyring, structlog, redaction, loguru, canary]
requires:
  - phase: 01-03
    provides: Secret/get_secret, skeleton logger, hub and brain worker
  - phase: 01-06
    provides: "snow" CLI dispatch with a `setup` entry
  - phase: 01-08
    provides: LLMChain fallback used by the canary turn
provides:
  - "`snow setup` (--status, --only, --clear) with hidden key entry into Windows Credential Manager"
  - "KeySpec, KNOWN_KEYS, set_secret, delete_secret, revealed_secret_values"
  - "snow.logging.configure(process) as redacting structlog JSON logging"
  - "Canary test proving no key or spoken text reaches logs, events, frames or config"
affects: [01-13, 01-14, hud, voice]
tech-stack:
  added: []
  patterns:
    - "Three-layer redaction: field name, key-shaped regex, exact match of every revealed secret"
    - "structlog ProcessorFormatter on a stdlib RotatingFileHandler so third-party loggers share redaction"
key-files:
  created:
    - src/snow/config/setup.py
    - tests/test_setup.py
    - tests/test_logging.py
    - tests/test_secrets_canary.py
  modified:
    - src/snow/config/secrets.py
    - src/snow/logging.py
key-decisions:
  - "Revealed-secret exact match ignores values shorter than 8 chars so a short test key cannot shred ordinary words"
  - "Extra key_name entries in models.toml are offered by `snow setup` with no prefix check"
patterns-established:
  - "Log event names, ids, kinds, durations; never transcript or reply text (module docstring policy)"
requirements-completed: [SAFE-09, QUAL-03]
status: complete
duration: 25min
completed: 2026-10-16
commits: 3
plan_head_before: 72d4282e3d69e0322d788ec00438b4f133f13e10
plan_head_after: a9826904cc33a4f869adadd7d17479b40fde81a6
actuals:
  tokens: 9000
  tasks: 2
  commits: 3
---

# Phase 1 Plan 11: Key setup and redacting logs Summary

**`snow setup` stores provider and Cartesia keys in Windows Credential Manager via hidden input, and every Snow process now writes redacted structlog JSON logs, proven leak-free by an end-to-end canary test.**

## Performance

- **Tasks:** 2 (Task 1 tracer, Task 2 TDD)
- **Commits:** 3 (feat, test RED, feat GREEN)
- **Verification:** 105 tests pass; ruff check/format and pyright (strict) clean

## Accomplishments

- `snow setup`: getpass prompts for the six known keys plus any extra `key_name` in models.toml; Enter skips (D-25); a wrong prefix warns naming only the expected prefix and asks y/N; `--status` prints `<Label>: configured|not configured` only; `--only` and `--clear` supported. The value is never echoed, printed or measured.
- `secrets.py`: `KeySpec`, `KNOWN_KEYS`, `set_secret`, `delete_secret`, and a registry of every value that left the keyring (`revealed_secret_values()`); `Secret` and `get_secret` unchanged for existing callers.
- `logging.configure(process)` (signature kept): structlog JSON with `timestamp`, `level`, `process`, `event`, `logger`; rotating file (5 MB x 5) under the data dir; stdlib loggers flow through the same redaction; tracebacks are rendered before redaction; openai/httpx/httpx2/httpcore/websockets pinned to WARNING.
- Loguru bridge: default sink removed, one WARNING+ sink forwards into the `pipecat` logger so Pipecat DEBUG context dumps never reach disk.
- Canary test: real hub, real BrainWorker, first provider answers 401 echoing the key, second succeeds; scans logs, all events columns, every WebSocket frame in both directions and every config file for the key and for the spoken text.

## Task Commits

1. **Task 1: snow setup** - `b8acf0d`
2. **Task 2 RED: failing log/canary tests** - `940b6f3`
3. **Task 2 GREEN: redacting logging** - `a982690`

## Deviations from Plan

**1. [Rule 3 - Blocking] respx replaced by httpx2 mock transport**
- The plan says respx; openai 3.29 runs on httpx2 which respx cannot patch, so the canary uses the existing `mock_provider` fixture (as instructed by the orchestrator).

**2. [Rule 2 - Missing coverage] Simulated careless log line in the canary**
- The real chain logs only error kinds, so the key would not reach a log anyway. The canary therefore also logs the echoed provider body and an exception traceback containing it through `snow.brain.chain`, proving the redactor itself holds if a future log line is careless.

Otherwise the plan was executed as written. No edits to cli.py, brain/*, hub/*, conftest.py, pyproject.toml or uv.lock.

## Pending for the user

- **Task 1 human-check (not performed by design):** run `uv run snow setup`, type real keys, then `uv run snow setup --status` and confirm the entries under "snow" in Windows Credential Manager. Automated tests only used the in-memory keyring.

## Known Stubs

None.

## Threat Flags

None. Mitigations T-01-13, T-01-14, T-01-15 implemented and tested; T-01-16 accepted per plan.

## Notes and limits

- "No transcript in logs" is enforced by convention plus the canary scan, not by a field-name filter; a future log call passing `text=` would be written. Add a name-based omit rule if that risk grows.
- The exact-match layer only knows secrets revealed or stored in the current process; shape regexes and field names cover the rest.

## Self-Check: PASSED

Files exist (setup.py, secrets.py, logging.py, three test files); commits b8acf0d, 940b6f3, a982690 are in HEAD ancestry.
