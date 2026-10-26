---
phase: quick-261026-wvr
plan: 01
subsystem: voice
tags: [barge-in, playout, turn-engine, moonshine, self-echo]
status: complete
requirements: [VOIC-06]
key-files:
  created:
    - src/snow/voice/bargein.py
    - tests/voice/test_barge_check.py
  modified:
    - src/snow/voice/playout.py
    - src/snow/voice/turn.py
    - src/snow/voice/config.py
    - src/snow/voice/stt_local.py
    - src/snow/voice/pipeline.py
    - config/voice.toml
    - tests/voice/conftest.py
    - tests/voice/test_playout.py
    - tests/voice/test_turn_engine.py
    - tests/voice/test_bargein.py
decisions:
  - "Pause holds samples in Playout (set_paused), played stays truthful, no drain or underrun while paused"
  - "Release-sizing check is split: TurnConfig checks pause + echo tail + check window; VoiceConfig adds barge_check.timeout_s (amendment 3)"
  - "Live duck_release_s is 3.0 (not 2.5): the warm-up worst case needs 600 + 250 + 700 + 1000 = 2550 ms"
  - "A check called at the release deadline (spaced bursts) is awaited for a 2 s grace (_CHECK_GRACE_S), the engine ring is sized for it"
actuals:
  tokens: 45000
  tasks: 1
  commits: 1
plan_head_before: 9dc35cacb2bc0db93105279ddb12f6dc0b6da9e6
plan_head_after: 9c275a308a94e8605792b48a80a52fea9a16a5ea
---

# Phase quick-261026-wvr Plan 01: Pause first, decide second Summary

Talking over Snow now ducks it at 150 ms, pauses it at 300 ms with the rest of the reply held in RAM, and runs one local words check (Moonshine) plus a difflib self-echo filter; accept stops Snow for good, reject, quiet or timeout resumes from the exact held sample.

## What was built

- **Playout** (`playout.py`): `set_paused` ramps to 0 over 30 ms, then takes nothing from the queue (`played`, `_buffered` frozen); the drained and underrun branches are skipped while paused; `abort`/`start_utterance` clear it; echo reference still equals what plays.
- **Engine** (`turn.py`): episode rules R1-R11. Duck at `duck_after_ms`, pause at `pause_after_ms` (`barge_in_warmup_min_ms` while the canceller warms), window opens after `echo_tail_ms`, check at `verify_speech_ms` of window speech, one whole-episode check when an episode goes quiet (`quiet_resume_ms`) with at least `check_min_speech_ms` of speech (so a one-word "Stop." is heard), blips give the voice back with no check, `reject_hold_s` turns later pauses into ducks, `verdict()` through a thread-safe queue, stale verdicts ignored. Amendment 4: an episode of spaced short bursts gets its one check at `duck_release_s`.
- **`bargein.py`**: pure `words`, `echo_ratio`, `decide(score, threshold, heard, said, cfg)`. Word floor runs before the echo filter (amendment 1).
- **`LocalStt.transcribe`**: one-shot Moonshine transcription of an in-memory window, never touching the open turn; failures go into the future.
- **Pipeline**: `_request_check` hops to the loop, `_barge_check` awaits `transcribe` under `barge_check.timeout_s`, fails closed to "" on missing model, timeout or error, logs `barge_check episode reason score words echo` (numbers only), then `engine.verdict`. `_said` deque feeds the echo filter; `_pause` wires the playout pause.
- **Config**: new `TurnConfig` keys and `[barge_check]` section in `voice.toml`, validators per the plan plus the words timeout in `VoiceConfig`.

## Deviations from Plan

**1. [Rule 3 - Blocking] Live `duck_release_s` is 3.0, not 2.5.** Amendment 3 sizing at the 600 ms warm-up pause trigger is 600 + 250 + 700 + 1000 = 2550 ms, so 2.5 s fails the validator. Set 3.0 s. Test fixtures still pin 2.0 s as the plan says (model_copy skips validation).

**2. [Rule 2 - Correctness] 2 s check grace.** Amendment 4 checks an unchecked episode at the release deadline; its verdict would arrive after the voice was already given back. The engine now keeps awaiting a deadline-called check for `_CHECK_GRACE_S` = 2.0 s and the audio ring is sized for it. Checks called earlier still give the voice back at the release.

**3. Task type** was `auto` with `tdd="true"` per amendment 2 (tests were written alongside the code in one commit, not as a separate RED commit).

Amendment 5 (key_links wording) needed no code change.

## Verification

- `uv run pytest -q tests/voice/test_playout.py tests/voice/test_turn_engine.py tests/voice/test_bargein.py tests/voice/test_barge_check.py tests/voice/test_echo_cancel.py -x`: 108 passed
- `uv run ruff check src tests`: clean; `uv run ruff format --check src tests`: clean; `uv run pyright`: 0 errors
- `uv run pytest -q tests/voice tests/brain`: 475 passed, 1 skipped, 7 deselected

## Notes for plan 02

- `tests/hardware/test_echo_cancel.py` still compares residual runs with `turn.barge_in_min_ms`. That key now only gates the wake-acknowledgement cut-off; the hardware test should use `pause_after_ms` (and the loopback test should tune it).
- `decide` already accepts a speaker score; `_barge_check` passes `None` and threshold `0.0` (marked with a `shortcut:` comment). Until a voiceprint is enrolled the check runs in degraded mode (2 words plus the echo filter).
- `LocalStt.transcribe` is covered through the fake in rig tests; the real Moonshine call (`transcribe_without_streaming`) was not run against the model in this plan.

## Known Stubs

None.

## Threat Flags

None. T-wvr-01..04 mitigations are implemented: degraded-mode word floor and echo filter, fail-closed words check, numbers-only logs, check timeout plus release deadline, and the reject hold.

## Self-Check: PASSED

- src/snow/voice/bargein.py and tests/voice/test_barge_check.py exist
- commit 9c275a3 is an ancestor of HEAD
