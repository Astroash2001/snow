---
phase: 01-always-on-voice-loop
plan: 13
subsystem: voice
tags: [openwakeword, silero-vad, smart-turn, groq-whisper, pre-roll, audio-thread]

requires:
  - phase: 01-always-on-voice-loop
    provides: "HubClient and event catalog (01-03, 01-04), audio fixtures and openWakeWord model-path note (01-05), secrets and logging (01-11), supervisor heartbeat contract (01-14)"
provides:
  - "python -m snow.voice worker: MicSource -> WakeGate -> TurnEngine -> GroqStt -> hub events"
  - "WakeGate: openWakeWord ONNX on CPU, RAM-only 2 s ring, pre-roll of preroll_frames+1 frames, patience and refractory"
  - "TurnEngine: framework-free SLEEPING/AWAKE/MUTED state machine on audio time, wake-alone detection, Smart Turn agreement with a 3 s silence cap"
  - "GroqStt.transcribe: in-memory WAV to whisper-large-v3-turbo, SttUnavailable(no_key, rate_limited, unreachable, offline)"
  - "config/voice.toml and VoiceConfig (audio, wake, turn, conversation, stt.groq)"
affects: [01-18 conversation flow, 01-20 mute and mic resilience, 01-22 STT router and local fallback, 01-29 barge-in, 01-30 wake word training]

commits: 1
plan_head_before: 888c91996a3a2d0be2175ed6ee0201e2b9a38076
plan_head_after: c67325d57127776e905bc33c19224bc1025228f4

actuals:
  tokens: 28000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Only vad.py imports Pipecat; the rest of the voice code is framework-free and the Pipecat frame pipeline is not used"
    - "Audio thread to event loop through one asyncio.Queue fed by call_soon_threadsafe, so events keep order"
    - "Engine is driven by samples processed, never the wall clock, so files and the pre-roll burst behave like live audio"
    - "Network faked with a fail-closed httpx2.MockTransport injected into GroqStt"

key-files:
  created:
    - config/voice.toml
    - src/snow/voice/__init__.py
    - src/snow/voice/__main__.py
    - src/snow/voice/config.py
    - src/snow/voice/phrases.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/sources.py
    - src/snow/voice/stt_groq.py
    - src/snow/voice/turn.py
    - src/snow/voice/vad.py
    - src/snow/voice/wake.py
    - tests/voice/__init__.py
    - tests/voice/conftest.py
    - tests/voice/test_voice_turn.py
    - tests/voice/test_units.py
  modified: []

key-decisions:
  - "Smart Turn is asked once per stretch of silence (at stop_secs) and its audio is cleared after an 'incomplete' answer. Measured on mid_thought_pause: with the earlier words kept the final sentence scored 0.14 to 0.23 complete (turn only ended at the 3 s cap); alone it scores 0.87 to 0.93, so the turn ends 0.2 s after the last word and the pause in the middle still does not split the turn"
  - "EndOfTurn bypasses Pipecat's append_audio/analyze_end_of_turn (wall-clock timestamps, async executor) and calls the analyzer's _predict_endpoint on audio the adapter holds, so recorded files behave like live audio"
  - "Pre-roll audio is kept in the turn but not counted as speech: the wake model fires at the end of the wake phrase, so its tail would otherwise look like the user's command and defeat wake-alone detection"
  - "vad_stop_sample is an offset into the turn's pcm (pre-roll start = 0), not absolute stream time"
  - "TurnEngine.events defaults to a NullEvents object and VoicePipeline assigns itself, which breaks the engine/pipeline construction cycle without changing the plan's VoicePipeline signature"
  - "Wake model files cache in the gitignored repo models/openwakeword folder (same location plan 01-05 used) and download once through openwakeword.utils.download_models"

patterns-established:
  - "Hub events from the audio thread: _put(EventClass, **fields) builds with ts_ns, source=voice and the conversation correlation_id, then queues on the loop"

requirements-completed: [VOIC-01, VOIC-04]

coverage:
  - id: D1
    description: "Wake phrase detected locally on CPU: wake.detected, conversation.started and presence.state(listening) are published first, from the audio thread, in order"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_voice_turn.py#test_wake_plus_command_becomes_one_stripped_transcript"
        status: pass
    human_judgment: false
  - id: D2
    description: "Wake phrase plus command in one breath: pre-roll keeps the first command word, upload is at least command duration plus 0.3 s, wake phrase stripped from transcript.final (stt_source groq)"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_voice_turn.py#test_wake_plus_command_becomes_one_stripped_transcript"
        status: pass
    human_judgment: false
  - id: D3
    description: "No audio reaches Groq before a wake phrase (30 s TV negative sends nothing) and a lone wake phrase sends nothing"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_voice_turn.py#test_no_audio_leaves_the_pc_without_the_wake_phrase"
        status: pass
      - kind: test
        ref: "tests/voice/test_voice_turn.py#test_wake_phrase_alone_sends_nothing"
        status: pass
    human_judgment: false
  - id: D4
    description: "A 1.2 s mid-thought pause stays one turn with both halves in one upload (VOIC-05 groundwork)"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_voice_turn.py#test_mid_thought_pause_stays_one_turn"
        status: pass
    human_judgment: false
  - id: D5
    description: "Groq errors map to SttUnavailable (429 with retry-after, 5xx, 401, missing key never touches the network); 3 s silence cap ends a turn Smart Turn keeps open"
    requirement: VOIC-04
    verification:
      - kind: test
        ref: "tests/voice/test_units.py"
        status: pass
    human_judgment: false
  - id: D6
    description: "Live microphone path with a real Groq key: say 'Hey Jarvis, what is the capital of France?' and see the You row and Snow's text reply in the HUD"
    requirement: VOIC-01
    verification: []
    human_judgment: true
    rationale: "The plan's human-check needs a live mic and a real Groq key; not performed per instructions (privacy, no real audio or keys in automation)"

duration: 55min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 13: Voice Input Path Summary

**Local openWakeWord gate with RAM-only pre-roll, a Silero + Smart Turn v3.2 turn engine running on audio time, and one in-memory WAV to Groq whisper-large-v3-turbo that becomes a wake-stripped `transcript.final` the brain answers.**

## Accomplishments

- `python -m snow.voice` loads `config/voice.toml`, connects a `HubClient(role="voice")` (its 2 s heartbeat satisfies the 01-14 supervisor's 6 s window) and runs `VoicePipeline` on `MicSource`.
- Wake: `hey_jarvis` ONNX on CPU, 2 consecutive frames at or above 0.5, 1.5 s refractory, model reset after a hit. The hit carries the last 5 frames (about 400 ms including the detecting frame) as pre-roll.
- Turn: pre-roll is replayed into the turn buffer, speech needs 0.2 s above VAD 0.5 after the wake point, a turn ends on 0.2 s of silence plus Smart Turn "complete", a 3 s silence cap, or 30 s total. No speech within 1.0 s of the wake calls `on_wake_alone` and sends nothing.
- Measured on the 01-05 fixtures (CPU, file playback): `wake_cmd_gap0/150/600` end 0.26 s after the last spoken word; `mid_thought_pause` stays one 5.8 s turn and ends 0.2 s after the final word; `wake_only` gives wake-alone 1.04 s after the hit and no Groq call; `tv_negative` (30 s) fires no wake and sends nothing.
- Groq: stdlib `wave` into `io.BytesIO`, `AsyncOpenAI(max_retries=0, timeout=8)`, `language=en`, `response_format=json`; 429 carries `retry-after`, connection/timeout/5xx map to `unreachable`, 401/403 or a missing key to `no_key`. Transcribe failures are logged by kind only and drop the turn (the local fallback is plan 01-22).
- Full suite: 182 passed. `ruff check src tests` and `pyright` (strict) clean.

## Task Commits

1. **Task 1 (tracer): wake phrase plus a question becomes a transcript Snow answers** - `c67325d` (feat)

Tracer gate: `<verify>` (`uv run pytest tests/voice/test_voice_turn.py -x -q`, `uv run pyright`) re-run end to end before finishing, passed.

## Deviations from Plan

**1. [Rule 3 - Blocking] respx replaced by a fail-closed httpx2.MockTransport**
- **Found during:** Task 1 (tests)
- **Issue:** The plan asks for a respx route for `POST /openai/v1/audio/transcriptions`; openai 3.29 runs on httpx2, which respx cannot patch.
- **Fix:** `GroqStt` takes an optional `transport`; `tests/voice/conftest.py` `FakeGroq` serves only POST `api.groq.com/openai/v1/audio/transcriptions` and records anything else as a violation that fails the test at teardown. No test can reach the real Groq API.
- **Files modified:** src/snow/voice/stt_groq.py, tests/voice/conftest.py

**2. [Rule 1 - Bug] Smart Turn kept 'incomplete' on the final sentence of a turn with an earlier pause**
- **Found during:** Task 1 (mid_thought_pause), see key-decisions for the numbers.
- **Fix:** ask once per silence and clear the model's audio after an incomplete answer. Recorded in `turn.py`.

**3. [Design note] Pipecat analyzer used through its private `_predict_endpoint`** because the public `append_audio` path stamps audio with `time.monotonic()` and `analyze_end_of_turn` is a coroutine over an executor, neither suited to the audio thread nor to faster-than-real-time files. Confined to `EndOfTurn` in `vad.py` with a pyright ignore; a Pipecat upgrade should re-run `tests/voice`.

**4. [Additions within owned files]**
- `tests/voice/test_units.py` (not in the plan's file list): phrase helpers, Groq error mapping, silence-cap check with scripted fakes.
- `WakeHit.at_sample` field and `model_files()` helper so tests can locate the wake in audio time and the model download happens once.
- `logger.remove()` in `vad.py`: Pipecat logs DEBUG to stderr through loguru by default.
- `EndOfTurn.append(pcm)` drops the plan's `is_speech` argument (it had no use once Pipecat's buffering was bypassed).

**5. Plan items intentionally left to later plans** (per the plan text): `on_conversation_end`, `on_level`, `on_turn_start`, `on_wake_alone` and `MUTED` handling are defined on the interface but only `on_wake_alone`/`on_turn_start` are called by the engine and the pipeline treats them as no-ops. Follow-on turns without a wake phrase are not opened (01-18). `barge_in_min_ms` and `silence_timeout_s` are configured but unused here.

**Total deviations:** 1 blocking (test mechanism), 1 bug fixed, 1 design note, 4 small additions. **Impact:** none on scope. No contracts, hub, brain, config, logging, cli, conftest, pyproject or uv.lock edits were needed.

## Notes for downstream plans

- `src/snow/voice/stt_groq.py` imports `httpx2` directly. It is a transitive dependency of `openai` and is not listed in pyproject (not edited here); add it if the project wants direct dependencies explicit.
- Wake model cache is `<repo>/models/openwakeword` (gitignored); the first run downloads about 9 MB from openWakeWord's official releases (feature models, VAD, `hey_jarvis`). A fresh worktree redownloads.
- `MicSource` resolves the Windows default WASAPI input and passes `WasapiSettings(auto_convert=True)`; if no WASAPI input exists it opens the PortAudio default without it. Open errors are not retried yet (plan 01-20).
- `tests/brain/test_chain.py::test_first_entry_serves_and_call_is_recorded` failed once in a full-suite run and passed on the next three runs (timing-sensitive, plan 01-03 area); not touched.

## Pending Human Check (not performed, per instructions)

- With headphones and a stored Groq key: `uv run snow run` (HUD built), say "Hey Jarvis, what is the capital of France?" into the microphone; the HUD should show a You row and then Snow's text reply. The microphone was never opened and no real key or audio left the machine during this plan.

## Known Stubs

None. `on_turn_start`, `on_wake_alone` and `on_level` on `VoicePipeline` are intentional no-op hooks for plans 01-18, 01-20 and 01-29.

## Self-Check: PASSED

- All 15 created files exist on disk; commit `c67325d` is an ancestor of HEAD.
- Acceptance: `voice.toml` has `model = "hey_jarvis"`, `silence_timeout_s = 45` and `whisper-large-v3-turbo`; `stt_groq.py` has `io.BytesIO` and `max_retries=0`; `grep "import pipecat\|from pipecat" src/snow/voice` matches only `vad.py`; `tests/voice/test_voice_turn.py` passes.
- Plan verification: `uv run pytest tests/voice -q` 17 passed; `uv run pytest -q` 182 passed; `uv run ruff check src tests` and `uv run pyright` clean.
