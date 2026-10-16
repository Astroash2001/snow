---
phase: 01-always-on-voice-loop
plan: 18
subsystem: voice
tags: [turn-engine, conversation-flow, wake-alone, soft-sleep, inject-wav, audio-level]

requires:
  - phase: 01-always-on-voice-loop
    provides: "Voice path from 01-13 (WakeGate, TurnEngine on audio time, GroqStt, FakeGroq MockTransport), event catalog (01-04), WAV fixtures (01-05)"
provides:
  - "TurnEngine conversation flow: follow-on turns without a re-wake, wake-alone, 45 s audio-time silence timeout, reply wait with timeout, thread-safe reply_finished/end_conversation"
  - "match_command(): whole-utterance end/sleep/mute matching from [phrases] in voice.toml"
  - "VoicePipeline: ack.requested, conversation.ended (phrase/sleep/silence), presence thinking/listening/sleeping with soft_sleep mode, audio.level (mic), on_hub_event"
  - "build_pipeline() shared by the worker and the dev tool; snow dev inject-wav <path> [--realtime]"
affects: [01-16 brain acknowledgement pool, 01-20 mute and mic resilience, 01-26 end-of-playback reply_finished, 01-29 barge-in]

commits: 2
plan_head_before: d695b375aaf4bfab6bf9aa5c7241fe14310e1fb8
plan_head_after: bcdd3db0ee16fd40febd4c83ed8402af6cfef038

actuals:
  tokens: 36000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Loop thread talks to the audio thread through a deque inbox drained at the start of feed()/on_wake()"
    - "Engine owns presence transitions; the pipeline only maps them to events"
    - "FileSource.hold paces a recording like a listening user (waits for each reply), with one capped wall wait per pending reply"

key-files:
  created:
    - src/snow/voice/devinput.py
    - tests/voice/test_turn_engine.py
    - tests/voice/test_phrases.py
    - tests/voice/test_modes.py
    - tests/voice/test_wake.py
    - tests/voice/test_stt_groq.py
  modified:
    - src/snow/voice/turn.py
    - src/snow/voice/phrases.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/config.py
    - src/snow/voice/sources.py
    - src/snow/voice/__main__.py
    - config/voice.toml
    - tests/voice/conftest.py

key-decisions:
  - "After a turn ends the engine is deaf until the reply is done (or reply_timeout_s = 20 s of audio time): Snow must not hear its own answer; plan 01-26 moves reply_finished to the end of playback"
  - "Follow-on turns are opened without a wake and keep only a 0.5 s lead-in before speech is confirmed, so 45 s of idle silence is never uploaded or fed to Smart Turn"
  - "Reply matching uses turn_id: a reply.final for another turn (a wake ack) only restarts the silence timer and never ends the wait for the pending turn"
  - "Mic level is emitted once per 512-sample chunk (31.25 per second, audio time) instead of a wall-clock throttle, so file replays and live audio behave the same; the pre-roll burst emits none"

patterns-established:
  - "Dev pipeline events carry source dev because the hub requires event.source == client role"

requirements-completed: [VOIC-05, VOIC-01]

coverage:
  - id: D1
    description: "A pause mid-thought does not end the turn (one upload with both halves); silence cap and Smart Turn agreement unchanged from 01-13"
    requirement: VOIC-05
    verification:
      - kind: test
        ref: "tests/voice/test_modes.py#test_mid_thought_pause_is_one_turn"
        status: pass
      - kind: test
        ref: "tests/voice/test_voice_turn.py#test_mid_thought_pause_stays_one_turn"
        status: pass
    human_judgment: false
  - id: D2
    description: "Conversation stays open across turns with one wake (two turns, five presence transitions), ends on 45 s audio-time silence with the timer paused while a reply is pending"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_modes.py#test_two_turns_in_one_conversation"
        status: pass
      - kind: test
        ref: "tests/voice/test_turn_engine.py#test_silence_ends_the_conversation_after_45_s_of_audio_time"
        status: pass
      - kind: test
        ref: "tests/voice/test_turn_engine.py#test_silence_timer_is_paused_while_a_reply_is_pending"
        status: pass
    human_judgment: false
  - id: D3
    description: "Wake phrase alone emits exactly one ack.requested and the conversation stays open; wake plus command emits none"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_modes.py#test_wake_alone_asks_for_one_ack_and_stays_open"
        status: pass
      - kind: test
        ref: "tests/voice/test_modes.py#test_wake_with_a_command_requests_no_ack"
        status: pass
    human_judgment: false
  - id: D4
    description: "'that's all' ends the conversation (phrase), 'go to sleep' enters soft sleep, mute is matched and ignored; none publish transcript.final; 'mute the speaker in the call' is a normal request (T-01-24)"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_modes.py"
        status: pass
      - kind: test
        ref: "tests/voice/test_phrases.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "audio.level (mic) only while listening, at most one per 512-sample chunk, none while asleep, thinking or in the wake pre-roll"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_turn_engine.py#test_mic_levels_only_while_listening_and_at_most_32_per_second"
        status: pass
      - kind: test
        ref: "tests/voice/test_modes.py#test_mic_level_only_while_listening"
        status: pass
    human_judgment: false
  - id: D6
    description: "snow dev inject-wav drives the real pipeline from a WAV as role dev; wake fixture fires once, TV negative never; Groq request shape and error mapping covered"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_wake.py"
        status: pass
      - kind: test
        ref: "tests/voice/test_stt_groq.py"
        status: pass
    human_judgment: false
  - id: D7
    description: "Live check: wake with 'Hey Jarvis' alone, ask two questions with a mid-sentence pause, say 'that's all', wake again and say 'go to sleep'; HUD shows the matching states"
    requirement: VOIC-01
    verification: []
    human_judgment: true
    rationale: "Needs the live microphone and a real Groq key; not performed per instructions (privacy, no real audio or keys in automation)"

duration: 55min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 18: Natural Conversation Flow Summary

**The voice worker now holds a conversation: wake once, speak follow-on turns without re-waking, end by "that's all", soft-sleep by "go to sleep" or after 45 s of silence, and a lone wake phrase asks the brain for an acknowledgement.**

## Accomplishments

- TurnEngine (audio time only, no wall clock): follow-on turns, wake-alone via `on_wake_alone`, silence timeout `silence_timeout_s` (paused while a reply is pending), `reply_timeout_s` (20 s) for replies that never come, presence transitions (listening, thinking, sleeping) and per-chunk `on_level`.
- `match_command` in `phrases.py`: whole normalized utterance of at most 6 words, optional leading "snow", phrases from the new `[phrases]` table. Matched commands never become `transcript.final`.
- Pipeline: `ack.requested`, `conversation.ended` (phrase, sleep, silence), `presence.state` mode `soft_sleep` after "go to sleep" and `awake` again on the next wake, `audio.level` (mic), `on_hub_event` ends the wait when the brain's `reply.final` for the pending turn arrives.
- `snow dev inject-wav <path> [--realtime]` (`devinput.py`): real pipeline from a WAV as role `dev`, paced so each reply arrives before the next turn is heard, 60 s cap, prints you/snow lines.
- Tests: 44 new voice tests (61 in `tests/voice`), all on CPU with real wake, VAD and Smart Turn models for the fixture tests and scripted VAD for flow timing. Full suite passes (`ruff check`, `ruff format --check`, `pyright` clean).

## Task Commits

1. **Task 1 (tracer): natural conversation flow** - `46b69a2` (feat)
2. **Task 2: developer WAV input and wake / Groq STT edge tests** - `bcdd3db` (feat)

Tracer gate: `<verify>` for task 1 re-run end to end (`tests/voice/test_turn_engine.py test_phrases.py test_modes.py`) passed before task 2.

## Deviations from Plan

**1. [Rule 3 - Blocking] respx replaced by the fail-closed FakeGroq MockTransport**
- Plan task 2 says "respx Groq route"; respx cannot patch openai 3.29 (httpx2). All Groq tests use `FakeGroq` from `tests/voice/conftest.py`; any unrouted request fails the test.

**2. [Rule 3 - Blocking] `sources.py` and `tests/voice/conftest.py` edited (not in files_modified)**
- `FileSource` gained an optional public `hold` callable (one capped 30 s wall wait per pending reply). Without it a recording runs far ahead of the (mock or real) reply and the second turn of `conversation_two_turns.wav` arrives while the engine is still deaf waiting for the first reply, which would make that test nondeterministic and make multi-turn `inject-wav` useless.
- `conftest.py`: `FakeGroq.texts` (per-request replies), `FakeHub` can answer transcripts with `reply.final`, `run_fixture(..., replies=True)`, engine receives `cfg.conversation`. Existing tests unchanged.

**3. [Design] `build_pipeline()` added to `pipeline.py`** so `__main__` and `devinput` share one wiring (wake gate, VAD, Smart Turn). `ConversationConfig` gained `reply_timeout_s` (default 20) and `VoiceConfig` a `phrases` table; `TurnEngine` takes `conversation=` keyword (defaults to 45 s / 20 s), so older callers still work.

**4. [Scope note] inject-wav exit rule:** it exits when the file (plus its 2 s silence tail) has played and every transcript is published, or after 60 s. It does not exit earlier on `conversation.ended`; the remaining audio is only silence.

**5. [Plan interpretation] audio.level rate:** emitted per 512-sample chunk in audio time (31.25 per second) instead of a 31 ms wall-clock throttle; this satisfies "no more than 32 per second" and behaves the same for files and live audio.

No contracts, hub, brain, config package, logging, cli, root conftest, pyproject or uv.lock edits were needed. `cli.py` already dispatched `dev inject-wav` to `snow.voice.devinput:main`.

## Notes for downstream plans

- 01-16 brain: `ack.requested` carries no turn id; the brain's ack `reply.final` should leave `turn_id` empty (or another id) so it only restarts the silence timer and never ends the wait for a real turn.
- 01-20: `mute` is matched, logged nowhere and released immediately (engine returns to listening); wire the actual mute there. `State.MUTED` handling is still untouched.
- 01-26: call `engine.reply_finished()` at the end of playback instead of on `reply.final`; the hook is `VoicePipeline.on_hub_event`.
- 01-29: while a reply is pending the engine is deaf by design; barge-in must lift that.
- Environment: one long full-suite run reported failures (a 4 hour wall-clock jump in the pytest summary, stale locked `.pytest_tmp` files from an orphaned test process). Re-runs of the voice, hub and brain suites and a full `tests` pass were clean.

## Pending Human Check (not performed, per instructions)

With headphones and a stored Groq key, run `uv run snow run`: say "Hey Jarvis" alone and wait (Snow should request an acknowledgement and keep listening); ask two questions without re-waking, pausing mid-sentence once; say "that's all" (HUD returns to standing by); wake again and say "go to sleep" (HUD shows the asleep state). The microphone was never opened and no audio or key left the machine.

## Known Stubs

None. `mute` handling is intentionally deferred to plan 01-20 (matched and released, no state change).

## Threat Flags

None. T-01-24 mitigated: whole-utterance matching, at most 6 words, tested for "mute the speaker in the call" and over-long utterances. T-01-SC: no new packages.

## Self-Check: PASSED

- Created files exist: devinput.py, test_turn_engine.py, test_phrases.py, test_modes.py, test_wake.py, test_stt_groq.py.
- Commits `46b69a2` and `bcdd3db` are ancestors of HEAD.
- Acceptance: `match_command` defined and no `in text` substring test; `turn.py` has `on_wake_alone` and no `time.time`/`time.monotonic`; `voice.toml` has `[phrases]`; `uv run snow dev inject-wav --help` exits 0; `uv run pytest tests/voice -q` 61 passed.
