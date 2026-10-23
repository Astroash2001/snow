---
phase: 01-always-on-voice-loop
plan: 30
subsystem: voice
status: checkpoint
tags: [wake-word, openwakeword, livekit-wakeword, training, kaggle, privacy]
requires: ["01-02 livekit-wakeword verdict (approved)", "01-29 tests/hardware/__init__.py"]
provides:
  - "training/wakeword recipe (hey_snow.yaml, hey_snow_dnn.yaml, README.md with the Kaggle route)"
  - "snow dev record-negatives"
  - "WakeGate path models pinned by [wake] model_sha256, refusal reported as wake_word down"
  - "tests/hardware/test_wake_fp.py false-accept and recall harness"
  - "\"Hey Snow\" as the configured wake phrase (models/wakeword/hey_snow.onnx, threshold 0.5)"
affects: [src/snow/voice/wake.py, src/snow/voice/config.py, src/snow/voice/pipeline.py, config/voice.toml]
tech-stack:
  added: []
  patterns: ["SHA-256 pin before loading an off-machine model file", "refused model = deaf gate + health row, never a crash", "flow tests pin the hey_jarvis stand-in; gitignored-model tests skip when it is absent"]
key-files:
  created:
    - training/wakeword/hey_snow.yaml
    - training/wakeword/hey_snow_dnn.yaml
    - training/wakeword/README.md
    - src/snow/voice/record_negatives.py
    - tests/voice/test_wake_custom.py
    - tests/hardware/test_wake_fp.py
    - tests/fixtures/audio/hey_snow_cmd.wav
  modified:
    - src/snow/voice/wake.py
    - src/snow/voice/config.py
    - src/snow/voice/pipeline.py
    - config/voice.toml
    - scripts/make_audio_fixtures.py
    - tests/voice/conftest.py
    - tests/voice/test_voice_turn.py
    - tests/voice/test_wake.py
    - tests/voice/test_units.py
    - tests/voice/test_bargein.py
    - tests/hardware/test_latency.py
decisions:
  - "A path wake model always needs model_sha256; an empty hash is refused as a mismatch"
  - "The training install verifies the livekit-wakeword 0.3.0 wheel SHA-256 before installing"
  - "Runtime stays openwakeword: the livekit-wakeword conv_attention export loads in openwakeword.Model; livekit-wakeword is not a Snow dependency"
  - "Wake threshold 0.5, not the eval's optimal 0.21: the look-alike 'hey so' peaks up to 0.75 on synthetic voices; patience_frames stays 2; calibrate once after the hardware test"
  - "Training runs on Kaggle (GPU T4 x2, Save & Run All commit); the community Colab notebook fails on Python 3.13"
metrics:
  completed: 2026-10-23
actuals:
  tokens: 14000
  tasks: 3
  commits: 5
plan_head_before: 83f6a1c6e17db68115fd9fc9be63ea501ddb810b
plan_head_after: 28a7059
---

# Phase 1 Plan 30: "Hey Snow" wake word (Tasks 1-3 done, hardware check pending)

Snow now wakes on "Hey Snow" through the user's own trained model, loaded locally by openWakeWord and pinned by SHA-256, at threshold 0.5. CI never needs the gitignored model: flow tests pin the hey_jarvis stand-in, and the one hey_snow test skips when the file is absent.

## Progress

| Task | Status | Commits |
|------|--------|---------|
| 1. Recipe, recorder, checksummed loading, measurement tools | done | 61f8d9c, e93538c, e9ca4de, d74dedf |
| 2. Train the model (human action) | done by the user on Kaggle | - |
| 3. "Hey Snow" becomes the wake phrase | done except the hardware human-check | 28a7059 |

## What Task 1 built

- `training/wakeword/hey_snow.yaml` / `hey_snow_dnn.yaml`: key names checked against the 0.3.0 sdist (`src/livekit/wakeword/config.py`). Both files load in the real `WakeWordConfig` with no unknown keys. Unknown keys are ignored silently, so this check matters. The real names differ from the plan's flat list: `model_type`/`model_size` sit under `model:`, look-alike phrases are `custom_negative_phrases`, and recorded negatives go in `augmentation.background_paths`.
- `training/wakeword/README.md`: the training steps using the real CLI stages (`setup`, `generate`, `augment`, `train`, `export`, `eval`), with a wheel hash check before install, plus placement, `certutil` hashing, acceptance targets and a privacy note.
- `snow dev record-negatives --minutes N --out <dir>`: writes 10-minute 16 kHz WAV files and refuses folders inside the repo or `data_dir()`.
- `WakeGate(..., model_sha256=)`: a `.onnx` path loads only if its SHA-256 matches (case-insensitive). On failure the gate stays deaf and `VoicePipeline` publishes `wake_word` `down` with "Wake model missing" or "Wake model checksum mismatch". The worker keeps running.

## Task 2: the trained model

- **Platform: Kaggle**, not Colab. Colab and Kaggle both run Python 3.13 now. The community Colab notebook fails there because `piper-phonemize-cross` has no 3.13 wheel.
- Recipe: livekit-wakeword 0.3.0 (wheel SHA-256 `6bb00b832c21720ebb94410e005854740b2d36b20970c7cecc74b5e889d94f4b`, verified). `hey_snow.yaml` was unchanged except for paths: `data_dir: /tmp/data`, `output_dir: /kaggle/working/output`, `background_paths: [/tmp/data/backgrounds]`, `rir_paths: [/tmp/data/rirs]`. `/kaggle/working` holds only 20 GB. The run used "Save Version > Save & Run All (Commit)" with GPU T4 x2 and Internet on, so the outputs persisted. An earlier draft session was wiped before download.
- **Upstream bug in livekit-wakeword 0.3.0:** `cli.py` lines 292 and 398 call `run_extraction(config)`, but `data/features.py:72` declares `run_extraction(config, sess_options: SessionOptions)` with no default. `augment` then fails with `TypeError: run_extraction() missing 1 required positional argument: 'sess_options'`. The code downstream accepts `None`. The fix, run before augment: `sed -i 's/sess_options: SessionOptions) -> None:/sess_options: SessionOptions | None = None) -> None:/' /usr/local/lib/python3.13/dist-packages/livekit/wakeword/data/features.py`. It is now in the README.
- Model: `models/wakeword/hey_snow.onnx` (gitignored, never committed), 152605 bytes, SHA-256 `db2bc395d5e5676694ac258a8b258b2e087eb9d5ff47b3783d047f8d19be283b` (matches Kaggle's `sha256sum`). conv_attention small, 50000 steps.
- Eval (`hey_snow_eval.json`): aut 0.000223, fpph 0.0, recall 0.8905, accuracy 0.945 at threshold 0.5; optimal_threshold 0.21 (optimal_recall 0.961, optimal_fpph 0.157); n_positive 4000, n_negative 34484, validation_hours 19.16.

## What Task 3 did

- **Runtime: openwakeword.** The conv_attention export loads in `openwakeword.Model(..., inference_framework="onnx")` with Snow's melspectrogram/embedding models via `snow.voice.wake.model_files`. Input is `embeddings [batch,16,96]` and output is `score [batch,1]`. livekit-wakeword was not added to `pyproject.toml` and no packages were installed.
- Synthetic peak scores (kokoro voices af_heart, am_michael, bf_emma, bm_george; max frame score, no patience):

  | Phrase | Peak score |
  |--------|------------|
  | "hey snow" | 0.83-0.95 |
  | "hey snow, what time is it" | 0.88-0.92 |
  | "hey so" | 0.35-0.75 |
  | "let it snow" | 0.07-0.38 |
  | "hey jarvis", "what is the weather" | < 0.02 |
  | `tv_negative.wav` | 0.016 |
  | new `hey_snow_cmd.wav` | 0.877 |

- `config/voice.toml [wake]`: `model = "models/wakeword/hey_snow.onnx"`, `model_sha256 = "db2bc395…283b"`, `threshold = 0.5`, `patience_frames = 2`. A commented `# model = "hey_jarvis"` line is kept as the A/B baseline. **Licence:** the hey_jarvis pretrained weights are CC BY-NC-SA 4.0, personal use only, so they must not ship to other users. The new first strip pattern removes a leading "hey snow" and its ASR variants ("hey, snow", "hey sno", "hay snow", "a snow", "hey snoh", "hey snoe"). It is anchored at the start only, so "Let it snow" is left alone. The Jarvis patterns stay while the A/B line exists. The Groq prompt hint `Hey Jarvis.` became `Hey Snow.`, as its comment requires.
- Tests: `tests/voice/conftest.py` `voice_cfg()`/`CFG` keep voice.toml but pin the wake to hey_jarvis, because the existing fixtures say "Hey Jarvis". `run_fixture(..., configured_wake=True)` uses the configured model instead. `test_wake.py` uses that `CFG`. `hey_snow_cmd.wav` ("Hey Snow, what time is it?", bm_george) was added to `scripts/make_audio_fixtures.py`. It is scored with the trained model, and `--check` skips its wake score when the model is absent (CI). The new `test_hey_snow_on_the_configured_model_strips_and_keeps_the_command` skips without the model. There are also new strip-pattern cases in `test_units.py`.
- CI without the model: with `hey_snow.onnx` moved away, `tests/voice` gave 301 passed, 1 skipped, and `make_audio_fixtures.py --check` passed. No test depends on the gitignored file. A real Snow run without the file reports `wake_word` down ("Wake model missing") and stays deaf rather than crashing. That is the Task 1 design.

## Deviations from Plan

**1. [Rule 3 - Blocking] `config.py` and `pipeline.py` touched in Task 1** for the `model_sha256` field and the health row.

**2. [Rule 1 - Bug] `tests/voice/test_bargein.py` `NoWake` fake** gained `error = None` (Task 1).

**3. Expected time in README** belongs to the community fallback only (Task 1).

**4. Extra adversarial phrases** in the training YAML (Task 1).

**5. Training on Kaggle instead of Colab** (Task 2): a Python 3.13 runtime plus 20 GB working-disk path overrides and the upstream `sess_options` patch. All of it is documented in the README.

**6. Threshold 0.5 rather than the eval operating point** (Task 3): the plan asked for the eval's point for about 0.2 FP/h (0.21). 0.5 was chosen because "hey so" peaks up to 0.75 on synthetic voices, and the eval reports fpph 0.0 at 0.5 anyway.

**7. [Rule 1 - Bug] `tests/hardware/test_latency.py`** plays "Hey Jarvis" command clips through the configured wake. It would never wake on hey_snow, so it now pins the stand-in the same way conftest does.

**8. [Rule 2] Groq prompt hint** changed to "Hey Snow." so Whisper spells the new wake phrase for the strip patterns.

## Pending: hardware human-check (why status stays `checkpoint`)

`tests/hardware/test_wake_fp.py` has not been run on the real microphone yet:
- fp mode: under 1 false accept per hour over at least 2 h of TV and room noise (`uv run pytest -m hardware tests/hardware/test_wake_fp.py -k false_accepts -s -q`)
- recall mode: at least 90 % of 50 "Hey Snow" at arm's length, across the room and from the doorway (`-k recall`)

Record false accepts per hour and recall here. Adjust `[wake] threshold` once if a target is missed, then re-run the failing mode. VOIC-01 stays open until then.

## Gates (Task 3)

- `uv run pytest tests/voice -x -q`: 302 passed (model present); 301 passed, 1 skipped (model absent)
- `uv run pytest -q -m "not hardware and not gpu and not network"`: 533 passed, 1 skipped
- `ruff check src tests`: clean; `ruff format --check src tests`: 131 files formatted; `pyright`: 0 errors; `python -m snow.contracts.export --check`: exit 0
- `scripts/make_audio_fixtures.py --check`: all 14 fixtures PASS

## Self-Check: PASSED

Fixture `tests/fixtures/audio/hey_snow_cmd.wav` exists; commits 61f8d9c, e93538c, e9ca4de, d74dedf and 28a7059 are on HEAD; the model file is untracked (gitignored).
