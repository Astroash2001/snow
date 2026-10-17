---
phase: 01-always-on-voice-loop
plan: 20
subsystem: voice
tags: [mute, privacy, microphone-resilience, health, no-egress, wake-latency]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "Event catalog and cmd.mute.set (01-04), hub mute persistence (01-04/01-13), voice path and FakeGroq (01-13), conversation flow where `mute` was matched but ignored (01-18)"
provides:
  - "Hard mute: the 'mute' phrase closes the audio source (mic indicator off); unmute only through cmd.mute.set (HUD/tray)"
  - "Fail-safe startup: the worker opens the mic only after the first hub snapshot says muted=false; no snapshot, no mic"
  - "MicSource reopen with backoff (1 s doubling to 30 s) on PortAudioError and on a stream that ends by itself; health.subsystem wake_word restarting/running"
  - "health rows wake_word and speech_to_text (down + 'No Groq key. Run snow setup.' when no key), re-sent on every hub (re)connect"
  - "Proof tests: no idle egress, no audio on disk, wake.detected hub latency p95 <= 50 ms"
affects: [01-22 local STT fallback (extends the speech_to_text row), 01-19 HUD (paints muted/restarting), 01-26 end-of-playback, 01-29 barge-in]

commits: 2
plan_head_before: a6661b264be7f3de4f010da2f9a5e79d0beb24a6
plan_head_after: 43b522abc22a71bfb076a6a62272b1dbcf670ff3

actuals:
  tokens: 30000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Source open/close happens in exactly two places: the cmd.mute.set handler and the first-snapshot check (VoicePipeline._set_muted / on_snapshot)"
    - "Loop-side events use VoicePipeline._emit (direct queue put); audio-thread events keep _put (call_soon_threadsafe), after a sleep(0) so late hops cannot land after a muted presence"
    - "Health rows are state, re-sent on each snapshot, because a row sent while the hub is away is lost"

key-files:
  created:
    - tests/voice/test_mute.py
    - tests/voice/test_no_egress.py
    - tests/voice/test_wake_latency.py
  modified:
    - src/snow/voice/pipeline.py
    - src/snow/voice/sources.py
    - src/snow/voice/__main__.py
    - src/snow/voice/turn.py
    - src/snow/voice/wake.py
    - src/snow/voice/stt_groq.py
    - tests/voice/conftest.py
    - tests/voice/test_modes.py

key-decisions:
  - "Muting a local ring too: WakeGate.reset() and a fresh MicSource queue on open, so audio heard before a mute can never become a later pre-roll that is uploaded"
  - "A locally muted worker stays muted if a reconnect snapshot says unmuted (the hub missed our mute.changed); it re-sends mute.changed(True) instead of reopening. Only an explicit command reopens"
  - "turn.cancelled(mute) is published only for another turn or reply in flight, not for the mute command's own turn"

requirements-completed: [VOIC-01, VOIC-03, VOIC-04, HUD-03]

coverage:
  - id: D1
    description: "Saying mute closes the source, publishes mute.changed(True, voice), presence muted, conversation.ended(mute), and no transcript.final; mute inside a sentence is a normal request"
    requirement: VOIC-03
    verification:
      - kind: test
        ref: "tests/voice/test_mute.py#test_say_mute_closes_the_source_and_reaches_the_brain_never"
        status: pass
      - kind: test
        ref: "tests/voice/test_mute.py#test_mute_inside_a_sentence_does_not_mute"
        status: pass
    human_judgment: false
  - id: D2
    description: "HUD cmd.mute.set closes and reopens the source through a real in-process hub; persisted mute keeps the mic closed at restart; no hub connection keeps it closed"
    requirement: VOIC-03
    verification:
      - kind: test
        ref: "tests/voice/test_mute.py#test_hud_commands_close_and_reopen_the_source"
        status: pass
      - kind: test
        ref: "tests/voice/test_mute.py#test_restart_while_muted_never_opens_the_mic"
        status: pass
      - kind: test
        ref: "tests/voice/test_mute.py#test_no_hub_connection_keeps_the_mic_closed"
        status: pass
      - kind: test
        ref: "tests/voice/test_mute.py#test_a_lost_mute_report_is_resent_not_silently_undone"
        status: pass
    human_judgment: false
  - id: D3
    description: "Mic open failure and unplug reopen with backoff without exiting; wake_word restarting then running; speech_to_text down when no key"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_mute.py#test_mic_reopens_with_backoff_after_open_failure_and_unplug"
        status: pass
      - kind: test
        ref: "tests/voice/test_mute.py#test_health_rows_for_wake_word_and_speech_to_text"
        status: pass
    human_judgment: false
  - id: D4
    description: "No wake: zero socket connects and zero Groq requests; a wake turn: exactly one request, WAV built only in io.BytesIO, no audio file created under data/tmp/cwd/system temp"
    requirement: VOIC-01
    verification:
      - kind: test
        ref: "tests/voice/test_no_egress.py#test_no_wake_means_no_connection_and_no_groq_request"
        status: pass
      - kind: test
        ref: "tests/voice/test_no_egress.py#test_a_wake_turn_makes_exactly_one_groq_request_and_no_file"
        status: pass
    human_judgment: false
  - id: D5
    description: "wake.detected from the pipeline reaches a second hub client in <= 50 ms p95 over 50 runs"
    requirement: HUD-03
    verification:
      - kind: test
        ref: "tests/voice/test_wake_latency.py#test_wake_detected_reaches_a_second_client_within_budget"
        status: pass
    human_judgment: false
  - id: D6
    description: "Real microphone: saying mute turns the Windows microphone indicator off, speech then does nothing, and after a Snow restart the mic stays off until Unmute is clicked in the HUD"
    requirement: VOIC-03
    verification:
      - kind: human
        ref: "01-20-PLAN.md Task 1 human-check"
        status: pending
    human_judgment: true
---

# Phase 1 Plan 20: Hard Mute, Mic Resilience and Privacy Proofs Summary

**"Snow, mute" closes the microphone stream itself, the mic stays closed after a restart until a HUD or tray click, a lost microphone reopens with backoff and is reported, and tests prove idle audio makes no network call, no audio touches disk, and wake.detected reaches clients within 50 ms.**

## What was built

- **Mute (pipeline.py).** The `mute` command found in `_transcribe` calls `_set_muted(True, "voice")`: `source.close()`, `WakeGate.reset()`, `TurnEngine.mute()`, then `mute.changed(True, voice)`, `presence.state(muted)`, `turn.cancelled(mute)` if another turn or reply was in flight, and `conversation.ended(mute)`. A transcript that comes back after a mute is dropped. Unmute exists only in `on_command` (cmd.mute.set from hud/tray): reopen, `mute.changed(False, by)`, presence sleeping.
- **Startup rule (`__main__`).** `pipeline.start(listen=False)` plus `client.on_snapshot`: the source opens on the first snapshot only if `muted` is false. A muted snapshot closes it. With no hub there is no snapshot and no mic.
- **Resilience (sources.py).** `MicSource` runs its open attempt in the audio thread, catches `sd.PortAudioError`, also handles the `finished_callback` of a stream that dies by itself, retries at 1 s doubling to 30 s, and calls `on_health(ok)`; the pipeline maps that to `health.subsystem wake_word restarting ("Microphone unavailable")` and `running`. The `speech_to_text` row is `down` with "No Groq key. Run snow setup." when there is no key (01-22 adds the fallback).
- **Proofs.** `test_no_egress.py` (socket connect/create_connection recorded and refused, `wave.open` spied for write targets, audio-file listings before and after), `test_wake_latency.py` (real hub, voice client, raw HUD socket, event fired from a worker thread, ts_ns at publish vs receipt).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Pre-mute audio must not survive a mute**
- **Found during:** Task 1
- **Issue:** `WakeGate` keeps a ~2 s ring of recent frames and `MicSource` a 200-frame queue; after unmute a wake would have put audio heard before the mute into the pre-roll that is uploaded to Groq.
- **Fix:** `WakeGate.reset()` (wake.py), called on mute and unmute; `MicSource.open()` creates a fresh queue.
- **Files modified:** src/snow/voice/wake.py, src/snow/voice/sources.py, src/snow/voice/pipeline.py

**2. [Rule 3 - Blocking] Engine needs a MUTED transition, and the STT row needs a key check**
- **Found during:** Task 1
- **Issue:** `State.MUTED` existed but nothing entered it; the pipeline cannot read whether a Groq key exists.
- **Fix:** `TurnEngine.mute()/unmute()` (thread-safe inbox like `reply_finished`) in turn.py; `GroqStt.has_key` in stt_groq.py. Neither file is in the plan's `files_modified`; both changes are additive.

**3. [Rule 1 - Bug] Health rows sent before the hub connects are lost**
- **Found during:** Task 1 (test showed `send_dropped_not_connected`)
- **Fix:** rows are state, published at start and re-sent on every snapshot and every mic change.

**4. Existing tests adjusted.** `test_mute_is_matched_and_never_reaches_the_brain` (01-18) asserted the old placeholder behaviour (no conversation.ended, presence listening) and was replaced by the new test_mute.py cases. `FakeHub` in tests/voice/conftest.py now keeps health rows in `hub.health` so flow tests that assert exact event lists stay exact; `run_fixture` gained a `source_factory` argument and `Run.source`; `StubSource`, `make_pipeline`, `until` moved there for reuse.

**5. [Process] A `taskkill //F //IM python.exe` I ran to clear a hung test of mine would also have killed Python processes of the parallel executors (01-17, 01-19) if they were running tests at that moment.** If either reports a sudden test crash, that is the cause; re-run.

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None. No new network surface; T-01-21, T-01-22 and T-01-25 are covered by the tests above.

## Pending human check

Wake Snow with the real microphone and say "mute": the Windows microphone indicator should disappear, speech should do nothing, and after restarting Snow the mic should stay off until Unmute is clicked in the HUD. Not performed (no real microphone use allowed in this run).

## Verification run

`uv run pytest -m "not hardware and not network"`: 273 passed. `uv run ruff check`, `ruff format --check`, `uv run pyright`: clean.

## Self-Check: PASSED

Files exist (tests/voice/test_mute.py, test_no_egress.py, test_wake_latency.py); commits 423f482 and 43b522a are on the branch.
