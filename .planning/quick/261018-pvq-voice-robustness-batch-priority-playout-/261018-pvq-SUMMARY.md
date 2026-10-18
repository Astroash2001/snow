---
phase: quick-261018-pvq
plan: 01
subsystem: voice
tags: [windows-qos, supervisor, playout, groq-stt, whisper, robustness]
requires: [quick-261018-glq]
provides:
  - raise_priority (HighQoS + ABOVE_NORMAL) for the voice worker and the hub
  - resume-aware supervisor with slow warning, longer kill timeout and stall stacks
  - playout re-buffering with fades, synthesis RTF tracking and clause hold
  - Groq verbose_json request, silent and too-short turn filter, per-turn level logs
affects: [voice, hub]
tech-stack:
  added: []
  patterns: [ctypes SetProcessInformation, faulthandler re-armed per heartbeat, EWMA RTF]
key-files:
  created:
    - src/snow/common/priority.py
    - tests/test_process_hardening.py
    - tests/voice/test_playout.py
    - tests/voice/test_turn_filter.py
    - tests/hardware/test_pocket_rtf.py
  modified:
    - src/snow/hub/supervisor.py
    - src/snow/hub/__main__.py
    - src/snow/common/hubclient.py
    - src/snow/voice/__main__.py
    - src/snow/voice/playout.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/stt_groq.py
    - src/snow/voice/tone.py
    - src/snow/voice/config.py
    - src/snow/voice/tts/config.py
    - config/snow.toml
    - config/tts.toml
    - config/voice.toml
    - tests/hub/test_supervisor.py
    - tests/voice/conftest.py
    - tests/voice/test_stt_groq.py
key-decisions:
  - "Silent-turn thresholds ship as Whisper's own pair (0.6 / -1.0), not the gap study's tighter 0.4 / -0.5, because the mic sits 12-18 dB under reference and a dropped real command costs more than a rare hallucination"
  - "tts_playout and groq_stt log lines carry numbers and word counts only (D-18)"
requirements-completed: [CORE-02, SPCH-03, SPCH-04, VOIC-04]
status: complete
commits: 3
plan_head_before: 58819701af2313053d60aca8f2d73573da177b6c
plan_head_after: b1349bd84f12e2e4efc4e5bcbf2365b8b7a71866
actuals:
  tokens: 60000
  tasks: 3
  commits: 3
completed: 2026-10-19
---

# Phase quick-261018-pvq Plan 01: Voice robustness batch Summary

Voice worker and hub run HighQoS at ABOVE_NORMAL, the supervisor survives laptop sleep and dumps stacks before a kill, playout fades and re-buffers instead of going silent when synthesis falls behind, and Groq turns that are silent or too short get no reply.

(`commits: 3` counts the three task commits made before this SUMMARY; the SUMMARY commit follows.)

## What was built

**Task 1 - process level** (commit 7a0b2a9)
- `snow.common.priority.raise_priority()`: `SetProcessInformation(ProcessPowerThrottling=4)` with ControlMask EXECUTION_SPEED and StateMask 0 (HighQoS), plus psutil `ABOVE_NORMAL_PRIORITY_CLASS`. Never raises; failures log `process_priority_failed`. Called in `snow.voice.__main__` and the hub `main()` (after the single-instance mutex).
- Supervisor: `SupervisorConfig` (`slow_after_s` 6, `hang_after_s` 20, `sleep_gap_s` 3) from `snow.toml [supervisor]`. A tick gap above `sleep_gap_s` logs `hub_resumed` and resets all heartbeats once. `worker_slow` is logged once at 6 s and re-armed by a beat; kill at 20 s.
- Supervised workers get `SNOW_STALL_DUMP_S`; `HubClient._heartbeat` re-arms `faulthandler.dump_traceback_later` after each beat and cancels it when the session ends, so a stalled worker writes its stacks to `logs/<worker>.err`.

**Task 2 - playout** (commit db82f4b)
- Underrun while not ended: last 5 ms fade out, `_playing` off, threshold becomes `rebuffer_ms` (250 ms), fade in on resume, `underruns += 1`. Fades are applied before `on_render`, so the echo reference equals the speaker output.
- `clause_done(synth_s)` keeps an EWMA RTF (weight 0.5; first measurement taken as is). Above `hold_rtf` (0.7) a clause plays only once complete.
- Pipeline calls `clause_done` after each clause is synthesized and logs `tts_playout turn_id= underruns= rtf= hold=` per spoken reply.
- Hand-run `tests/hardware/test_pocket_rtf.py` (battery A/B of Pocket RTF with and without `raise_priority`), collected only.

**Task 3 - Groq and turn filter** (commit b1349bd)
- Groq request: `verbose_json`, `temperature=0`, vocabulary prompt (omitted when empty). A turn is silent when every segment has `no_speech_prob >= 0.6` and `avg_logprob <= -1.0` (inclusive); no segments fails open.
- `tone.voiced_level(pcm, rate)` shared with `ToneAnalyzer.analyze` (outputs unchanged). `_transcribe` logs `turn_audio` (voiced_s, dbfs), drops turns under `min_voiced_s` 0.3 s before any Groq request (`turn_dropped reason=too_short`), and logs `turn_heard` word counts.

## Gate results

| Gate | Result |
|------|--------|
| `uv run pytest -q -m "not hardware and not gpu and not network"` | 491 passed, 1 skipped, 7 deselected |
| `uv run ruff check src tests` | pass |
| `uv run ruff format --check src tests` | pass |
| `uv run pyright` | 0 errors |
| `uv run python -m snow.contracts.export --check` | pass (no contract change) |
| `uv.lock` / `pyproject.toml` | unchanged |
| `tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env` | passed in this worktree (the known single-instance-lock error did not occur) |
| `tests/hardware/test_pocket_rtf.py --collect-only` | 1 test collected, not run |

GetProcessInformation readback worked on this OS: after `raise_priority()` it reports `(ControlMask, StateMask) = (1, 0)`, and psutil reports ABOVE_NORMAL, both proven in a real hidden child process. The same child proves the faulthandler dump ("most recent call first") reaches stderr.

## Deviations from Plan

**1. [Rule 1 - Bug] `VoicePipeline.wait_done` lost a command answered by the last transcript**
- **Found during:** Task 3 full-suite run (`tests/voice/test_modes.py::test_thats_all_ends_the_conversation_without_a_transcript` failed when run first in a process, and in the full suite).
- **Issue:** `wait_done` drained the turn engine's inbox once, before waiting for transcript tasks. A "that's all" command is appended to the inbox by the transcript task and, with the extra latency before it, was never drained. The ConversationEnded event also hops onto the loop via `call_soon_threadsafe`.
- **Fix:** drain again after the tasks finish, then `await asyncio.sleep(0)` before joining the queue. This is a dev/file-replay helper, not on the live audio path.
- **Files modified:** `src/snow/voice/pipeline.py`
- **Commit:** b1349bd

**2. [Rule 3 - lint] `SupervisorConfig` default argument**
- `timing: SupervisorConfig | None = None` with `timing or SupervisorConfig()` instead of a call in the default (ruff B008). Same behaviour.

**3. Test-only detail**
- In `test_playout.py` the held-clause tests pump 51 blocks, not 50: a queue that is exactly empty at a block boundary only counts as an underrun on the next callback, which is correct behaviour but must be reflected in the test.

## Known Stubs

None.

## Threat Flags

None. No new endpoints or trust boundaries. The faulthandler dump holds file, line and function names only; the new log lines carry numbers, ids and word counts, and `test_stt_groq.py` / `test_playout.py` assert the transcript and reply text never appear in `caplog.text`.

## Notes for the user

- The silent-turn pair is Whisper's canonical 0.6 / -1.0, deliberately looser than the study's 0.4 / -0.5; tune it from the `groq_stt` lines in `voice.log`.
- The 3 s resume gap also fires if the hub is frozen by heavy load for more than 3 s; that only defers one hang verdict (a silent worker is still killed `hang_after_s` later).
- A truly hung voice worker now takes about 20 s to be restarted instead of 6 s (accepted, T-pvq-03).

## Human checks (run by the user after merge, not by the executor)

Logs are in %LOCALAPPDATA%\Snow\logs.
1. Battery A/B (priority): unplug the laptop and leave Snow running and idle. Run `uv run pytest -m hardware tests/hardware/test_pocket_rtf.py -s -q` and report both RTFs. Boosted should be equal or lower. Then talk to Snow on battery for a few replies: voice.log `tts_playout` lines should show underruns=0 and rtf well under 0.7. Worker start lines should show `process_priority qos=high priority=above_normal` in voice.log and hub.log.
2. Sleep/resume: with Snow running, put the laptop to sleep for 2+ minutes, then wake it. hub.log should show `hub_resumed gap_s=...`, with no `worker_hung` and no `worker_exited ... cause=hang` after it. Snow should answer "Hey Jarvis" right after wake without a restart.
3. Short sentences: say several short commands ("what time is it", "you are up buddy") and one-word answers ("yes", "no") in a conversation. Each should be recognised; none should hit `turn_dropped reason=too_short` or `groq_stt ... silent=True`. Report any that did, with their voiced_s, dbfs, no_speech_prob and avg_logprob values, so the thresholds can be tuned.
4. Noise: cough or tap the desk during a conversation. Snow should stay silent, with `turn_dropped` or `silent=True` in voice.log.
5. Underrun feel: during a long reply while the CPU is busy (for example a build running), gaps, if any, should fade rather than click, and Snow should keep speaking to the end.

## Self-Check: PASSED

- Files: priority.py, test_process_hardening.py, test_playout.py, test_turn_filter.py, test_pocket_rtf.py all present.
- Commits 7a0b2a9, db82f4b, b1349bd are ancestors of HEAD; `git rev-list --count` from the base is 3.
