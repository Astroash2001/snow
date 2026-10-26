---
phase: quick-261026-nvh
plan: 01
subsystem: brain
tags: [llm-chain, cooldown, rate-limit, fallback]
requires: []
provides:
  - per-model cooldown for timeout and service_error in RateLimiter
affects: [src/snow/brain/limits.py, src/snow/brain/chain.py]
key-files:
  modified:
    - src/snow/brain/limits.py
    - src/snow/brain/chain.py
    - tests/brain/test_cooldown.py
    - tests/brain/test_acks.py
decisions:
  - "timeout and service_error cool (provider, model); 429, 401/403 and connection failures still cool the provider"
  - "Provider health row is cooling_down only while the provider-wide cooldown is live"
status: complete
commits: 2
plan_head_before: 7678e9cf1619fd98de4ec47b3b173c5555311f1f
plan_head_after: 2716bfda8cf8cb62399b8dcfc9612f63a2d14402
actuals:
  tokens: 9000
  tasks: 2
  commits: 2
requirements: [CORE-04, CORE-09, SAFE-12]
completed: 2026-10-26
---

# Phase quick-261026-nvh Plan 01: Per-model cooldown Summary

A first-token timeout or 5xx now cools down only that provider+model pair, so groq qwen is tried in the same turn when groq gpt-oss times out (closes UAT gap G-01-16).

## What changed

- `RateLimiter.record_failure(provider, entry, reason, headers, body)`: key is `(provider, entry.model)` for `timeout` and `service_error`, else the provider. Durations are unchanged. New `_live(key)` holds the expiry logic; `cooling_until` takes the later of the provider and model cooldown, `snapshot` reports the provider-wide one only.
- `LLMChain._record_failure` passes the entry and marks the provider row `cooling_down` only when the provider itself is cooling. The privacy check still runs before the cooling skip (SAFE-12).
- Tests: end-to-end `test_timeout_cools_only_that_model`, scope matrix, two-groq 429 test, privacy test parametrized over rate_limit and timeout.

## Deviations from Plan

**1. [Rule 1 - Bug] tests/brain/test_acks.py needed an update**
- **Found during:** Task 2 full gate
- **Issue:** `test_empty_pool_and_every_provider_down_is_silent` queued a single groq 500, relying on a 5xx cooling all of Groq. Now groq's second entry is also tried and hit an unrouted request.
- **Fix:** queue a 500 for each of groq's two entries.
- **Commit:** 2716bfd

## Known Stubs

None.

## Notes

- `uv run pytest tests --ignore=tests/voice` stops at `tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env` (error at setup, in the CLI hub launcher). Unrelated to the brain cooldown code; not investigated, left alone.

## Self-Check: PASSED

Commits 2a0ebee and 2716bfd exist; ruff check, ruff format --check, pyright and `pytest tests/brain` (116 passed) are clean.
