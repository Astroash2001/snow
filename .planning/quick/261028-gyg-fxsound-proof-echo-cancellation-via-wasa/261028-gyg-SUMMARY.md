---
phase: quick-261028-gyg
plan: 01
subsystem: voice
tags: [aec, wasapi-loopback, fxsound, barge-in, pyaudiowpatch]
requires: []
provides:
  - "EchoCanceller loopback reference (use_loopback, loopback_block, loopback_stale, render_rate)"
  - "snow.voice.loopback: is_enhancer, pick_endpoint, LoopbackReference"
  - "AudioConfig aec_reference, aec_reference_device, output_enhancers, enhancer_disables_bargein"
  - "TurnEngine.speech_barge_in hook (wake-only fallback, off by default)"
affects: [snow.voice, config/voice.toml, tests/hardware]
tech-stack:
  added: ["pyaudiowpatch==0.2.12.9 (user-approved 2026-10-28)"]
  patterns: ["reference with fallback: loopback first, render on any failure, background retry"]
key-files:
  created:
    - src/snow/voice/loopback.py
    - tests/voice/test_loopback.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/snow/voice/aec.py
    - src/snow/voice/config.py
    - config/voice.toml
    - src/snow/voice/pipeline.py
    - src/snow/voice/turn.py
    - src/snow/voice/playout.py
    - tests/voice/conftest.py
    - tests/hardware/test_bargein_loopback.py
decisions:
  - "Reference defaults to the WASAPI loopback in voice.toml; the model default stays render so configs without the key behave as before"
  - "Zero frames are fed when the loopback queue is empty, so the render timeline keeps pace with capture"
status: complete
commits: 3
plan_head_before: 16b8ab2fd56ff152eff786e009c8e9cd4767316c
plan_head_after: 64fa5282b7c436d74d33de74dc63a296d8577d45
actuals:
  tokens: 45000
  tasks: 3
  commits: 3
requirements-completed: [VOIC-06]
completed: 2026-10-28
---

# Quick 261028-gyg: FxSound-proof echo cancellation via WASAPI loopback

Snow's echo canceller now takes its reference from a WASAPI loopback of the speaker endpoint the audio finally reaches (the real speakers behind FxSound), and falls back to the old render reference whenever the loopback is unavailable, lost, ambiguous or silently dead.

## Commits

- `7b48386` feat: WASAPI loopback as the echo canceller's reference (tracer, dependency, aec.py, loopback.py, unit tests)
- `3f94d70` feat: the live voice worker uses the loopback reference (config, voice.toml, pipeline, conftest isolation, wiring tests)
- `64fa528` feat: wake-only fallback and FxSound-style hardware scenarios (turn.py, playout.py, pipeline gate, hardware suite)

## Measured numbers (deterministic unit tracer)

Scene: Snow's voice goes through a pumping gain of about +-9 dB at 3 Hz and tanh saturation, then the 60 ms room impulse (120 ms delay, -26 dBFS). ERLE is measured from `utt2_s + 1.0`.

| Reference | Longest speech run | ERLE |
|-----------|--------------------|------|
| render (old) | 0 ms | 14.4 dB |
| loopback (new) | 0 ms | 39.9 dB |

The render reference does not leave a barge-in-length run in this synthetic scene (AEC3's suppressor hides it), so the test asserts the plan's alternative: loopback ERLE beats render ERLE by 6 dB or more (measured 25.5 dB). The loopback path meets the bar of 20 dB and no barge-in-length run.

## Verification

- `uv lock --check` passes; the uv.lock diff adds only `pyaudiowpatch`; pyproject.toml gains only its pin.
- `uv run --no-sync ruff check src tests`, `ruff format --check src tests`, `pyright`: clean.
- `uv run --no-sync pytest -q tests/voice`: 423 passed, 2 skipped (the plan asked for `--no-sync`; the worktree has its own `.venv`, so plain `uv run` would also have worked).
- Rest of the suite: 246 passed; the one error is the known `tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env` (fails while Snow runs).

## Hardware suite: SKIPPED-PENDING

Snow is running and the user is working, so nothing was played. Both new scenarios are collected (`test_fxsound_style_output_with_the_loopback_reference_never_pauses_snow`, `test_fxsound_style_output_with_the_render_reference_is_recorded`) and skip with "Snow is running: quit it, then rerun". For the orchestrator to run later with the user, after quitting Snow, FxSound on:

    uv run pytest -m hardware tests/hardware/test_bargein_loopback.py -x -q -s

The existing room scenarios are pinned to the render reference (room sounds play through the PC, so a loopback would cancel them).

## Notes

- Bonus: every sound the PC plays (videos, music) is in the loopback reference, so it is cancelled from the mic too. Documented in the aec.py docstring and the voice.toml comment.
- Assumption A1: the Realtek driver's own endpoint effects may or may not be in the loopback. The hardware run settles it.
- Edge: if Snow plays to a different endpoint than the one the loopback reads, no loopback packet arrives while Snow is audible. The liveness check (1 s) falls back to render and the loopback is retried every 10 s, so Snow flaps between the two but never runs on a dead reference.
- The user must restart Snow to pick up the change; afterwards a normal `uv sync` refreshes the project install (the running `snow.exe` was never touched).
- Wake-only fallback: `enhancer_disables_bargein` (default false). When true, with an enhancer as the default output and no live loopback, speech over Snow never starts a barge-in episode; "Hey Snow" still cuts. Logged once at load as `speech_barge_in=wake_only_without_loopback`. No HUD indicator (hub and contracts belong to the other session). The default output name is read once at voice load (shortcut comment in `default_output_name`).

## Deviations from Plan

- **[Rule 3 - Blocking] Own `.venv`:** the worktree had no `.venv`, so `uv sync --frozen` created one, then `uv add pyaudiowpatch==0.2.12.9` ran as the plan's constraints allowed (plain `uv add`, no `--no-sync` needed).
- **[Rule 2 - Missing] ImportError reason:** `LoopbackReference` catches `ImportError` explicitly so a missing module logs `reason=ImportError` (a `ModuleNotFoundError` would otherwise log its subclass name).
- **[Rule 2 - Missing] Empty resampler chunk:** the callback skips a zero-length chunk (the soxr stream's first chunk can be empty), avoiding a NaN level and a numpy warning.
- **conftest:** the autouse `no_device_rate` fixture also stubs `snow.voice.pipeline.default_output_name`, so no voice test queries a real device.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-gyg-01 to T-gyg-SC are covered: memory-only audio with a no-disk and log-content test, liveness fallback, catch-all PortAudio callback, exact-pinned hash-locked dependency).

## Self-Check: PASSED

- src/snow/voice/loopback.py, tests/voice/test_loopback.py: present.
- Commits 7b48386, 3f94d70, 64fa528: reachable from HEAD.

## Orchestrator hardware run (2026-10-28, Snow quit, FxSound on, volume ~70 %, fan off)

`uv run pytest -m hardware tests/hardware/test_bargein_loopback.py -q -s`: 7 passed (5 m 55 s). Room -57.3 dBFS, speaker burst -12.2 dBFS.

- Snow alone, 3 long replies: 0 pauses, 0 cut-offs.
- Coughs, clicks, noise bed: 0 pauses (enrolled and no-voiceprint).
- Voice clip over Snow, no voiceprint: confirmed and cut (positive control).
- Same clip with the user's voiceprint: rejected twice by speaker (0.22, 0.20), so a stranger's voice cannot cut Snow.
- FxSound-style scenarios, loopback and render reference: 0 pauses each (the simulated enhancer is milder than the real one).

Live check before this run, FxSound on, 45 % volume, fan on: 0 self-pauses in about 50 s of speech (5 in 3 min before the fix); 2/2 real interruptions confirmed.

A first attempt crashed (0xC0000005: Moonshine's onnxruntime 1.23 loaded before sherpa); fixed in b7e8eec by loading sherpa-onnx in `snow/voice/__init__.py`.
