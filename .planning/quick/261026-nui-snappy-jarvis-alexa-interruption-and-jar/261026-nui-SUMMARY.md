---
phase: quick-261026-nui
plan: 01
subsystem: voice
status: complete
tags: [barge-in, wake-word, duck, playout, persona]
requirements: [VOIC-06, SPCH-01]
key-files:
  modified:
    - src/snow/voice/turn.py
    - src/snow/voice/playout.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/config.py
    - config/voice.toml
    - config/persona.toml
    - tests/voice/conftest.py
    - tests/voice/test_turn_engine.py
    - tests/voice/test_bargein.py
    - tests/voice/test_playout.py
actuals:
  tasks: 3
  commits: 3
plan_head_before: cb6968a127e378ff4ac6fe769ed7e45d7fd8e5fc
plan_head_after: c9e459bba6674ae559319ea06c89f37608dc2aa9
completed: 2026-10-26
---

# Quick 261026-nui: Snappy Alexa/Jarvis interruption Summary

The wake phrase now interrupts Snow mid-speech, a gap-tolerant 400 ms barge-in ducks Snow's voice to 0.25 after 150 ms of speech (releasing after 1 s if unconfirmed), and the persona carries the Jarvis answer rules.

## Commits

- 1d54f96 Task 1 (tracer): `_cut()` shared stop path; `on_wake` cuts audible speech and opens a fresh wake turn; persona section "Answering and being interrupted"
- 303c494 Task 2: `TurnConfig` barge_gap_ms / duck_after_ms / duck_gain / duck_release_s with validator; live barge_in_min_ms 400; episode-based `_listen_over`; seed = run + 0.3 s
- c9e459b Task 3: `Playout.set_gain` with 30 ms per-sample ramp before `on_render`, reset per utterance/abort/drain; `engine.duck` wired in `_load_tts`

## Deviations from Plan

None in behaviour. Two small notes:
- The playout duck test asserts 0.125 at 30 ms after the duck as the plan says; the ramp actually reaches 0.125 earlier (0.75 gain swing = 540 samples at 24 kHz), which satisfies "within 30 ms".
- Line-length fixes (E501) in config.py, playout.py and turn.py comments/docstrings so ruff passes.

## Gate results

- `uv run ruff check src tests`: pass
- `uv run ruff format --check src tests`: pass (131 files)
- `uv run pyright`: 0 errors
- `uv run pytest -q tests/voice tests/brain`: 433 passed, 1 skipped, 7 deselected (run before the final docstring-only line-length edit; ruff re-run after it passes)

## Hand checks for the user (not run by the executor)

1. While Snow is mid-reply, say "Hey Snow". The voice stops within about a tenth of a second, the HUD shows listening, and Snow answers what you say next. If you say nothing, it gives a short acknowledgement.
2. Talk over a long reply. Snow's voice drops at once and stops within about half a second.
3. Cough or tap the desk while Snow speaks. The voice dips briefly, comes back, and the reply continues.
4. On laptop speakers, let Snow speak several long replies without talking. It must never cut itself off.
5. Ask for the time or a count. The number comes first. Interrupt a reply with a new question. Snow answers the new question without apologising or finishing the old sentence.

## Notes for closing G-01-5

- tests/voice/test_echo_cancel.py and tests/hardware/test_echo_cancel.py still measure the echo residual as consecutive VAD runs. The engine now accumulates across gaps of up to 150 ms, and the live minimum (400 ms) is below the 0.42 s residual run seen on 2026-10-24, so the hardware echo suite and hand check 4 must be run on speakers before G-01-5 is closed.
- The wake-acknowledgement cut-off in `_chunk` (`t.speech_run >= self._barge_min()`) still uses the consecutive run; out of scope.
- tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env is a known failure while the user's Snow runs; not touched.

## Known Stubs

None.

## Threat Flags

None. No logging added; no audio written; no packages added.

## Self-Check: PASSED

Commits 1d54f96, 303c494, c9e459b exist on branch worktree-agent-a726782a8b5ee1995.
