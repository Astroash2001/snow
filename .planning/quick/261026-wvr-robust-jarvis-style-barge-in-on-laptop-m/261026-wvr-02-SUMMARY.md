---
phase: quick-261026-wvr
plan: 02
subsystem: voice
tags: [barge-in, speaker-verification, sherpa-onnx, titanet, dpapi, enrollment, hardware-test]
status: complete
requirements: [VOIC-06, SPCH-01]
key-files:
  created:
    - src/snow/voice/speaker.py
    - src/snow/voice/enroll.py
    - tests/voice/test_speaker.py
    - tests/voice/test_enroll.py
    - tests/hardware/test_bargein_loopback.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/snow/voice/tts/kokoro.py
    - tests/voice/test_tts_failover.py
    - src/snow/voice/config.py
    - config/voice.toml
    - src/snow/voice/pipeline.py
    - src/snow/voice/__main__.py
    - src/snow/cli.py
    - tests/voice/test_bargein.py
    - tests/hardware/test_echo_cancel.py
    - config/persona.toml
decisions:
  - "TitaNet-small via sherpa-onnx, SHA-256 pinned; plain numpy cosine against a DPAPI-wrapped centroid"
  - "A voiceprint file on disk gates every barge-in check: enrolled but not loaded (or load failed, or scoring error) rejects with reason speaker (amendment 1)"
  - "Only no voiceprint on disk uses the degraded words-only mode"
  - "Hardware loopback skips itself unless the mic hears a speaker burst 10 dB above the room, so a muted or headset mic cannot give a vacuous pass"
actuals:
  tokens: 90000
  tasks: 2
  commits: 3
plan_head_before: 54f9a571c9f960dc5d98ced7008744e4a6ec5253
plan_head_after: 28edb188c4e391bfca144ad57446d4c9de8970d3
---

# Phase quick-261026-wvr Plan 02: Speaker verification, enrollment and the loopback self-test Summary

Barge-in now asks "is this the user's voice?" with a TitaNet-small score before it cuts Snow off; `snow dev enroll-voice` makes the DPAPI-wrapped voiceprint; a hardware loopback suite exists but could NOT be run tonight (no live loopback on this laptop's default devices), so nothing in it is evidence yet.

## What was built

- **Dependency** (commit b7c722e): `sherpa-onnx==1.13.8` locked. See deviation 1: `sherpa-onnx-core==1.13.8` had to be added explicitly. Both RESEARCH wheel hashes are in `uv.lock` (`566e49ad...` and `5579e801...`).
- **`speaker.py`**: `SpeakerVerifier` (sherpa-onnx TitaNet-small, 1 CPU thread, dim 192, model fetched once into `models/speaker/` through the pinned `ensure_pinned` downloader, renamed from kokoro's `_ensure`), plus the voiceprint store: DPAPI wrap with app entropy, atomic write under `%LOCALAPPDATA%\Snow\voice\voiceprint.bin`, corrupt or wrong-dimension loads as None logging only the exception class, `delete_voiceprint`. No vector is ever logged.
- **Pipeline** (`pipeline.py`, `__main__.py`): `speaker=` on `VoicePipeline` and `build_pipeline`; `_load_speaker` loads off the loop and logs `speaker_verify on threshold=...`, `speaker_verify off reason=not_enrolled`, or `speaker_verify unavailable kind=...`. `_barge_check` scores the window concurrently with the words check (`asyncio.gather`), passes the score and the voiceprint's threshold to `bargein.decide`.
- **Fail closed (amendment 1)**: if a voiceprint file exists but the verifier is not loaded (still loading, model failed, voiceprint unreadable) every check rejects with reason `speaker`; a scoring exception also rejects (`speaker_score_failed kind=...`). Talking over Snow can then never cut it; the wake phrase still does. No subsystem health row fits, so only the log line is published.
- **Config**: `SpeakerConfig` (https-only url, SHA-256 pin, threshold 0.35, min/max 0.30-0.60, min_margin 0.15, six `calibration_lines`) and a `[speaker]` section in `config/voice.toml`; the lines follow the tts.toml `audition_line` dev-tool exception (spoken only by the dev tool, never on the reply path).
- **`enroll.py`** (commit 02a4de8, `snow dev enroll-voice`): refuses with exit 2 while the hub pid is alive (read-only `snow_is_running`, `--reset` exempt); plays Snow's Pocket voice through the speakers with no echo reference (a TV-like impostor), records the user reading the config lines through a fresh `EchoCanceller.capture`, needs 8 voiced 2 s segments, holds out 5, centroid from the rest, `calibrate` (midpoint of impostor max and genuine p5, clamped; refuses under margin 0.15), optional `--tv-seconds` and `--check-clips DIR`, saves only the wrapped voiceprint. Audio stays in memory. Voiced seconds come from a named helper `voiced_seconds` over `voiced_level`'s tuple (amendment 5).
- **Persona** (`persona.toml`): one instruction bullet: Snow's own voice or room noise is sometimes misheard as the user; a turn that only repeats a few of its recent words, or one senseless word, is probably that; never take it as agreement or approval; at most one short line asking what they want. `test_no_scripts` and `test_persona` pass.
- **Hardware suite** (commit 28edb18, `tests/hardware/test_bargein_loopback.py`): real pipeline (mic, real wake gate, VAD, Smart Turn, Moonshine, Pocket only, AEC, fail-closed fake Groq) in enrolled and no-voiceprint states; Snow alone (3 long replies), coughs/clicks/noise bed over Snow in both states, a voice-clip positive control, and an enrolled rejection control that runs only with the user's real voiceprint. Room sounds play through a second stream that is not the echo reference. `tests/hardware/test_echo_cancel.py` now compares against `pause_after_ms` (plan 01 note).

## Hardware loopback: SKIPPED-PENDING (neither pass nor fail)

`uv run pytest -m hardware tests/hardware/test_bargein_loopback.py -x -q -s` on this machine, Snow not running:

- Default input is the headset **Microphone (GHW-123P)**, which reads digital silence (-96 dBFS) even while the speakers play. The suite's loopback guard detects this (speaker burst must sit 10 dB above the room) and skips all five tests with "loopback is not live". Default output is FxSound Speakers.
- The laptop's own mic is "Microphone Array (Intel Smart Sound)". With `SNOW_LOOPBACK_MIC="Microphone Array"` the 2 s speaker burst only measured 3 to 9 dB above the room (-38 to -42 dBFS against -45 to -47 dBFS): the speakers are very quiet or routed to the headset. I did not touch system volume or default devices.
- **Earlier runs with the default (silent) mic passed vacuously** (0 pauses, 0 checks in every scenario). They are not evidence. The guard was added because of them.
- Informational runs with the weak Intel-mic coupling and `SNOW_LOOPBACK_MIN_RISE_DB=-20` (not evidence either; they only show the harness works end to end): Snow alone, enrolled with the stand-in voiceprint: 0 pauses, 3 replies complete, one check logged as reason `speaker` with score 0.18 (Snow's own voice against a stand-in voiceprint). Noise over Snow, enrolled stand-in: 0 pauses, 0 ducks, 0 cut-offs, 2 replies complete. Noise, no voiceprint: 0 pauses, 0 cut-offs. Positive control (no voiceprint): cut Snow once (episode 5, 2 words) and missed once, so it is flaky at this coupling.
- **Enrolled-state scenarios run with the stand-in voiceprint are labelled "stand-in, not evidence of the biometric gate"** (amendment 3). The real evidence run happens after the user enrolls.
- **Step D (tuning `[turn] pause_after_ms`) is pending**: left at 300; no valid Snow-alone measurement exists. Rerun with the laptop speakers and its own mic as default devices at normal volume (or `SNOW_LOOPBACK_MIC="Microphone Array"` plus a louder speaker volume), Snow quit, command: `uv run pytest -m hardware tests/hardware/test_bargein_loopback.py -x -q -s`. If replies 2-3 pause, raise `pause_after_ms` in 50 ms steps up to 400 (`-k alone`), if none, try 200; record the result in the voice.toml comment.

## One-word score measurement (amendment 2)

TitaNet-small against a centroid of 20 of the user's phone "Hey Snow" clips (C:\SnowVoice\clips, about 1 s each), 13 held out, threshold 0.35. Phone mic, not the laptop mic; not an actual "Stop.", so it is an indication only:

| Audio | min | p5 | mean | max |
|-------|-----|----|------|-----|
| whole clip (0.9-1.7 s) | 0.70 | 0.72 | 0.83 | 0.92 |
| first 0.8 s | 0.12 | 0.32 | 0.71 | 0.88 |
| first 0.5 s | 0.08 | 0.30 | 0.55 | 0.75 |
| fixture voices, 0.8 s crops (37) | -0.17 | -0.15 | -0.09 | 0.02 |

The one-word path is mostly reliable (mean 0.71 at 0.8 s), but a tail of short or soft words scores under 0.35 (about 1 in 13 at 0.8 s, more at 0.5 s), so a single quiet "Stop." can be rejected and Snow resumes. `min_words_verified` stays 1. **Known limit for the user's check**: if "Stop." does not stop Snow, say it again or use two words ("Stop, Snow."); the wake phrase always works. `C:\SnowVoice\snow_full.wav` crops scored up to 0.91, so that file is probably the user's own voice, not Snow's; I did not use it as an impostor.

## Deviations from Plan

**1. [Rule 3 - Blocking] `sherpa-onnx-core` was not locked by `uv add sherpa-onnx==1.13.8`.** The core wheel hash `5579e801...` was absent from `uv.lock` even though PyPI's `requires_dist` and the installed wheel METADATA both say `sherpa-onnx-core==1.13.8` (uv's lock took the dependency list from metadata that omits it). The plan says to halt if either hash is missing; this was a missing lock entry, not a different hash, so I added the exact transitive pin `sherpa-onnx-core==1.13.8` with `uv add`, which locks the RESEARCH hash `5579e80196d516e6dae23c8f629292ce3142ab8869925d32b94612fd86f93733` (verified present, along with `566e49ad...`). Both are the packages the user approved on 2026-10-26. The orchestrator may want to double check this call.
- Files: `pyproject.toml`, `uv.lock`. Commit b7c722e.

**2. [Rule 2 - Correctness] Hardware loopback guard and `SNOW_LOOPBACK_MIC` / `SNOW_LOOPBACK_MIN_RISE_DB` overrides** (not in the plan). Without a live loopback the suite passed vacuously on this machine, so a module guard skips when the mic does not hear a speaker burst. The mic override lets a headset-default machine use the laptop mic. Commit 28edb18.

**3. [Rule 3] Hub arms the engine between replies.** The harness puts the engine in wake-only state between replies and aborts the room stream when a reply ends, so room sounds that outlast a reply cannot open a user turn that swallows the next reply (found by an informational run).

**4. Commit split** per amendment 6: (a) b7c722e dependency lock, downloader rename, SpeakerConfig, speaker.py, pipeline wiring with its tests; (b) 02a4de8 enroll.py with its tests; (c) 28edb18 hardware test, persona, echo-test fix.

**5. Fail-closed gate keyed on the voiceprint file** rather than on the `speaker` object (amendment 1): plan E said to set the speaker to None on a load error; the amendment overrides it.

## Verification

- `uv run pytest -q tests/voice tests/brain`: 507 passed, 7 deselected
- `uv run ruff check src tests`: clean; `uv run ruff format --check src tests`: clean; `uv run pyright`: 0 errors
- `uv run pytest -q tests/brain/test_persona.py tests/brain/test_no_scripts.py`: 18 passed; `grep -c "never take it as agreement or approval" config/persona.toml`: 1
- Both sherpa wheel hashes present in `uv.lock` (grep -c 1 each); real model loads with dim 192 (`SpeakerVerifier.load`); real-model test ran, not skipped
- `uv run snow dev enroll-voice --help` works
- `uv run pytest -q tests -m "not hardware" --ignore=tests/voice --ignore=tests/brain`: 120 passed, 1 failed (`tests/test_skeleton_turn.py::test_provider_failure_before_first_token_publishes_no_reply`: the mock provider runs out of queued responses, a brain chain-length mismatch in code and config this plan did not touch; logged under Deferred Issues). `tests/test_cli.py` passes (Snow was not running).
- Hardware suite: SKIPPED-PENDING, see above.

## Deferred Issues

- `tests/test_skeleton_turn.py::test_provider_failure_before_first_token_publishes_no_reply` fails (`IndexError: pop from empty list` in `tests/conftest.py` MockProvider): out of scope, not touched by this plan.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-wvr-06..SC mitigations are in place: score threshold plus words plus echo filter with fail-closed on scoring errors and on a not-loaded verifier; https plus SHA-256 pinned model download; DPAPI voiceprint outside the repo with tests for no plaintext and no vector in logs; enrollment audio in memory only; `snow_is_running` guard (read-only); exact pins with both wheel hashes locked.

## For the user (two steps, with Snow quit)

1. Enrollment (about 1 min): `uv run snow dev enroll-voice`. Stay quiet while Snow's voice plays the calibration lines, then read the printed lines aloud for 30 s. It must print "Saved" with a margin of at least 0.15. If it refuses, follow its one-line advice and rerun. (Use the laptop speakers and the laptop mic as defaults, not the GHW-123P headset.)
2. Live check (about 2 min, `uv run snow run`, laptop speakers):
   - (a) Ask for a long answer and talk over it with a sentence. Snow goes quiet within about a third of a second and answers your new words.
   - (b) Cough or tap the desk while it speaks. At most a brief pause, then it carries on from the same word.
   - (c) Play a YouTube talk while it speaks. It carries on.
   - (d) Let it finish a long reply without talking. It never stops itself, and no "Certainly." turn appears.
   - (e) Say "Hey Snow" mid-reply. It stops at once.
   - (f) Say just "Stop." over a reply. It stops and listens (known limit: a quiet single word can be rejected; say it again).

## Self-Check: PASSED

- src/snow/voice/speaker.py, src/snow/voice/enroll.py, tests/voice/test_speaker.py, tests/voice/test_enroll.py, tests/hardware/test_bargein_loopback.py exist
- commits b7c722e, 02a4de8, 28edb18 are ancestors of HEAD

## Orchestrator hardware run (2026-10-27, night, Snow quit, default in: Microphone Array, out: FxSound Speakers)

- Run 1: 3 passed (Snow alone, noise scenarios: zero confirmed barge-ins), positive control failed: the words check timed out (`local_stt_failed kind=InvalidStateError`; one-shot Moonshine took 1.3 s cold, up to 0.9 s busy, against `timeout_s` 1.0).
- Fix (orchestrator commit after this note): Moonshine one-shot warm-up at load, `barge_check.timeout_s` 2.0, `duck_release_s` 4.0, no `set_result` on a timed-out future.
- Run 2: 3 passed, 1 skipped; positive control did not pause at all (speaker-to-mic coupling of the replayed clip too weak at night volume through FxSound). Inconclusive, not evidence against the gate; the user's live check (a)-(f) decides.
- Note: the default output is the FxSound virtual device (an audio enhancer). It may cause the voice "flutter" (UAT test 5) and adds non-linear processing that weakens echo cancellation; try Snow with FxSound bypassed.
