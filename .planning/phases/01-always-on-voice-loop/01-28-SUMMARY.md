---
phase: 01-always-on-voice-loop
plan: 28
subsystem: voice
tags: [tts, router, failover, kokoro-onnx, fallback, spch-03]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "TtsEngine protocol, PocketEngine, Playout and speech orchestration (01-26), voice.switch/voice.status/health events (01-04), kokoro-onnx 0.6.1 pin (01-02)"
provides:
  - "snow.voice.tts.router.VoiceRouter: D-33 engine order from config, per-reply choice, mid-reply failover, cooldown, voice.switch/voice.status/health speech_output"
  - "snow.voice.tts.kokoro.KokoroEngine: last-resort British male local voice (bm_george), SHA-256-pinned model files"
  - "[engines.kokoro] and [router] cooldown_s in config/tts.toml"
affects: [01-29 barge-in, 01-31 Cartesia, 01-33 Chatterbox, 01-32 user voice]

commits: 1
plan_head_before: ad9efa3def190a4b809927c91053f3ab5d5241df
plan_head_after: 6b55324

actuals:
  tokens: 32000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Engine chain with cooldown, mirroring stt_router: first enabled+registered+eligible+healthy engine wins; a synthesis error cools the engine down, a load failure lasts the session"
    - "Engines load in background tasks; readiness waits only for the engine that would speak an everyday reply, so a slow Kokoro download never delays a loaded Pocket"
    - "Switch announced once per failure, when the next engine has actually been chosen"

key-files:
  created:
    - src/snow/voice/tts/router.py
    - src/snow/voice/tts/kokoro.py
    - tests/voice/test_tts_router.py
    - tests/voice/test_tts_failover.py
  modified:
    - src/snow/voice/pipeline.py
    - src/snow/voice/__main__.py
    - src/snow/voice/tts/config.py
    - config/tts.toml
    - tests/voice/test_tts_pipeline.py

key-decisions:
  - "Router, not pipeline, owns the speech_output health row and the VoiceStatus card (announce() dedupes; the pipeline only forces a republish on hub reconnect)"
  - "Any non-EngineError exception from an engine counts as a broken engine (kind unreachable): Pocket's generator re-raises raw library errors"
  - "A fallback engine at another sample rate is linearly resampled to the open playout's rate (all current engines are 24 kHz, so this is dormant)"
  - "cooldown_s = 60 in [router]; a load failure is never retried within a session"

requirements-completed: [SPCH-03]

coverage:
  - id: D1
    description: "Normal and big_moment replies both select pocket_tts when only pocket and kokoro are enabled"
    status: tested
  - id: D2
    description: "Pocket load failure selects kokoro; voice.switch(pocket_tts to kokoro, load_failed) and voice.status(kokoro, fallback) published once"
    status: tested
  - id: D3
    description: "Pocket erroring on chunk 2 of 3: chunks 2 and 3 spoken by kokoro in order, chunk 1 not repeated (router level and through the pipeline with a fake speaker)"
    status: tested
  - id: D4
    description: "Disabled engine never selected; unregistered engine skipped; cartesia only for big moments; chatterbox only by its policy callable"
    status: tested
  - id: D5
    description: "Every engine down: health speech_output down, reply loop continues, no crash"
    status: tested
  - id: D6
    description: "Tampered or wrong-checksum kokoro file is discarded and never loaded; http URLs refused"
    status: tested
  - id: D7
    description: "Real kokoro-onnx int8 on CPU: first-audio time and real-time factor"
    status: tested
  - id: D8
    description: "Disable Pocket in tts.toml, ask a question: Kokoro voice, Voice card shows Kokoro with Fallback chip, Snow mentions the change once"
    status: pending
    reason: "Human check needs speakers and the running HUD; not run by this agent"
---

# Phase 1 Plan 28: Voice router with failover Summary

Snow's voice no longer drops out: a config-driven router picks the engine per reply, and if the everyday voice fails to load or errors mid-sentence, the failed clause and the rest of the reply continue in the Kokoro British male voice.

## What was built

- `tts/router.py`: `VoiceRouter(engines, cfg, publish, gpu_ok=, clock=)`.
  - `start()` loads every enabled engine in the background; `wait_ready()` resolves as soon as the engine that would speak an everyday reply is known and fixes the playout sample rate.
  - Choice walks `[router] order`: skips engines that are disabled, not registered, ineligible (`cartesia` only for `big_moment`, `chatterbox` only when `gpu_ok()` says so, absent here) or down.
  - `speak(chunks, emotion, big_moment, push)` streams chunk by chunk; on `EngineError` (or any other exception) it marks the engine down with the error kind, publishes `voice.switch` once (from the failed engine to the one actually chosen next), and re-speaks the failed chunk and the rest. A synthesis error cools the engine down for `cooldown_s` and the everyday voice returns afterwards (voice.status republished); a load failure lasts the session. A `tried` set stops a zero cooldown from retrying a broken engine forever.
  - All engines down: `AllVoicesDown` is raised, health `speech_output` goes `down` ("No voice available"), the pipeline ends the reply cleanly and the loop goes on. Reply text still reaches the HUD (the brain publishes it, independent of voice).
  - `cancel()` stops the active engine; `spoke_with` tells the pipeline which engine produced the audio for `tts.spoken`.
- `tts/kokoro.py`: `KokoroEngine` with kokoro-onnx 0.6.1 int8, `bm_george`, speed 1.0, onnxruntime `intra_op_num_threads = 4` through `Kokoro.from_session`, `lang="en-gb"`. Synthesis per chunk in a worker thread. Files are fetched from the official `model-files-v1.0` release into gitignored `models/kokoro/` on first use, written to a `.part` file, SHA-256 checked against `config/tts.toml`, and only then moved into place (a mismatch deletes the download; an existing file that mismatches is re-fetched, never loaded). https only.
- `pipeline.py`: takes a mapping of engines, builds the router itself (like `SttRouter`), speaks through `router.speak`, carries `big_moment` from `reply.final`, and `reply_finished`/`tts.spoken` behave as before. `__main__.py` registers Pocket and Kokoro.
- `config/tts.toml` / `TtsConfig`: `[router] cooldown_s`, `[engines.kokoro]` enabled/voice/speed/threads/model_url/voices_url/model_sha256/voices_sha256.

## Measurements (this laptop, CPU, 4 intra-op threads, real model)

| What | Result |
|------|--------|
| Model load (files present, checksum + session) | 1.0 s |
| First call, "Well, I think so, yes." (1.94 s audio) | 5.19 s, RTF 2.67 (cold: includes first-use warm-up) |
| Warm calls | 1.96 to 2.11 s for 1.94 s of audio (RTF 1.01 to 1.09); 4.02 s for 3.71 s (RTF 1.08) |

Honest reading: Kokoro runs at about real time on this CPU, same as the research figure. Each clause is synthesized whole, so the first Kokoro audio arrives roughly 2 s after the clause is handed over (5 s on the very first call of a session), and between clauses there can be small gaps because the next clause takes about as long to make as the previous one takes to play. Pocket (RTF 0.4, 0.2 s to first audio) is far better; Kokoro is a last resort, as designed. No threshold was loosened.

## Deviations from Plan

1. **[Rule 3 - Blocking] `src/snow/voice/__main__.py` edited** (not in files_modified): the worker must register Kokoro with the pipeline or the router has nothing to fail over to.
2. **[Rule 3 - Blocking] `tests/voice/test_tts_pipeline.py` edited** (not in files_modified, but named in the plan's verify command): its setup assigned a bare engine to the pipeline; it now wraps the fake engine in a `VoiceRouter`, and waits on `_tts_ready` instead of the removed `_tts_state`, and joins the event queue before reading VoiceStatus (the router announces after ready, not synchronously at start).
3. **`build_pipeline`/`VoicePipeline` take `tts: Mapping[EngineName, TtsEngine]`** instead of a single engine, and the pipeline builds the router (so it can hand it `_emit`). Existing default-off behaviour is unchanged.
4. **`cooldown_s` added to `[router]`**: the plan says "marks unavailable"; a permanent mark after one transient error would waste the everyday voice, so the stt_router cooldown pattern was mirrored.

No contract changes: VoiceSwitch, VoiceStatus and HealthSubsystem already carry everything used.

## Known limits and risks

- **Emotion and big_moment reach the router only as the values known when the reply task starts.** `ReplyDelta` carries no emotion (the 01-26 limit), so streamed replies get `neutral`/`False`; replies with no deltas (acks) get the final values. Plan 01-31 (Cartesia) must solve how a big moment is known before the first clause is synthesized.
- Partial audio a failing engine already pushed for the failed chunk is not retracted, so that clause may start twice (a few hundred ms at most). Marked `shortcut:` in the router docstring.
- Kokoro at RTF about 1.0 may leave short gaps between clauses (see measurements).
- The first Kokoro use on a machine downloads about 120 MB from GitHub (network at engine load, in the voice worker). `models/kokoro/` is already populated in this worktree only.
- The one-time in-character remark (D-17) comes from the brain reacting to `voice.switch` (plan 01-16); not verified end to end here.

## Known stubs

None.

## Pending (needs the user)

- Human check (D8): set `[engines.pocket_tts] enabled = false` in `config/tts.toml`, restart Snow and ask a question. Expect the reply in the Kokoro voice, the Voice card showing "Kokoro" with the "Fallback" chip, and Snow mentioning the change once. Restore the setting afterwards. Also judge whether `bm_george` suits and whether the clause gaps are acceptable.

## Threat flags

None new. T-01-58 mitigated and tested (pinned SHA-256 for both files, verified before the file is kept or loaded, https only). T-01-SC: no packages added; `pyproject.toml` and `uv.lock` untouched. Audio stays in memory (no disk writes; no-egress and no-disk tests pass).

## Verification

- `uv run pytest tests/voice/test_tts_router.py tests/voice/test_tts_failover.py tests/voice/test_tts_pipeline.py -x -q`: 29 passed (2 slow deselected).
- `uv run pytest -m slow tests/voice/test_tts_failover.py`: 1 passed (real Kokoro, numbers above).
- `uv run pytest -x -q -m "not hardware and not network and not slow"`: 347 passed (includes test_no_egress, the no-disk proof and test_no_scripts).
- `ruff check`, `ruff format --check`, `pyright`, `python -m snow.contracts.export --check`: clean.
- Acceptance: `class VoiceRouter` and `VoiceSwitch` publication in `router.py`; `voice = "bm_george"` and `model_sha256`/`voices_sha256` in `config/tts.toml`.

## Self-Check: PASSED
