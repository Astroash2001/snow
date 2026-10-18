---
phase: quick-261018-glq
plan: 01
subsystem: voice
tags: [echo-cancellation, webrtc-aec3, livekit, barge-in, VOIC-06]
requires: []
provides:
  - EchoCanceller (livekit AudioProcessingModule, echo cancellation only) on the live mic path
  - cold-start barge-in guard (barge_in_warmup_min_ms)
  - hand-run speaker + mic hardware test
affects: [voice worker, config/tts.toml, config/voice.toml]
tech-stack:
  added: [livekit==1.1.20, types-protobuf==7.35.1.20260906 (transitive)]
  patterns: [fail-open native wrapper, audio-time warm-up counter]
key-files:
  created:
    - src/snow/voice/aec.py
    - tests/voice/test_echo_cancel.py
    - tests/hardware/test_echo_cancel.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/snow/voice/playout.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/turn.py
    - src/snow/voice/config.py
    - src/snow/voice/tts/config.py
    - src/snow/voice/__main__.py
    - config/voice.toml
    - config/tts.toml
    - tests/voice/test_bargein.py
decisions:
  - "Echo cancellation only; noise suppression, AGC and high-pass stay off (AGC shifts VAD, wake and tone levels)"
  - "No set_stream_delay_ms: research measured no effect for true delays up to 500 ms"
  - "Warm-up guard keyed on seconds of reference audio played (2 s), not wall clock"
metrics:
  duration: ~40 min
  completed: 2026-10-18
status: complete
actuals:
  tokens: 38000
  tasks: 3
  commits: 3
plan_head_before: 834e3c4e7ce604af7538289abd6b750385a39b39
plan_head_after: dc7d1b8401655ac5337f4799e8ae67e946721bb2
---

# Phase quick-261018-glq Plan 01: Real echo cancellation (livekit APM) Summary

WebRTC AEC3 through livekit 1.1.20 now sits between Snow's speaker and the mic: playout feeds it the reference, every live mic frame is cleaned before wake, VAD, Moonshine, Groq and tone, and the live worker runs it by default on speakers.

## What was built

- `src/snow/voice/aec.py`: `EchoCanceller` (echo cancellation only). `render()` taps the playout (never raises), `capture()` cleans 10 ms slices, `warming()` is true until 2 s of reference voice has played, any failure switches both sides to pass-through (`aec_failed` logged once). Non-10 ms frames raise `ValueError` before the native call; non-multiple-of-100 rates are refused.
- `Playout` gained `on_render`, called once per block, silent blocks included.
- `VoicePipeline` gained `echo_cancel`; the canceller is built in `asyncio.to_thread` after the voice loads (rate from the router). Load failure logs `aec_unavailable` and audio passes through. `_on_frame` cleans first; `stop()` closes it. The speakers warning is now logged only when `assume_headphones` and `echo_cancel` are both false.
- `TurnEngine.echo_warming` plus `barge_in_warmup_min_ms = 600` (steady state stays 250); the barge ring is sized for the larger value.
- `config/tts.toml`: `assume_headphones = false`, `echo_cancellation = true`; the worker passes it to `build_pipeline`.
- `tests/hardware/test_echo_cancel.py` (marked hardware, memory only, not run).

## New lock packages

Only `livekit 1.1.20` and `types-protobuf 7.35.1.20260906`. No existing package changed version.

## Measured test numbers (real APM, real Silero, synthetic echo, seed 0, delay 120 ms, -26 dBFS)

| Check | Measured | Threshold |
|-------|----------|-----------|
| Raw mic, longest VAD run in utt2 | 896 ms | >= 250 ms (precondition) |
| Cleaned, longest VAD run in utt2 | 0 ms | < 250 ms |
| ERLE from +1 s of utt2 | 39.1 dB | >= 20 dB |
| Cold residual (first reply) in this scene | 0 ms | informational |
| Sweep seeds 0-3 x delays 60/120/250 | all 12 pass | same thresholds |
| Double-talk: user VAD chunks surviving | 125 of 132 (95%) | >= 70% |
| Double-talk: barge-in detection delay vs user alone | +0.22 s | <= 0.7 s |

All thresholds met as stated; none loosened. Research numbers reproduced or beaten.

## Gates

- `uv run pytest -q -m "not hardware and not gpu and not network"`: 454 passed, 1 skipped, 1 error. The error is the known pre-existing `tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env` ("hub exited early", the user's real Snow hub holds the single-instance lock). Not touched.
- `ruff check`, `ruff format --check`, `pyright` (0 errors), `snow.contracts.export --check`: all clean.
- `pytest -m hardware tests/hardware/test_echo_cancel.py --collect-only`: 2 tests collected, no device opened.
- `uv run pip-audit`: No known vulnerabilities found.
- `tests/voice/test_no_egress.py` and `tests/brain/test_no_scripts.py` pass; nothing writes audio to disk.

## Hardware command for the user (not run by the executor)

With Snow quit or muted and speakers on at normal volume in a quiet room:

    uv run pytest -m hardware tests/hardware/test_echo_cancel.py -x -q -s

Expect ERLE >= 15 dB, no barge-in-length residual after 3 s, and the talk-over test passing (it prompts you to speak over Snow). Run it twice: FxSound Speakers as the default output, then FxSound effects off or another output. Report the printed stream latencies and both verdicts. Then restart Snow on speakers: it should no longer transcribe itself or cut its own reply after 250 ms.

## Deviations from Plan

**1. [Rule 3 - Blocking] Warning change and `echo_warming` wiring moved between tasks.** The `start()` speakers-warning guard (plan Task 3 step 4) was done in the Task 1 pipeline edit since it touched the same lines; the `echo_warming` line in `_load_tts` was held back to Task 2 so Task 1 committed cleanly. No behaviour difference.

**2. Test helper.** `make_rig` in `tests/voice/test_bargein.py` gained an `echo_cancel` keyword so the pipeline wiring tests reuse it. Existing callers unchanged.

Otherwise the plan was executed as written.

## Known Stubs

None.

## Threat Flags

None. No new network surface; no livekit Room is created. Mitigations T-glq-01 to T-glq-05 implemented and tested (frame-size ValueError, render never raises, fail-open load, memory only, warm-up guard).

## Residual risks (unchanged from plan)

- FxSound DSP and the Intel mic driver's own processing are untested until the hardware run; real ERLE may be lower than synthetic.
- A cold residual during a wake acknowledgement could still open a short turn; accepted until the hardware run.
- Real loopback delay above 500 ms would defeat AEC3 (fallback: headphones or the physical speaker output).

## Self-Check: PASSED

- aec.py, tests/voice/test_echo_cancel.py, tests/hardware/test_echo_cancel.py exist.
- Task commits be351ce, 7ee1012, dc7d1b8 are on the branch.
