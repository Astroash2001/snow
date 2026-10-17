---
phase: 01-always-on-voice-loop
plan: 29
subsystem: voice
tags: [barge-in, latency, turn-timing, voic-06, spch-04]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "TurnEngine (01-13/18/20), Playout and speech orchestration (01-26), VoiceRouter (01-28), turn.cancelled / reply.interrupted / turn.timing events (01-04)"
provides:
  - "TurnEngine.set_speaking and on_barge_in: talking over an audible reply for barge_in_min_ms (250) interrupts it and opens the next turn on the audio that barged in"
  - "Pipeline interrupt: playout aborted on the audio thread, synthesis and reply cancelled on the loop, turn.cancelled(barge_in) then reply.interrupted(text actually heard)"
  - "turn.timing published after every answered turn (VAD stop, STT final, first LLM token, first engine chunk, first output sample)"
  - "[playout] assume_headphones in tts.toml / PlayoutConfig, startup warning when false"
  - "tests/hardware package and tests/hardware/test_latency.py (percentiles plus fast-primary comparison)"
affects: [01-30 wake word hardware tests, 01-33 Chatterbox, 01-31 Cartesia]

commits: 2
plan_head_before: 34dbc54efb390dab93cb9989e8ef3d709f28f74d
plan_head_after: 203acc26478f1e7317cd49ad023837fb10129def

actuals:
  tokens: 36000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Audio-thread-first interrupt: abort the speaker where the detection happens, then hop to the loop for the rest (the loop-side abort repeats it, harmless)"
    - "Chunk start offsets (samples pushed before each chunk) versus Playout.played give the heard text at sentence granularity"
    - "A bounded deque of cut-off turn ids stops late reply.delta / reply.final from restarting speech"

key-files:
  created:
    - tests/voice/test_bargein.py
    - tests/voice/test_latency_fake.py
    - tests/hardware/__init__.py
    - tests/hardware/test_latency.py
  modified:
    - src/snow/voice/turn.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/playout.py
    - src/snow/voice/tts/config.py
    - config/tts.toml
    - tests/voice/test_tts_pipeline.py

key-decisions:
  - "Barge-in detection lives in the TurnEngine (it owns VAD): the pipeline tells it when Snow is audible (set_speaking at the first output sample, cleared at drain, stop or mute)"
  - "Onset kept by an engine-owned ring of barge_in_min_ms + 300 ms of chunks, handed to the new turn (a little more than the plan's bare 300 ms, because detection fires 250 ms after the onset)"
  - "vad_stop_ns is the wall clock at the end-of-turn decision (after stop_secs and Smart Turn); the 200 ms stop_secs is therefore not inside the measured interval"
  - "A wake acknowledgement (no turn) is cut off by the next words too, but publishes no turn.cancelled and no turn.timing"

requirements-completed: [VOIC-06, SPCH-04]

coverage:
  - id: D1
    description: "300 ms of speech while speaking: playout aborted at the detection chunk (0 ms after, limit 150 ms), router/engine cancelled, turn.cancelled(barge_in) before reply.interrupted, presence listening"
    status: tested
  - id: D2
    description: "reply.interrupted.spoken_text is chunk 0 plus the partly played chunk 1 and excludes the chunk still being synthesized"
    status: tested
  - id: D3
    description: "200 ms of speech over Snow does not barge in"
    status: tested
  - id: D4
    description: "Interrupting speech becomes the next user turn with every speech chunk, onset included, in its audio"
    status: tested
  - id: D5
    description: "Barge-in on the first 20 ms block of a reply cancels the whole reply and nothing after the cut is synthesized"
    status: tested
  - id: D6
    description: "Late deltas / final of the cut-off turn do not start speech again"
    status: tested
  - id: D7
    description: "turn.timing carries all five timestamps in order; with zero-latency fakes the pipeline adds under 100 ms"
    status: tested
  - id: D8
    description: "Real hardware: 20 turns, VAD stop to first sample p50 <= 1.0 s and p95 <= 1.6 s; Groq gpt-oss-120b versus Experiential deepseek-v4-flash time to first audio"
    status: pending
    reason: "Needs the real speaker, the stored Groq and Experiential keys and the network; not run by this agent (no hardware tests allowed)"
  - id: D9
    description: "With headphones, ask for a long answer and talk over it: Snow stops at once, listens, HUD shows the reply dimmed with the Interrupted chip"
    status: pending
    reason: "Human check; needs a person, headphones and the running HUD"
---

# Phase 1 Plan 29: Barge-in and latency measurement Summary

Talking over Snow for 250 ms now silences it on the spot, cancels synthesis and generation, records what the user actually heard, and treats the interrupting words as the next turn; every answered turn also reports five wall-clock stamps so the one-second target can be measured.

## What was built

- **`turn.py`**: `set_speaking(bool)` (thread-safe, through the existing inbox) and `on_barge_in` on `EngineEvents`/`NullEvents`. While the engine is waiting for a reply and Snow is audible, VAD keeps running on every chunk (a ring keeps the last `barge_in_min_ms + 300 ms`). `barge_in_min_ms` of consecutive speech calls `_barge_in()`: the wait ends, a follow-on turn opens already speaking, seeded with the ring, and `on_barge_in`, `on_presence("listening")`, `on_turn_start` fire in that order. If no turn is waiting (a wake acknowledgement is playing), the same threshold on the user's own new turn fires `on_barge_in` and the turn carries on. While Snow is audible the 20 s `reply_timeout_s` no longer runs.
- **`pipeline.py`**:
  - `on_barge_in` (audio thread) reads `playout.played`, calls `playout.abort()` immediately, clears `_pending`, and hops `_interrupt(played)` to the loop. `_interrupt` works out the heard text from per-chunk start offsets, calls `_stop_speech()` (task cancel, `router.cancel()`, second abort), remembers the turn id so late `reply.delta`/`reply.final` for it are ignored, then publishes `turn.cancelled(barge_in)` and `reply.interrupted(spoken_text)`.
  - `_first_audio` tells the engine Snow is audible; `_stop_speech` tells it Snow stopped.
  - Timing: VAD stop stamped at `on_turn_end`, STT final after the router returns, first LLM token when the reply starts, first engine chunk in the push wrapper, first output sample from the playout callback's own `time_ns`. `turn.timing` is published from `_finish` and `_interrupt`.
  - Startup warning when `assume_headphones = false`.
- **`playout.py`**: `played` property (samples handed to the device in this utterance; `abort` resets it).
- **`tts/config.py`, `config/tts.toml`**: `[playout] assume_headphones = true`.
- **Tests**: `tests/voice/test_bargein.py` (3 tests), `tests/voice/test_latency_fake.py` (1), `tests/hardware/test_latency.py` (1, marked `hardware`, not run), `tests/hardware/__init__.py`.

## Results (fakes)

| What | Result |
|------|--------|
| Speaker abort after the detection chunk | 0 ms of microphone audio (limit 150 ms); same audio-thread call that detects it |
| Detection point | 8th speech chunk = 256 ms of speech (threshold 250 ms) |
| Pipeline's own share, zero-latency fakes | under 100 ms (test asserts it; passes) |
| Fast suite | 351 passed, 7 deselected; ruff, ruff format, pyright, contracts export clean |

## Real-hardware latency

NOT MEASURED. The hardware suite needs the real speaker and stored keys and was not run, per the rules for this run. No numbers are claimed. To run it (headphones on, it speaks aloud): `uv run pytest -m hardware tests/hardware/test_latency.py -x -q -s`. It prints p50/p95 for 20 turns (asserts p50 <= 1.0 s, p95 <= 1.6 s), a per-stage median breakdown (stt, llm first token, tts first audio, device) to show which stage dominates if the budget is missed, and the Groq `openai/gpt-oss-120b` versus Experiential `deepseek-v4-flash` median time to first audio (10 turns for the second). The earlier plan 01-17 probe gave Groq first-token p50 0.456 s and Experiential 1.111 s, so Groq is expected to keep the primary slot; the end-to-end comparison above still has to confirm D-30's second half.

## Deviations from Plan

1. **[Rule 3 - Blocking] `tests/voice/test_tts_pipeline.py` edited** (not in files_modified): its shared `StubTurnEngine` (also used by test_tts_failover) gained a no-op `set_speaking`, because the pipeline now calls it.
2. **[Rule 1/2 - related fix] Reply timeout paused while Snow is audible**: the 20 s `reply_timeout_s` used to end the wait mid-speech on long replies (known 01-26 limit); with barge-in the engine knows Snow is speaking, so it no longer counts.
3. **Ring is `barge_in_min_ms + 300 ms`, not 300 ms**: detection fires 250 ms after the onset, so a bare 300 ms ring leaves almost no lead-in.
4. **Hardware test uses its own `CommandSource` instead of `FileSource`**: one pipeline, one stack for all 20+ turns, each clip replayed in real time and held until the previous reply's `turn.timing` arrives. The brain is the real `BrainWorker` wired through an in-process loopback (no hub process).
5. The `fast` chain is swapped by moving the `deepseek-v4-flash` entry first in a temp copy of `models.toml` (verified to parse with `ModelsConfig`); the shipped file is untouched.
6. TDD note for Task 2: the RED run was observed (test failed with no `turn.timing`) before the stamps were written; RED and GREEN went into one commit.

No contract changes: `TurnCancelled`, `ReplyInterrupted` and `TurnTiming` were used as defined in 01-04.

## Known limits and risks

- Sentence granularity: `spoken_text` includes the whole chunk that was partly played, and ignores audio still in the device buffer (up to the prebuffer plus one 20 ms block).
- The first-audio stamp is taken in the device callback, so output-device latency (WASAPI buffer, 20-60 ms in the research budget) is not inside it.
- `vad_stop_ns` is the end-of-turn decision, after the 200 ms `stop_secs` and Smart Turn. A user-perceived "stopped talking to hearing Snow" is about `stop_secs` longer than the number reported.
- Wake hits during Snow's reply are swallowed by the engine (existing behaviour), so the frame carrying a "hey Snow" said over the reply is not counted toward barge-in; later frames still are.
- No echo cancellation: with speakers instead of headphones Snow can interrupt itself. `assume_headphones = false` only logs a warning.
- Kokoro failover can repeat a chunk's first words (01-28 limit), which makes the heard-text offsets slightly generous in that case.
- `config/voice.toml` still says `barge_in_min_ms` is "used by plan 01-29" (comment only; not touched, outside this plan's files).

## Known stubs

None.

## Pending (needs the user)

- D8: run the hardware latency suite as above and record p50/p95, the dominant stage if over budget, and the Groq versus Experiential figures here or in the phase verification.
- D9 human check: headphones on, ask Snow something with a long answer, start talking mid-sentence. Expect Snow to stop at once, listen, and the HUD to show its reply dimmed with the "Interrupted" chip.

## Threat flags

None new. T-01-42 mitigated and tested (barge-in after 250 ms, speaker aborted in the detecting call, synthesis and generation cancelled). T-01-SC: no packages added; `pyproject.toml` and `uv.lock` untouched. Audio stays in memory; no-egress, no-disk proof and test_no_scripts pass in the fast suite. No spoken literals added.

## Self-Check: PASSED
