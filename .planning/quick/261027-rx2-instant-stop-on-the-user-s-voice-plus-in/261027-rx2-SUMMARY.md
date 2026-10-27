---
phase: quick-261027-rx2
plan: 01
subsystem: brain, voice
tags: [barge-in, interruption, persona, turn-engine]
requirements: [VOIC-06, SPCH-01]
key-files:
  modified:
    - src/snow/brain/persona.py
    - src/snow/brain/worker.py
    - config/persona.toml
    - src/snow/voice/turn.py
    - src/snow/voice/config.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/playout.py
    - config/voice.toml
    - tests/brain/conftest.py
    - tests/brain/test_persona.py
    - tests/voice/conftest.py
    - tests/voice/test_turn_engine.py
    - tests/voice/test_bargein.py
    - tests/voice/test_playout.py
    - tests/hardware/test_bargein_loopback.py
decisions:
  - "Marker stripping is a streaming MarkFilter in persona.py (shares INTERRUPTED_MARK with History); it holds back a possible marker prefix across chunks."
  - "History records a cancelled turn in the _answer finally block, so reply.interrupted trims it in either event order."
  - "Duck stage removed entirely; pause fires only when the reject hold is 0."
metrics:
  tasks: 2
  commits: 2
actuals:
  tasks: 2
  commits: 2
plan_head_before: 8ccb75f6d66e36e26358eeebccd456d9cce34141
plan_head_after: 93cf96f
status: complete
completed: 2026-10-27
---

# Phase quick-261027-rx2 Plan 01: Instant stop on the user's voice plus interruption-aware brain Summary

Speech over Snow now pauses it at the first speech decision (live 150 ms) with no fade stage, and after an interruption the brain's history holds only the words the user heard plus an instruction-only marker the persona explains.

## Commits

- 7e570fd feat(quick-261027-rx2): brain history keeps only what the user heard, plus an interruption marker
- 93cf96f feat(quick-261027-rx2): instant fade-free pause on speech over Snow; reject hold postpones the next pause

## What changed

- Brain: `History` stores turn ids; `interrupt()` trims in either event order (pending cuts bounded), `seed()` respects interrupted rows. The worker handles `ReplyInterrupted` and records a cancelled turn in the `finally` block (no `reply.final` for it). `persona.toml` has one bullet naming the marker, no scripted lines.
- Amendment: `MarkFilter` strips the marker from every published delta and the final, even when split across chunks. Test: a model reply containing the marker is published without it.
- Voice: duck hook, duck config keys, `Playout.set_gain` removed. The pause branch requires `_hold == 0`; the reject hold (1.0 s) postpones the next pause, then speech pauses at once. Release sizing includes `reject_hold_s` in both validators. Live values: `pause_after_ms = 150`, `reject_hold_s = 1.0` (3950 ms sizing within the 4.0 s release).

## Verification

- `ruff check`, `ruff format --check`, `pyright`: clean.
- `pytest tests/voice tests/brain tests/test_skeleton_turn.py`: 515 passed, 2 skipped, 7 deselected.
- `uv.lock` and `pyproject.toml` unchanged. No `.duck`/`.set_gain` left in src/snow/voice, tests/voice, tests/hardware.
- Human check (after the user restarts Snow): talk over a long answer, Snow goes silent at once with no fade; a cough pauses briefly and Snow resumes from the same word.

## Deviations from Plan

None in scope. Test-only adjustment: the live-timings test borrows the fixture's `stop_secs 0.2` (live 0.7 would stop `Over()` from ending its first turn); the pause timings under test are the live ones.

## Notes

- During an active reject hold the engine's quiet-gap check still runs on unpaused audio, as the plan specified; it remains behind the same fail-closed speaker/words/echo check.

## Known Stubs

None.

## Self-Check: PASSED
