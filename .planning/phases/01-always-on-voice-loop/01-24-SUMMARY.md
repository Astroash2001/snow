---
phase: 01-always-on-voice-loop
plan: 24
subsystem: voice
tags: [tone, prosody, emotion, onnx, privacy]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "Tone model and transcript.final.tone field (01-04), tone_calm and tone_stressed fixtures (01-05), SttRouter and voice pipeline (01-20, 01-22), brain tone line that consumes the result (01-16)"
provides:
  - "ToneAnalyzer.analyze(pcm, text) -> Tone: loudness, pitch, pace, optional emotion; in memory only"
  - "transcript.final.tone filled for every user turn; None if the analysis is late or fails"
  - "[tone] table in config/voice.toml and ToneConfig; `python -m snow.voice.tone` fetches and verifies a pinned model on request"
affects: [01-16 brain tone line (now receives real values), 01-23 HUD (tone fields on transcript.final)]

commits: 1
plan_head_before: 971844ea0d304ed531cb9724bc4aef4a95241cf0
plan_head_after: a4134ae249054505dc5c8659a6b5fde04be780d6

actuals:
  tokens: 14000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Per-turn analysis in asyncio.to_thread, awaited with a shielded timeout so tone can never delay or break the transcript"
    - "Categories relative to the user's last 20 turns (median), absolute thresholds until 3 turns exist"

key-files:
  created:
    - src/snow/voice/tone.py
    - tests/voice/test_tone.py
  modified:
    - src/snow/voice/pipeline.py
    - src/snow/voice/config.py
    - config/voice.toml

key-decisions:
  - "Emotion model is OFF (model_url empty): the only small CPU candidate has a non-permissive licence and weak accuracy on natural speech. Prosody-only ships; the model path is implemented, tested with a fake session, and enabled by filling three config lines"
  - "Pace is counted over speech with pauses up to 300 ms bridged, lead-in and tail excluded; plain frame-energy voiced time made the calm fixture read 177 wpm (fast)"
  - "wpm uses the unstripped transcript so the wake words, which are in the audio, are counted"

requirements-completed: [SPCH-02]

coverage:
  - id: D1
    description: "tone_stressed is fast and loud; tone_calm is slow or normal and quiet or normal"
    status: tested
  - id: D2
    description: "words_per_min equals words over voiced minutes within 10 % (synthetic clip with known duration)"
    status: tested
  - id: D3
    description: "analyze() of a 5 s clip under 150 ms on CPU"
    status: tested
  - id: D4
    description: "analyze() opens no file for writing (open, wave.open, Path.write_bytes patched to fail)"
    status: tested
  - id: D5
    description: "Missing file, failed checksum or unreadable model: emotion None, prosody filled"
    status: tested
  - id: D6
    description: "transcript.final carries tone; a 0.9 s analysis yields tone None without changing the text"
    status: tested
  - id: D7
    description: "Real emotion model on the fixtures (slow test)"
    status: skipped
    reason: "model_url is empty by decision; test skips with the reason recorded below"
  - id: D8
    description: "Spoken human check: ten calm and ten stressed turns, hit rate"
    status: pending
    reason: "Needs the real microphone; not run by this agent"
---

# Phase 1 Plan 24: Local tone detection Summary

Every user turn now carries a local tone tag (loudness, pitch, pace) computed from in-memory audio in about 15 ms; the emotion model is switched off after the spike because of its licence and accuracy.

## What was built

- `ToneAnalyzer` (`src/snow/voice/tone.py`): 30 ms energy frames pick the voiced part; loudness is RMS over voiced frames; pitch is the median autocorrelation peak (60-400 Hz) of voiced 40 ms windows; pace is words over speech time. Loud/quiet/fast/slow are judged against the median of the user's last 20 turns once 3 turns exist, and against the config's absolute limits (`fast_wpm` 170, `slow_wpm` 110, reference level -24 dBFS) before that.
- Pipeline: after the final text is known the analysis runs in a thread; the transcript waits at most `[tone] wait_s = 0.3` and goes out with `tone=None` if it is late or throws. Mute is re-checked after the wait.
- Optional emotion path: SHA-256 checked before load (bytes loaded from memory, so the checked file is the executed file), CPU provider only, softmax with a configurable temperature, top label kept only at or above `min_confidence`. `python -m snow.voice.tone` downloads over https and verifies the hash into gitignored `models/tone/`; the worker never downloads.

## Spike verdict (D-35): emotion2vec-web-distill, disabled

- Source: https://huggingface.co/thomashallock/emotion2vec-web-distill, commit `566a831be26e64f7e641241c26154793b7dd1428`, file `distill-student-v4.fused.onnx`, SHA-256 `136b83ee1cbf16b102b341398534604a7f8ddadff1f07b50bc76739fa04a3795` (verified after download; 9.7 MB, 2.23M parameters).
- Licence: FunASR Model Open Source License v1.1 (Alibaba). Not MIT/Apache/BSD/CC-BY. It says the models are provided "for reference and learning purposes only" and does not address commercial use; the model card says the same. Not permissive, so it fails this plan's licence rule.
- Speed: works on onnxruntime CPU, 5-7 ms per 3 s window (measured). Fits the CPU budget easily.
- Accuracy: the model card reports it agrees with its teacher only ~14 % of the time on non-calm natural speech and answers "calm" ~72 % anyway, and says it is not suitable for catching emotional events in conversation. On the two fixtures it answered "calm" for both (0.655 calm, 0.683 stressed), so it did not separate them.
- Output is 18 expression poses (calm, content, warm, happy, amused, excited, surprised, smug, confused, skeptical, annoyed, disgusted, afraid, angry, tense, sad, weary, bored), 48000-sample window, temperature 0.0375.
- Decision: `model_url = ""`, prosody only. This is a deviation from "Tone.emotion = top label" being filled in normal use; `Tone.emotion` is None in practice for now. To try the model later, paste the url, hash, labels and temperature (kept as a comment block in `config/voice.toml`) and run `uv run python -m snow.voice.tone`. The slow test `test_pinned_emotion_model_runs_within_budget` then runs for real; today it exits 0 with the skip reason "emotion model disabled (plan 01-24 spike: FunASR licence is not permissive and the model misses most non-calm speech); prosody only". The emotion path was also run once end-to-end against the downloaded model through `ToneAnalyzer` (has_model True, labels and temperature applied, ~6 ms).
- The 300M emotion2vec+ large was not pulled (D-39). A permissive small model is still an open item if emotion labels matter.

## Measurements

| Fixture | pace | loudness | wpm | dBFS | pitch Hz | analyze (prosody) |
|---------|------|----------|-----|------|----------|-------------------|
| tone_calm (5.85 s) | normal | normal (-31.7, just above the quiet limit) | 145 | -31.7 | 139 | ~16 ms first call, <5 ms warm |
| tone_stressed (4.15 s) | fast | loud | ~215-241 | -12.7 | 143 | ~2 ms |

A 5 s clip stays far under the 150 ms limit, with or without the model (the model added 5-7 ms). The test asserts the 150 ms bound on a 4 s synthetic clip (prosody only).

## Deviations from Plan

1. **[Rule 1 - Bug] Voiced time made pace wrong.** With plain frame energy the calm fixture read 177 wpm and "fast", breaking the behavior block. Fix: bridge pauses up to 300 ms and exclude lead-in/tail. Calm now 145 wpm "normal".
2. **Emotion model disabled** (see spike verdict); the plan allowed this when licence or runtime fails.
3. **Config keys beyond the plan's list:** `temperature` (the model needs 0.0375), `ref_loudness_dbfs` (absolute loudness reference for the first turns, which the plan required but gave no key for) and `wait_s` (the 300 ms cap).
4. **Tone starts after the final text, not before it.** The plan said tone and STT overlap. wpm needs the text, and a measured analysis costs about 15 ms, so the simple order was kept; the 300 ms cap still guarantees no delay.
5. **wpm counts the unstripped transcript** (wake words included) because the PCM contains the wake phrase.

No edits outside the plan's files_modified; no new package; no contract changes (`Tone` and `TranscriptFinal.tone` already in the 01-04 catalog).

## Known stubs

None. `Tone.emotion` is None until a model is enabled, by design, documented above.

## Pending

- Human check not run: speak ten calm and ten rushed turns and compare the stored `transcript.final` tone fields (hit rate to be recorded by the user). The loudness reference of -24 dBFS and the 170/110 wpm limits are tuned on synthetic TTS fixtures; real-mic levels are likely to differ until the 3-turn history takes over, so these are the values to adjust after the human check.
- A permissive emotion model if the user wants emotion labels.

## Threat flags

None new. T-01-36 (pinned URL + SHA-256, CPU provider, loaded from the verified bytes), T-01-37 (test patches open/wave.open/Path.write_bytes to fail on writes; tone code never writes audio), T-01-SC (no new package; download uses stdlib urllib, https only) are implemented as planned.

## Verification

- `uv run pytest -x -q -m "not hardware and not network and not slow"`: 308 passed (includes test_no_egress and the no-disk proof).
- `uv run pytest -m slow tests/voice/test_tone.py`: 1 skipped with the reason above, exit 0.
- `ruff check`, `ruff format --check`, `pyright`: clean.

## Self-Check: PASSED

Files tone.py, test_tone.py, this summary exist; commit a4134ae is on the branch.
