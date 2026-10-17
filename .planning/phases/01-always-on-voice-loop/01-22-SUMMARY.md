---
phase: 01-always-on-voice-loop
plan: 22
subsystem: voice
tags: [moonshine, stt, partials, fallback, router, cooldown]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "moonshine-voice 0.1.5 approved by the user (01-02), Groq STT with SttUnavailable kinds and the fail-closed FakeGroq transport (01-13), stt.status and transcript.partial events (01-04), speech_to_text health row and hard mute (01-20)"
provides:
  - "LocalStt: Moonshine streaming STT on CPU in one worker thread (start_turn, feed, partial, finish, cancel, close)"
  - "transcript.partial at most every 300 ms during a turn, wake phrase stripped, carrying the turn id"
  - "SttRouter: Groq primary with a 2.5 s deadline, Moonshine local final otherwise, per-reason cooldowns, stt.status on every source change"
  - "speech_to_text health detail: Groq cloud / Local fallback / Local only (no Groq key)"
affects: [01-23 HUD Voice card (reads stt.status and the health detail), 01-16 brain (one in-character mention of the fallback from stt.status), 01-30 wake word (strip patterns), 01-26 TTS]

commits: 2
plan_head_before: 579add4d2dc907a7c9575e2a7553db05695bf75e
plan_head_after: ab8682d37a18b76197ea67094edcfbc31e062bd4

actuals:
  tokens: 50000
  tasks: 2
  commits: 2

tech-stack:
  added: ["moonshine-voice==0.1.5 (exact pin, hash-locked in uv.lock)"]
  patterns:
    - "Local model behind a queue and one worker thread; the audio thread only enqueues and reads a lock-guarded string"
    - "Source chain with cooldowns on the event loop (SttRouter), fed a precomputed local Future so fallback adds no wait"
    - "Pipeline keeps the last 640 ms so a follow-on turn (no wake phrase) can start the local model late without losing its first word"

key-files:
  created:
    - src/snow/voice/stt_local.py
    - src/snow/voice/stt_router.py
    - tests/voice/test_partials.py
    - tests/voice/test_stt_router.py
    - tests/voice/test_moonshine_wer.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/snow/voice/pipeline.py
    - src/snow/voice/config.py
    - src/snow/voice/__main__.py
    - config/voice.toml
    - tests/voice/conftest.py

key-decisions:
  - "Moonshine model is `tiny` (streaming). moonshine-voice 0.1.5 publishes English streaming builds for tiny, small and medium only; `base` exists but is not streaming, so the plan's 'start with base' is not possible. Tiny gave WER 0.054, small was twice the CPU cost"
  - "Cooldowns are keyed on wall-clock seconds so retry_after_ns in stt.status is a real timestamp; tests inject a fake clock"
  - "A key stored after startup ends the no-key cooldown at the next health publish or turn (refresh()), faster than the plan's 60 s re-check"
  - "stt.status is re-announced when a hub snapshot carries none: the worker starts before the hub connects, so the startup announcement would otherwise be lost"

requirements-completed: [VOIC-04, VOIC-08]

coverage:
  - id: D1
    description: "Partials publish during a wake turn, never closer than 250 ms of audio time, wake phrase stripped, all before transcript.final, none after the turn ends, local model started exactly once"
    requirement: VOIC-08
    verification:
      - kind: test
        ref: "tests/voice/test_partials.py#test_partials_grow_with_the_turn_and_stop_at_its_end"
        status: pass
      - kind: test
        ref: "tests/voice/test_partials.py#test_wake_alone_drops_the_local_turn_without_partials"
        status: pass
    human_judgment: false
  - id: D2
    description: "Real Moonshine on wake_cmd_gap150.wav (real time) shows at least two partials before the final and the last partial shares at least half its words with it"
    requirement: VOIC-08
    verification:
      - kind: test
        ref: "tests/voice/test_partials.py#test_real_moonshine_shows_words_before_the_final"
        status: pass
    human_judgment: false
  - id: D3
    description: "Groq answers in time -> groq final, primary announced once; 429 with retry-after 30 -> local final, no Groq call inside 30 s, back to Groq after; connection error -> retried after 60 s; no key -> local only, notices a stored key"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_groq_in_time_is_the_final_and_primary_is_announced_once"
        status: pass
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_rate_limit_waits_out_retry_after_then_returns_to_groq"
        status: pass
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_unreachable_is_retried_after_sixty_seconds"
        status: pass
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_no_key_runs_local_only_and_notices_a_stored_key"
        status: pass
    human_judgment: false
  - id: D4
    description: "A Groq slower than 2.5 s costs one turn without a cooldown; three misses in a row start a 60 s unreachable cooldown; a fast answer resets the count; no local model means SttUnavailable"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_a_slow_groq_costs_one_turn_and_three_misses_start_a_cooldown"
        status: pass
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_without_a_local_model_groq_failure_is_unavailable"
        status: pass
    human_judgment: false
  - id: D5
    description: "Through the real pipeline a Groq 429 gives transcript.final with stt_source local, stt.status groq/primary then local/rate_limited with a retry time, health detail Local fallback"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_stt_router.py#test_pipeline_uses_the_local_final_when_groq_is_limited"
        status: pass
    human_judgment: false
  - id: D6
    description: "Moonshine tiny local finals on the four command fixtures have word error rate at most 0.25 (measured 0.054 over 37 words)"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_moonshine_wer.py#test_moonshine_finals_stay_within_the_word_error_bound"
        status: pass
    human_judgment: false
  - id: D7
    description: "Real microphone: the HUD live row updates with the user's words while speaking a long sentence slowly, then settles into the final line; with Wi-Fi off the Voice card shows Local (Moonshine) and words still appear, returning to Groq cloud within about a minute of reconnecting"
    requirement: VOIC-08
    verification:
      - kind: human
        ref: "01-22-PLAN.md Task 1 and Task 2 human-check"
        status: pending
    human_judgment: true
    rationale: "Needs the real microphone and the 01-23 HUD Voice card; neither was available or allowed in this run"
---

# Phase 1 Plan 22: Local Moonshine Partials and STT Router Summary

**Moonshine `tiny` streaming on CPU shows the user's words live (transcript.partial every 300 ms) and is the full fallback behind an SttRouter that gives Groq 2.5 s, honours 429 retry-after, backs off 60 s after failures, and publishes stt.status and the speech_to_text health detail on every change.**

## What was built

- **LocalStt (`stt_local.py`).** One daemon thread owns the Moonshine `Transcriber`; the audio thread only puts frames on a queue. `finish()` returns a `Future[str]` so the audio thread never waits, and `cancel()` drops a turn (wake alone, mute, conversation end). If the model cannot load, every `finish()` future fails and the router reports the turn as unhearable instead of returning silence. Model files download once into `models/moonshine/` (gitignored).
- **Partials (`pipeline.py`).** A wake turn starts the local model from the wake hit's pre-roll; a follow-on turn starts at speech start from the last 640 ms. Every frame is fed until the turn ends. Every `partial_interval_ms` of audio the pipeline asks for the words, strips the wake phrase and publishes `transcript.partial` if the text changed. Partials wait until speech is confirmed because the turn id is only known then.
- **SttRouter (`stt_router.py`).** `final(pcm, rate, local_future)` runs Groq under `final_deadline_s`; on `SttUnavailable`, a deadline miss or any other error the already-computed local final is used. 429 uses `retry-after` (default 60 s); unreachable, offline and no-key wait `cooldown_s`; three misses in a row start a 60 s `unreachable` cooldown. `stt.status` is published only when source, reason or retry time changes (primary once at start).
- **Wiring.** `__main__` builds `LocalStt`; `VoicePipeline(..., local=None)` and `build_pipeline(..., local=None)` are optional so every existing caller and test is unchanged. `transcript.final.stt_source` is the actual source. The speech_to_text health row reads the router: `Groq cloud`, `Local fallback`, `Local only (no Groq key)`; without a local model it keeps the 01-20 behaviour (`No Groq key. Run snow setup.`).

## Measurements

- Moonshine `tiny` streaming: mean 29 to 35 ms of CPU per 80 ms frame (measured through `Stream.add_audio` on the fixtures, including the periodic inference passes; the first frame costs about 0.5 s while the model warms up). That is above the plan's 20 ms trigger, but tiny is the smallest English streaming model, the work is in a worker thread and real-time factor is about 0.4.
- Moonshine `small` streaming: 58 to 71 ms per frame, not chosen.
- WER of `tiny` local finals on wake_cmd_gap0/150/600 and mid_thought_pause: 0.054 (2 errors in 37 words; "Javas" for "Jarvis" and a split sentence).
- `uv run pytest -q`: 295 passed. `uv run pytest -m slow tests/voice -q`: 2 passed. ruff check, ruff format --check, pyright: clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `base` has no streaming build**
- **Found during:** Task 1
- **Issue:** Plan said start with Moonshine base. In moonshine-voice 0.1.5 the English catalog has `tiny`/`small`/`medium` streaming builds and a non-streaming `base`.
- **Fix:** Config `[stt.local] model = "tiny"` (validated as tiny/small/medium). Task 1 still met its CPU-fallback intent: tiny is already the floor.
- **Files modified:** config/voice.toml, src/snow/voice/config.py, src/snow/voice/stt_local.py

**2. [Rule 2 - Missing critical functionality] Interface differences from the plan**
- `LocalStt.finish()` returns `Future[str]` (the plan wrote `str`) so the audio thread cannot block; `cancel()` was added for wake-alone and mute. `SttRouter(groq, cfg, publish, *, has_local, clock, on_change)` has no `local` argument; the local future goes into `final()`, as the plan's signature also shows. `refresh()` ends the no-key state as soon as a key is stored.

**3. [Rule 1 - Bug] Wake mishearing survived stripping**
- **Found during:** Task 2 WER run (local model heard "Hey, Javas,").
- **Fix:** added `javas` to the first `strip_patterns` entry in config/voice.toml.

**4. Test infrastructure.** `tests/voice/conftest.py`: `FakeHub.stt` keeps `stt.status` out of `hub.events` (like `health`), `FakeGroq.fail_with/retry_after` answer an error status, `run_fixture(local=...)`, and `FakeLocalStt` lives there. No existing assertion changed.

**5. Dependency.** `uv add moonshine-voice==0.1.5` also locks one new transitive package, `google-crc32c==1.9.0` (hash-locked, win32 only), which moonshine-voice declares. Its other dependencies (numpy, requests, sounddevice, tqdm, platformdirs, filelock) were already present. No onnxruntime conflict: moonshine bundles its own native runtime, and wake/VAD (onnxruntime 1.24) ran in the same process in every test.

**Total deviations:** 5 (1 blocking, 1 interface, 1 bug, 2 housekeeping). **Impact:** none on behaviour the plan specified.

## Tracer gate

Task 1 is the tracer. Both automated verifies (`tests/voice/test_partials.py`, fast and slow) passed at the tracer commit and again with the full suite. Its `<human-check>` needs the real microphone, which this run may not open, so it is recorded as pending below instead of a checkpoint (instruction from the orchestrator).

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None new. T-01-38 is covered by `test_a_slow_groq_costs_one_turn_and_three_misses_start_a_cooldown` and the pipeline test. T-01-SC: exact pin, hash-locked lock, installed only after 01-02's verdict. One note for the register: `LocalStt` downloads the Moonshine model from `download.moonshine.ai` the first time the worker starts (no audio is involved; later starts use the cache). The no-egress tests build the pipeline without a LocalStt, so they do not exercise that download.

## Pending human check

- Wake Snow and say a long sentence slowly: the HUD live row should update with your words while you speak, then settle into the final line (needs the 01-23 HUD row).
- Disconnect Wi-Fi, wake Snow and speak: the Voice card should show "Local (Moonshine)" with the unreachable helper and your words still appear as a final line. Reconnect: within about a minute the source returns to "Groq cloud".
- Known real-world edge to look at: a partial may briefly show a lone "Hey" if the model hears only the start of the wake phrase.
- The dev tool `snow dev inject-wav` does not build a LocalStt, so it shows no partials and has no local fallback.

## Self-Check: PASSED

Files exist (stt_local.py, stt_router.py, test_partials.py, test_stt_router.py, test_moonshine_wer.py); commits 1b7b96e and ab8682d are on the branch; all acceptance criteria verified (`moonshine-voice==0.1.5` in pyproject.toml, `class LocalStt` and `def partial`, `partial_interval_ms = 300`, `class SttRouter` and `final_deadline_s`, `final_deadline_s = 2.5`).
