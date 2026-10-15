---
phase: 01-always-on-voice-loop
plan: 08
subsystem: brain
tags: [openai-sdk, fallback-chain, privacy-routing, provenance, health]

requires:
  - phase: 01-always-on-voice-loop/01-03
    provides: BrainWorker, config models, keyring secrets, mock provider test mechanism
  - phase: 01-always-on-voice-loop/01-04
    provides: llm.call, llm.switch, llm.blocked_privacy, llm.exhausted, health.role, health.provider events
provides:
  - LLMChain, ChainStream, Trace, classify, PrivacyBlockedError, AllProvidersFailed, MidStreamError (src/snow/brain/chain.py)
  - Full five-provider config/models.toml with brain, fast and vision chains and per-role TTFT deadlines
  - BrainWorker on the fast chain with data_class private, startup health rows via on_snapshot
  - tests/brain fixtures: fail-closed Routes mock, Events, FakeClock, chain_factory
affects: [01-09, 01-12, 01-16, 01-17]

commits: 3
plan_head_before: f12b47dbece29993c5b9eeb1f0afbf9a2c67c229
plan_head_after: 9405c943f1e0cb054aff3737bb00c7cf0522ce36

actuals:
  tokens: 21000
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Chain entries are config; a role never holds 'the provider' (single provider = chain of length one)"
    - "Failover only before the first token; later errors raise MidStreamError"
    - "data_class defaults to private and the trust filter runs before any HTTP request"
    - "Provider HTTP faked by an httpx2.MockTransport route table that fails closed on unrouted hosts"

key-files:
  created:
    - src/snow/brain/chain.py
    - tests/brain/__init__.py
    - tests/brain/conftest.py
    - tests/brain/test_chain.py
    - tests/brain/test_config_swap.py
    - tests/brain/test_privacy.py
    - tests/brain/test_provenance.py
  modified:
    - src/snow/brain/config.py
    - src/snow/brain/worker.py
    - src/snow/brain/__main__.py
    - config/models.toml
    - tests/test_skeleton_turn.py

key-decisions:
  - "LLMChain takes client_factory and a shared ProviderBoard so tests inject transports without monkeypatching and the three role chains agree on provider status"
  - "The worker keeps one chain per role and rebuilds them only when models.toml changed, so cached clients and health change-detection survive across turns while edits still apply next turn"
  - "When a privacy-skipped entry exists and nothing else can serve, PrivacyBlockedError wins over AllProvidersFailed, even if earlier trusted entries failed"

requirements-completed: [CORE-04, CORE-08, CORE-10, SAFE-12]

coverage:
  - id: D1
    description: "Roles are ordered config chains; reordering or changing a base_url or model in models.toml changes who is called with no code change"
    requirement: CORE-04
    verification:
      - kind: integration
        ref: "tests/brain/test_config_swap.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "429 (rate and quota), 5xx, connection error, TTFT deadline, bad key and unsupported-parameter move to the next entry before the first token; keyless and unresolved-model entries are skipped as not_configured; each failing route is hit exactly once"
    requirement: CORE-08
    verification:
      - kind: unit
        ref: "tests/brain/test_chain.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "A stream error after the first token does not fail over; an exhausted or all-keyless chain raises AllProvidersFailed and emits llm.exhausted"
    requirement: CORE-08
    verification:
      - kind: unit
        ref: "tests/brain/test_chain.py#test_error_after_first_token_does_not_fail_over"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every llm.call and reply.final carries provider and model; health.role shows fallback with active_index 1 after failover; switch notice is returned once"
    requirement: CORE-10
    verification:
      - kind: unit
        ref: "tests/brain/test_provenance.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Private data (the default) never reaches untrusted providers; only-untrusted chains raise PrivacyBlockedError, emit llm.blocked_privacy and send zero HTTP requests"
    requirement: SAFE-12
    verification:
      - kind: unit
        ref: "tests/brain/test_privacy.py"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 08: Fallback Chain, Privacy Routing and Provenance Summary

**Config-driven LLM fallback chain per role over five OpenAI-compatible providers, with a private-by-default trust filter that sends zero requests when only untrusted providers remain, and llm.call / health.role provenance for the HUD**

## Accomplishments
- `LLMChain.stream` walks the role's chain, skipping keyless or unresolved-model entries, fails over before the first token on out_of_quota, rate_limit, service_error, timeout (TTFT deadline, fast 2.5 s, brain 6 s), unreachable, bad_key and config_error, and calls each failing route exactly once (`max_retries=0`).
- After the first token an error ends the turn with `MidStreamError` (no duplicated reply); the worker still publishes the partial `reply.final`, as in 01-03.
- Each attempt leaves a durable `llm.call`; failover emits `llm.switch`; exhaustion emits `llm.exhausted`; `health.role` reports active / fallback / failing / not_configured / not_used_yet with per-entry rows, and `health.provider` rows are sent on change. `take_switch_notice()` hands a limit-caused switch to plan 01-16 once.
- SAFE-12: `data_class` defaults to `"private"`; untrusted providers (google, openrouter) are skipped for private data before any request; the zero-request proof is `routes.total == 0` in `test_privacy.py`, and the fail-closed mock turns any unrouted request into a test failure.
- `config/models.toml` now holds the five providers (exactly two untrusted) and the D-21/D-22 brain, fast and vision chains. Entries whose model ID is unconfirmed use `model = ""` plus a `match` glob and are skipped as "not configured" until plan 01-17's probe resolves them.

## TDD (Task 2)
- **RED** (`0cc4715`): `test_privacy.py` and `test_provenance.py`. 4 privacy tests failed for the planned reason (chain still sent the private call to `google.test`; caught by the fail-closed route as an unrouted request). The provenance tests already passed because the tracer task implemented provenance. Evidence is plain pytest output, which the `tdd-red-evidence` classifier does not support, so it was not machine-classified; semantic assessment: the target tests executed and failed on the planned behavior (no `PrivacyBlockedError`, google was called), not on setup or import errors.
- **GREEN** (`9405c94`): trust filter, `LlmBlockedPrivacy`, `PrivacyBlockedError`, blocked entries marked in health rows.
- **REFACTOR**: none needed.

## Task Commits
1. **Task 1: Fallback chain, config, worker, models.toml** - `19fded7` (feat)
2. **Task 2 RED: privacy and provenance tests** - `0cc4715` (test)
3. **Task 2 GREEN: privacy routing** - `9405c94` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] respx replaced by an httpx2.MockTransport route table**
- **Issue:** openai 3.29 runs on `httpx2`, respx cannot intercept it (found in 01-03), so the plan's respx routes and `respx_mock.calls.call_count == 0` would hit real providers.
- **Fix:** `tests/brain/conftest.py` has `Routes` (per-host queues, per-host call counters, `total`) injected through `LLMChain(client_factory=...)` and `BrainWorker(client_factory=...)`. Unrouted host or path records a violation and the `routes` fixture fails the test at teardown, so a test cannot silently reach a provider (the SDK would otherwise swallow the handler exception as a connection error). `test_privacy.py` asserts `routes.total == 0`.
- **Files:** tests/brain/conftest.py, tests/brain/test_*.py

**2. [Rule 1 - Bug] tests/test_skeleton_turn.py adjusted (outside files_modified)**
- **Issue:** `test_provider_failure_before_first_token_publishes_no_reply` assumed one keyed fast entry and an empty publish list. With the full chain, a groq 500 now tries `qwen/qwen3.8-27b` (same key) and records `llm.call` and `llm.exhausted`, which is exactly what 01-03 deferred to this plan.
- **Fix:** queue two 500s, assert two requests, `llm.call` and `llm.exhausted` published, no `reply.delta` or `reply.final`. The other two tests in the file pass unchanged, including the `snow.brain.worker.AsyncOpenAI` monkeypatch (kept working via `_default_factory`).
- **Commit:** 19fded7

**3. [Rule 3 - Blocking] src/snow/brain/__main__.py (outside files_modified)**
- Startup health rows need a hook that runs when the brain connects; `HubClient.on_snapshot` is the only one, so `__main__` now also sets `client.on_snapshot = worker.on_snapshot`. `python -m snow.brain` still imports and runs; `BrainWorker(publish)` still works with the one-argument constructor (01-06's smoke test).
- **Commit:** 19fded7

**4. [Rule 2 - Missing Critical] Mid-chain consequences of the privacy default**
- `test_exhausted_chain_raises_and_emits` now passes `data_class="general"` because the default private call correctly raises `PrivacyBlockedError` once google is reached.

---

**Total deviations:** 2 blocking (test mechanism, brain `__main__` hook), 1 test update, 1 test clarification. No changes to `tests/conftest.py`, `src/snow/contracts/*`, `src/snow/hub/*`, `pyproject.toml` or `uv.lock`; no new event types needed.

## Issues Encountered
- Ruff E501 and strict pyright needed `LlmRole`-typed fields; fixed inline. Full suite: 72 passed, ruff and pyright clean.
- `with_raw_response.create(stream=True)` composes with async streaming in openai 3.29 (research assumption A9 holds), so rate-limit headers are exposed as `ChainStream.headers` for plan 01-12 without an httpx hook.

## Known Stubs
- `config/models.toml`: google, nvidia and openrouter chain entries and the vision/brain fallbacks use `model = ""` with a `match` glob. Intentional (D-29: IDs never guessed); plan 01-17's probe resolves them. Until then they are reported `not_configured` ("Model ID not resolved; run snow dev probe-models").
- `ChainEntry.requires` and `daily_request_cap` are parsed but not enforced; plan 01-12 adds limit handling and 01-17 the capability probe.
- Provider cooling (`cooling_down`) is not produced here; plan 01-12.

## Threat Flags
None. T-01-17 mitigated and tested (default private, trust filter before any request, zero-request test). T-01-19: no `tools` parameter is ever sent. T-01-20: only failure kinds and status codes are logged; `test_secret_never_appears_in_events` checks keys never reach events. T-01-SC: no new packages.

## Next Phase Readiness
- Plan 01-12 can add a `limiter` to `LLMChain` and read `ChainStream.headers`; 01-16 can call `take_switch_notice()` and pass `data_class="general"` for content-free prompts; 01-17 fills the empty model IDs.

## Self-Check: PASSED
- Created files exist: chain.py, tests/brain/{__init__,conftest,test_chain,test_config_swap,test_privacy,test_provenance}.py.
- Commits 19fded7, 0cc4715, 9405c94 are ancestors of HEAD.
- `trust = "untrusted"` appears twice in models.toml; chain.py contains `max_retries=0`, `class AllProvidersFailed`, `class MidStreamError`, `class PrivacyBlockedError`, `def classify`, `data_class: DataClass = "private"`.

---
*Phase: 01-always-on-voice-loop*
*Completed: 2026-10-16*
