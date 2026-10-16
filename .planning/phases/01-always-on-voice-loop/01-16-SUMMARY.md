---
phase: 01-always-on-voice-loop
plan: 16
subsystem: brain
tags: [persona, emotion, tone, ack-pool, no-scripts, cancellation]
status: complete

requires:
  - phase: 01-always-on-voice-loop/01-08
    provides: LLMChain.stream, take_switch_notice, llm.exhausted, fail-closed MockTransport fixtures
  - phase: 01-always-on-voice-loop/01-12
    provides: RateLimiter and cooldowns that make the switch-notice path real
provides:
  - PersonaConfig, History, Fact, build_messages, apply_overrides (src/snow/brain/persona.py)
  - HeaderParser and split_header for the hidden [[emotion]] / [[emotion|big]] header (src/snow/brain/emotion.py)
  - AckPool and Ack with background refill (src/snow/brain/acks.py)
  - BrainWorker handling transcript.final, ack.requested, turn.cancelled, voice.switch, stt.status
  - config/persona.toml with the full persona prompt, emotion set, history caps and ack settings
affects: [01-17, 01-18, 01-19, 01-21]

commits: 2
plan_head_before: d695b375aaf4bfab6bf9aa5c7241fe14310e1fb8
plan_head_after: 75c94e0bdc044967cb37bb77104a3edfc6d9ecee

actuals:
  tokens: 21000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Streaming header parser buffers only while the text could still be a header; plain text streams through at once, so existing deltas are unchanged"
    - "Ack pool is a background task shared by startup refill and the direct-generation deadline: the deadline only stops waiting, the refill keeps running"
    - "One-time facts are queued by the worker (switch notice, voice.switch, first non-primary stt.status of an episode), injected into the next system message, then cleared; a failed call puts them back"
    - "Cancellation is task.cancel() on the registered turn task plus aclose() of the chain generator, so the chain's own finally records llm.call cancelled"

key-files:
  created:
    - src/snow/brain/persona.py
    - src/snow/brain/emotion.py
    - src/snow/brain/acks.py
    - tests/brain/test_emotion.py
    - tests/brain/test_persona.py
    - tests/brain/test_acks.py
    - tests/brain/test_no_scripts.py
  modified:
    - src/snow/brain/worker.py
    - src/snow/brain/config.py
    - config/persona.toml
    - tests/brain/test_provenance.py

key-decisions:
  - "PersonaConfig moved from brain/config.py to brain/persona.py (the plan places it there); the old one-field class was removed"
  - "Ack lines without a valid header are dropped, so model chatter such as an intro sentence can never be spoken"
  - "Error-context override outranks the stressed-tone override: an error fact allows only neutral or sympathetic, otherwise a stressed tone forces calm"
  - "Context-fact wording lives in worker code as model-facing text, not spoken text; persona.toml stays instructions plus identifiers, enforced by test"
  - "A transcript turn that fails (all providers down) still publishes nothing, as before; only the wake-alone path publishes the silent fallback reply.final"

requirements-completed: [SPCH-01, SPCH-02, CORE-10]

coverage:
  - id: D1
    description: "Replies come from the persona prompt with a validated hidden emotion header, big-moment flag, header never in reply.delta, and tone tag next to the transcript"
    requirement: SPCH-02
    verification:
      - kind: unit
        ref: "tests/brain/test_emotion.py, tests/brain/test_persona.py"
        status: pass
    human_judgment: true
    rationale: "Whether the persona actually sounds like a dry, calm British assistant needs a spoken run with real keys (plan human-check)"
  - id: D2
    description: "Deterministic guardrails: stressed tone forces calm, error context forces neutral or sympathetic"
    requirement: SPCH-02
    verification:
      - kind: unit
        ref: "tests/brain/test_persona.py#test_stressed_tone_forces_calm_whatever_the_model_chose"
        status: pass
    human_judgment: false
  - id: D3
    description: "Wake-alone acknowledgement from an LLM-written general-class pool, served without network; silent fallback when pool and providers are empty"
    requirement: SPCH-01
    verification:
      - kind: unit
        ref: "tests/brain/test_acks.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "turn.cancelled cancels the in-flight stream (llm.call cancelled, no reply.final); switch, voice and stt fallbacks are mentioned once"
    requirement: CORE-10
    verification:
      - kind: unit
        ref: "tests/brain/test_acks.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "No spoken text is a string literal anywhere under src/snow (AST proof, no allow-list)"
    requirement: SPCH-01
    verification:
      - kind: unit
        ref: "tests/brain/test_no_scripts.py"
        status: pass
    human_judgment: false

duration: 45 min
completed: 2026-10-16
---

# Phase 1 Plan 16: Persona and emotional intelligence Summary

**Snow now answers in an original dry, J.A.R.V.I.S.-like persona with an LLM-chosen, validated emotion, reacts to the user's tone, answers "Hey Snow" instantly from a background LLM-written pool, and stays silent when no model can answer.**

## Accomplishments

- Persona prompt and settings in `config/persona.toml` (instructions only); `HeaderParser` strips the `[[emotion]]` / `[[emotion|big]]` header across chunk boundaries, falls back to neutral on invalid or missing headers, and never releases half a header.
- `build_messages` adds the `[user tone: emotion, pace, loudness]` line, history (6 turns, 1200 token budget, seeded from snapshot rows) and one-time context facts; `apply_overrides` enforces calm for stressed/angry/sad/fearful users and neutral/sympathetic for error context.
- Worker streams the `fast` chain with `data_class="private"`, `max_tokens=400` and no `tools`; `reply.final` carries the validated emotion and `big_moment`.
- `AckPool` fills at startup with one `data_class="general"` call whose messages hold no user content, serves `ack.requested` with no network, refills in the background below 3, and waits at most 1.5 s on an empty pool; otherwise one `reply.final` with `reply_source="fallback"`, empty text and no `reply.delta`.
- `turn.cancelled` cancels the registered turn task and closes the chain stream, producing `llm.call` outcome `cancelled` and no `reply.final`.
- `test_no_scripts.py` proves by AST that no `ReplyDelta`/`ReplyFinal` text anywhere under `src/snow` is a literal, and that `persona.toml` holds only instructions and identifiers.

## Task Commits

1. Task 1 (tracer): `feat(01-16)` persona, emotion header, tone-aware replies (also contains `acks.py` and the worker ack wiring, because the worker imports them) - commit `02258b2`
2. Task 2: `test(01-16)` ack pool, silent fallback, cancellation, facts, no-scripts proof - commit `75c94e0`

Tracer verify (`uv run pytest tests/brain/test_emotion.py tests/brain/test_persona.py -x -q`) passed before expansion: 22 passed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Existing startup test needed the ack refill route**
- **Found during:** Task 1
- **Issue:** `BrainWorker.on_snapshot` now fills the ack pool (plan requirement), so `tests/brain/test_provenance.py::test_worker_startup_publishes_all_providers_and_three_roles` made an unrouted request and failed the fail-closed fixture.
- **Fix:** queued one Groq SSE route and made the assertions read the first (announce) health rows plus the final fast-role state.
- **Files modified:** `tests/brain/test_provenance.py` (outside `files_modified`)
- **Commit:** `02258b2`

**2. [Rule 3 - Blocking] PersonaConfig relocated**
- **Issue:** the plan puts `PersonaConfig` in `persona.py` but a one-field class existed in `brain/config.py`.
- **Fix:** removed the old class, defined the full one in `persona.py`; nothing else imported it.
- **Files modified:** `src/snow/brain/config.py` (outside `files_modified`)
- **Commit:** `02258b2`

**Total deviations:** 2 auto-fixed (both Rule 3, test and config plumbing). **Impact:** none on behaviour.

No respx was used; all LLM tests use the fail-closed httpx2 MockTransport routes. `hub/`, `contracts/`, `config/` (the Python package), `chain.py`, `limits.py`, `models.toml`, `pyproject.toml` and `uv.lock` were not touched.

## Known Stubs

None.

## Notes and risks

- A turn cancelled while still connecting (before the first token) leaves no `llm.call` row because the chain has not opened a call yet; once streaming has started the cancelled call is recorded.
- Ack-pool refill happens on every hub (re)connect while the pool is below size, and after each pop below the minimum; with no keys or all providers down this emits one `llm.exhausted` per attempt (visible on the HUD, bounded by wake requests).
- Persona quality (tone, wit, "sir") is untested against a real model; the plan's human-check needs stored keys.
- Known flaky `tests/brain/test_chain.py::test_first_entry_serves_and_call_is_recorded` failed once in the first full run (0.2 s fake TTFT timeout) and passed on re-run; not silenced.

## Threat Flags

None. No new network endpoints, auth paths or schema changes; ack generation is the only added `general` call (T-01-34) and carries no user content.

## Verification

- `uv run pytest tests -q`: 219 passed
- `uv run pytest tests/brain -q`: 95 passed
- `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pyright`: clean

## Self-Check: PASSED

All created files exist, commits `02258b2` and `75c94e0` are ancestors of HEAD, task acceptance criteria re-checked (`allowed_emotions` and "sir" in persona.toml, `class HeaderParser`, `[user tone:`, `class AckPool`, `data_class="general"`, turn.cancelled handling, `take_switch_notice`, `reply_source="fallback"`).
