---
phase: 01-always-on-voice-loop
plan: 30
subsystem: voice
status: checkpoint
tags: [wake-word, openwakeword, livekit-wakeword, training, privacy]
requires: ["01-02 livekit-wakeword verdict (approved)", "01-29 tests/hardware/__init__.py"]
provides:
  - "training/wakeword recipe (hey_snow.yaml, hey_snow_dnn.yaml, README.md)"
  - "snow dev record-negatives"
  - "WakeGate path models pinned by [wake] model_sha256, refusal reported as wake_word down"
  - "tests/hardware/test_wake_fp.py false-accept and recall harness"
affects: [src/snow/voice/wake.py, src/snow/voice/config.py, src/snow/voice/pipeline.py]
tech-stack:
  added: []
  patterns: ["SHA-256 pin before loading an off-machine model file", "refused model = deaf gate + health row, never a crash"]
key-files:
  created:
    - training/wakeword/hey_snow.yaml
    - training/wakeword/hey_snow_dnn.yaml
    - training/wakeword/README.md
    - src/snow/voice/record_negatives.py
    - tests/voice/test_wake_custom.py
    - tests/hardware/test_wake_fp.py
  modified:
    - src/snow/voice/wake.py
    - src/snow/voice/config.py
    - src/snow/voice/pipeline.py
    - tests/voice/test_bargein.py
decisions:
  - "A path wake model always needs model_sha256; an empty hash is refused as a mismatch"
  - "The Colab install verifies the livekit-wakeword 0.3.0 wheel SHA-256 before installing"
metrics:
  completed: 2026-10-19
actuals:
  tokens: 9000
  tasks: 1
  commits: 4
plan_head_before: 83f6a1c6e17db68115fd9fc9be63ea501ddb810b
plan_head_after: d74dedf
---

# Phase 1 Plan 30: "Hey Snow" wake word (partial: Task 1 done, Task 2 awaiting the user)

A pinned, schema-checked livekit-wakeword 0.3.0 Colab recipe for "hey snow", a negatives recorder that only writes outside the repo and data folder, SHA-256 pinned custom wake models that report `wake_word` down instead of crashing, and a live-mic acceptance harness.

## Progress

| Task | Status | Commits |
|------|--------|---------|
| 1. Recipe, recorder, checksummed loading, measurement tools | done | 61f8d9c, e93538c, e9ca4de, d74dedf |
| 2. Train the model in Colab (human action) | awaiting the user | - |
| 3. "Hey Snow" becomes the wake phrase, measured threshold | not started (needs the model) | - |

## What Task 1 built

- `training/wakeword/hey_snow.yaml` / `hey_snow_dnn.yaml`: key names checked against the 0.3.0 sdist (`src/livekit/wakeword/config.py`). Both files were loaded by the real `WakeWordConfig` with no unknown keys (the model ignores unknown keys silently, so this matters). The real names differ from the plan's flat list: `model_type`/`model_size` sit under `model:`, look-alike phrases are `custom_negative_phrases`, and recorded negatives go in `augmentation.background_paths` (`./negatives`, skipped when absent).
- `training/wakeword/README.md`: Colab steps using the real CLI stages from `cli.py` (`setup --config`, `generate`, `augment`, `train`, `export`, `eval`), with a wheel hash check before install. Outputs: `/content/output/hey_snow/hey_snow.onnx`, `hey_snow_eval.json`, `hey_snow_det.png`. Also covers placement at `models/wakeword/hey_snow.onnx`, `certutil` hashing, the fallback notebook pinned to commit `da4d92a`, acceptance targets and a privacy note.
- `snow dev record-negatives --minutes N --out <dir>`: reuses `MicSource` (WASAPI, reconnects) and writes 10-minute 16 kHz WAV files. It refuses folders inside the repo or `data_dir()`. The CLI entry already existed in `snow/cli.py`.
- `WakeGate(..., model_sha256=)`: a `.onnx` path is resolved against the repo root and loaded only if its SHA-256 matches. The hash check ignores case, so `certutil` upper-case output works. On failure the gate sets `error` and stays deaf, and `VoicePipeline` publishes `wake_word` `down` with "Wake model missing" or "Wake model checksum mismatch". The worker keeps running.

## Deviations from Plan

**1. [Rule 3 - Blocking] `config.py` and `pipeline.py` touched in Task 1.** `[wake] model_sha256` needs a config field (default `""`, so `voice.toml` is unchanged until Task 3), and the health row lives in `VoicePipeline._publish_health`. `build_pipeline` passes the hash through.

**2. [Rule 1 - Bug] `tests/voice/test_bargein.py` `NoWake` fake** gained `error = None`; without it the pipeline's health row raised `AttributeError` in 12 tests.

**3. Expected time in README.** The plan's 75-90 min (L4) / 2.5 h (T4) figures belong to the community fallback notebook, not livekit-wakeword. The README states them for the fallback only and says the main recipe is untimed. Its `setup` step downloads about 16 GB of ACAV100M features.

**4. Extra adversarial phrases** beyond the plan's list ("hey slow", "hey sir", "a snow", "the snow", "let it snow", "hey, so anyway"), plus `n_background_samples` 1000/200 so recorded negatives carry weight.

## Gates (Task 1)

- `uv run pytest -q -m "not hardware and not gpu and not network"`: 525 passed, 1 skipped
- `uv run pytest tests/voice/test_wake_custom.py -x -q`: 9 passed
- `ruff check`, `ruff format --check`, `pyright`: clean; `python -m snow.contracts.export --check`: ok

## Awaiting (Task 2, human action)

The user trains the model in Colab per `training/wakeword/README.md` and places `models/wakeword/hey_snow.onnx`. Then they pass back the `certutil` SHA-256 and the `hey_snow_eval.json` numbers. Eval report: pending.

## Self-Check: PASSED

All six created files exist; commits 61f8d9c, e93538c, e9ca4de and d74dedf are on HEAD.
