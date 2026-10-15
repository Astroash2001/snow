---
phase: 01-always-on-voice-loop
plan: 12
subsystem: brain
tags: [rate-limits, cooldown, free-tier, health, privacy-routing]

requires:
  - phase: 01-always-on-voice-loop/01-08
    provides: LLMChain, ProviderBoard, httpx2 route-table fixtures, health.provider rows
provides:
  - RateLimiter, CooldownDefaults, parse_duration, next_midnight (src/snow/brain/limits.py)
  - LLMChain(limiter=...) skipping cooling providers, recording failures and usage
  - health.provider requests_today / tokens_today / cooling_until_ns; cooling_down entry and role status
  - Optional [limits] table in models.toml (ModelsConfig.limits)
affects: [01-16, 01-17]

commits: 1
plan_head_before: 72d4282e3d69e0322d788ec00438b4f133f13e10
plan_head_after: 5c3065ebcc6e24366bf6d3f3abf861f1c3c0b8ad

actuals:
  tokens: 6500
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Cooldown is per provider, decided by the first usable signal: retry-after, Groq reset-* of the empty window, OpenRouter X-RateLimit-Reset (epoch ms), Google retryDelay, else a configured default"
    - "Privacy check runs before the cooling check, so a cooling trusted entry never promotes an untrusted one for private data"
    - "Limiter is optional on LLMChain (None keeps 01-08 behaviour); the worker builds one per process and shares it across the three role chains"

key-files:
  created:
    - src/snow/brain/limits.py
    - tests/brain/test_cooldown.py
  modified:
    - src/snow/brain/chain.py
    - src/snow/brain/config.py
    - src/snow/brain/worker.py
    - tests/test_skeleton_turn.py

key-decisions:
  - "Cooling is per provider, not per entry: a Groq 429 on gpt-oss also skips qwen on the same key, and a bad key now costs one call per turn instead of two (the 01-08 known risk)"
  - "Counters are per provider; an entry's daily_request_cap compares against the provider's shared requests_today"
  - "A served request is counted in _drain's finally, so cut-short (barge-in) and mid-stream-error replies still count, with tokens estimated as len(text)/4 when no usage chunk arrived"
  - "bad_key cools for rate_limit_s (60 s); config_error (400/404/422) starts no cooldown because it is entry-specific, not a provider limit"

requirements-completed: [CORE-09]

coverage:
  - id: D1
    description: "Cooldown length follows each provider's own signal: Groq retry-after / x-ratelimit-reset-*, OpenRouter X-RateLimit-Reset, Google retryDelay, Experiential key_daily_cap / insufficient_credits / gateway_overloaded, defaults 60 s (429) and 20 s (5xx, timeout, connection)"
    requirement: CORE-09
    verification:
      - kind: unit
        ref: "tests/brain/test_cooldown.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "A cooling provider is skipped without a request until the cooldown ends, then used again; one limiter is shared by all roles"
    requirement: CORE-09
    verification:
      - kind: integration
        ref: "tests/brain/test_cooldown.py#test_cooling_provider_is_skipped_then_returns"
        status: pass
      - kind: unit
        ref: "tests/brain/test_cooldown.py#test_worker_shares_one_limiter_across_roles"
        status: pass
    human_judgment: false
  - id: D3
    description: "requests_today and tokens_today reach health.provider (usage chunk, else len/4), reset at local midnight; daily_request_cap cools the entry until midnight"
    requirement: CORE-09
    verification:
      - kind: integration
        ref: "tests/brain/test_cooldown.py#test_counters_reach_health_rows_and_are_shared_across_roles"
        status: pass
      - kind: integration
        ref: "tests/brain/test_cooldown.py#test_daily_request_cap_skips_entry_until_midnight"
        status: pass
    human_judgment: false
  - id: D4
    description: "A cooling trusted provider never makes a private turn reach an untrusted one: next trusted entry serves, or PrivacyBlockedError with zero requests"
    requirement: CORE-09
    verification:
      - kind: integration
        ref: "tests/brain/test_cooldown.py#test_cooling_trusted_provider_never_promotes_untrusted"
        status: pass
      - kind: integration
        ref: "tests/brain/test_cooldown.py#test_only_untrusted_left_fails_closed_while_cooling"
        status: pass
    human_judgment: false

duration: 30min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 12: Free-Tier Cooldowns and Daily Counters Summary

**Header- and body-driven provider cooldowns with per-provider daily counters shared by all LLM roles, skipped without weakening privacy routing, and shown in the health rows**

## Accomplishments
- `src/snow/brain/limits.py`: `parse_duration` (`1h2m3.5s`, `2m59.56s`, `7.66s`, `250ms`), `CooldownDefaults` (60 / 1800 / 20 / 15 s), `RateLimiter` with `record_success`, `record_failure`, `cooling_until`, `snapshot`. Cooldown is capped at 24 h so a provider cannot park itself indefinitely. Times are naive local datetimes; counters reset at local midnight.
- `LLMChain` skips cooling providers (after the privacy check), starts a cooldown from the exception's response headers and JSON body, counts every served request (usage chunk or `len(text)/4`) and republishes provider rows with `requests_today`, `tokens_today`, `cooling_until_ns`. Entries show `cooling_down`; a role whose entries are all cooling reports `cooling_down` instead of `failing`.
- `BrainWorker` owns one `RateLimiter` and passes it to the brain, fast and vision chains; `[limits]` in models.toml feeds its defaults.
- Fixes the 01-08 risk: a bad or limited Groq key now costs one call per turn, because the provider's second chain entry is skipped as cooling.

## Task Commits
1. **Task 1: provider cooldowns and daily counters** - `5c3065e` (feat)

## Deviations from Plan

**1. [Rule 3 - Blocking] src/snow/brain/config.py modified (outside files_modified)**
- The `[limits]` table needs a `limits: CooldownDefaults` field on `ModelsConfig`. `CooldownDefaults` lives in limits.py (which only imports config for typing) to avoid a circular import.

**2. [Rule 1 - Bug] tests/test_skeleton_turn.py updated (outside files_modified)**
- `test_provider_failure_before_first_token_publishes_no_reply` queued two groq 500s and asserted two requests. With cooling, the first failure cools groq and the second groq entry is skipped, so it now asserts one request. This is the intended behaviour change, not a regression.

**3. [Plan discrepancy] `limiter` argument was not reserved in LLMChain**
- 01-08 did not add the argument its summary promised; this plan added it as an optional keyword (`None` keeps the 01-08 tests unchanged). `tests/brain/conftest.py` was left untouched, so test_cooldown.py builds its own chains.

**Total deviations:** 2 files outside the plan list, 1 plan discrepancy. No changes to `src/snow/config/*`, `src/snow/contracts/*`, `src/snow/hub/*`, `tests/conftest.py`, `tests/brain/conftest.py`, `pyproject.toml` or `uv.lock`; no new event types (`health.provider` already had the three fields).

## Issues Encountered
- None blocking. Full suite: 104 passed; ruff and pyright clean.

## Known Stubs
- None. Counters restart at zero when the brain restarts (code comment `shortcut:`); provider 429s re-teach the limits. Persist only if double-spend is observed.

## Threat Flags
None. T-01-18 mitigated (cooldowns, counters, caps, fail-over across providers); T-01-SC: no new packages.

## Self-Check: PASSED
- limits.py contains `def parse_duration`, `class RateLimiter`, `x-ratelimit-reset-requests`, `x-ratelimit-reset`, `retryDelay`; chain.py calls `cooling_until(`; worker.py contains `RateLimiter(`.
- Commit 5c3065e is an ancestor of HEAD.

---
*Phase: 01-always-on-voice-loop*
*Completed: 2026-10-16*
