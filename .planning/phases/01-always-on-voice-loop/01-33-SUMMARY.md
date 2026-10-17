---
phase: 01-always-on-voice-loop
plan: 33
subsystem: voice
tags: [tts, chatterbox, gpu, power-policy, isolated-env, spch-02, spch-03]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "chatterbox-tts 0.1.7 approved (01-02), VoiceRouter with gpu_ok and order (01-26, 01-28), barge-in abort path (01-29), consent-tagged VoiceClip (01-31, 01-32)"
provides:
  - "engines/chatterbox: isolated, hash-locked uv project and a pipe-protocol synthesis server"
  - "ChatterboxEngine (subprocess client) and GpuPolicy (mains power, free VRAM, quiet GPU)"
  - "Router: Chatterbox joins the chain, one voice.switch when the policy turns false, process stopped to free VRAM"
  - "config/tts.toml [engines.chatterbox] with the emotion -> exaggeration dial"
affects: [HUD Voice card (voice_role gpu), 01-34 onward]

commits: 2
plan_head_before: df2f2100870d5c7107659dc83b072599b6b7bce5
plan_head_after: 4a6c782c7aa006d66e2ce57b5b0e78c79347d289

actuals:
  tokens: 38000
  tasks: 1
  commits: 2

tech-stack:
  added:
    - "chatterbox-tts 0.1.7 (isolated engines/chatterbox env only; root pyproject.toml and uv.lock unchanged)"
  patterns:
    - "Isolated engine: own uv project, own process, JSON lines in and length-prefixed float32 PCM out; scrubbed environment (no keys, no hub token, no HF token)"
    - "Policy-driven engine: eligibility = GpuPolicy.allowed() and model loaded; upkeep in the router's existing maintain loop"

key-files:
  created:
    - engines/chatterbox/pyproject.toml
    - engines/chatterbox/uv.lock
    - engines/chatterbox/.python-version
    - engines/chatterbox/server.py
    - src/snow/voice/tts/chatterbox.py
    - tests/voice/test_chatterbox_policy.py
    - tests/hardware/test_chatterbox.py
  modified:
    - src/snow/voice/tts/router.py
    - src/snow/voice/tts/config.py
    - src/snow/voice/__main__.py
    - config/tts.toml

key-decisions:
  - "The pipeline is not edited: the router (already owned by the pipeline) publishes the policy-driven voice.switch and the existing announce() publishes voice.status with the gpu role"
  - "Control answers (load, vram, in-speak error) travel on the same stdout as audio, as a frame whose length has bit 31 set; audio and end frames are exactly as the plan specified"
  - "The model is loaded in the background by the router's maintain loop, never at start-up, and the engine is eligible only while loaded; a reply that comes after an idle unload speaks in Pocket and brings the model back"
  - "Chatterbox's output watermark (Resemble Perth) is kept on; it is what the setuptools cap is for"

requirements-completed: [SPCH-03, SPCH-02]

coverage:
  - id: D1
    description: "GpuPolicy false on battery, true on a desktop, false on low VRAM, busy GPU or missing nvidia-smi; a spike does not count; our own VRAM and synthesis are not 'busy'"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_chatterbox_policy.py (policy tests)", status: pass}
    human_judgment: false
  - id: D2
    description: "With the policy true and the engine loaded, everyday replies select chatterbox (voice_role gpu); big moments stay Cartesia"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_chatterbox_policy.py#test_everyday_replies_use_chatterbox_while_allowed_big_moments_stay_cartesia", status: pass}
    human_judgment: false
  - id: D3
    description: "Policy turns false: process stopped (poll() not None), one voice.switch chatterbox -> pocket_tts with reason power or gpu_busy, next reply is Pocket"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_chatterbox_policy.py#test_a_false_policy_stops_the_process_and_publishes_one_switch", status: pass}
    human_judgment: false
  - id: D4
    description: "Frames parse from a stub server; a server crash raises EngineError so the router finishes the reply in Pocket with one switch"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_chatterbox_policy.py (frame, crash and router tests)", status: pass}
    human_judgment: false
  - id: D5
    description: "No clip is cloned without a consent tag: config load refuses it, the engine refuses a clip that got past config, Pocket's reference is shared only when it is an audio file"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_chatterbox_policy.py (consent tests)", status: pass}
    human_judgment: false
  - id: D6
    description: "Real model on the RTX 4050: load time, peak VRAM, first audio, RTF"
    status: tested
    verification:
      - {kind: test, ref: "tests/hardware/test_chatterbox.py (marked hardware and gpu, run once)", status: pass}
    human_judgment: false
  - id: D7
    description: "Plug in the charger, wait for the GPU to idle, talk to Snow: Voice card shows Chatterbox with the GPU chip. Unplug: within about 30 s the next reply uses Pocket TTS and Snow mentions the change once"
    status: pending
    human_judgment: true
    rationale: "Charger plug/unplug is the user's; not performed by this agent. Also listen to whether the emotion dial is audible."
---

# Phase 1 Plan 33: Chatterbox GPU voice behind a power and VRAM policy Summary

**Chatterbox (base model, CUDA) now speaks everyday replies only while the laptop is on mains power with free VRAM and a quiet GPU, in its own isolated environment and process that is stopped to free the VRAM the moment those conditions end; Pocket TTS takes over and the router records one voice.switch. The D-33 four-engine router is complete.**

## What was built

- `engines/chatterbox/`: its own uv project (`chatterbox-tts==0.1.7`, `torch==2.6.0`, `torchaudio==2.6.0` from the explicit `pytorch-cu124` index, `exclude-newer` as root, Python 3.12, win32 only), hash-locked (`uv.lock`, 114 packages, 269 hashes). `server.py` reads JSON lines (`load`, `speak`, `vram`, `quit`) and writes `uint32 length + float32 PCM` frames to stdout followed by a zero-length end frame; stray prints and C-level writes to fd 1 are redirected to stderr; audio is never written to disk.
- `tts/chatterbox.py`: `GpuPolicy` (psutil battery, `nvidia-smi` median of three readings, falls back to `System32\nvidia-smi.exe` when PATH lacks it), `ChatterboxEngine` (lazy background start, idle unload, crash and stall handling, scrubbed environment, consent check, `exaggeration` from the reply emotion), `resolve_reference` (Chatterbox's own clip, else Pocket's when it is an audio file, else Chatterbox's default voice).
- `tts/router.py`: Chatterbox eligibility is `engine.usable()` (policy true and model loaded); the existing 5 s maintain loop now also runs Chatterbox upkeep and publishes the single `voice.switch(chatterbox -> <next>, power|gpu_busy)`; `speak()` touches the engine; `stop()` closes the process. A crash mid-reply uses the existing fail-over (reason `unreachable`).
- `tts/config.py`: `SwitchConfig` replaced by `ChatterboxConfig` (enabled, python, server, min_free_vram_mb, max_gpu_util, check_interval_s, unload_after_s, load_timeout_s, cfg_weight, default_exaggeration, exaggeration map, optional consent-tagged reference).
- `voice/__main__.py`: registers the engine. `config/tts.toml`: `enabled = true`, thresholds, exaggeration `excited 0.8, content 0.55, calm 0.35, neutral 0.5, sympathetic 0.45, curious 0.6`.

## Measured on the RTX 4050 Laptop GPU (6 GB), mains power, desktop running

Run once, in memory, no audio played, server stopped afterwards (nvidia-smi back to 1.07 GB used / 4.85 GB free).

| Measure | Result |
|---------|--------|
| Model load incl. warm-up (weights already cached from a first attempt) | 41.3 s |
| Peak VRAM (torch allocated) | 3142 MB |
| VRAM taken from the GPU (nvidia-smi, incl. CUDA context) | 3311 MB |
| `min_free_vram_mb` set | 3823 (3311 + 512) |
| First audio, 2.2 s of speech (content) | 2.88 s, RTF 1.29 |
| First audio, 3.5 s of speech (sympathetic) | 3.30 s, RTF 0.94 |
| First audio, 0.8 s of speech (excited) | 1.30 s, RTF 1.64 |

Findings the user should weigh:

- **First audio is 1.3 to 3.3 s, not the roughly 1 s the project targets.** chatterbox-tts 0.1.7 generates a whole sentence before returning audio (no streaming), and RTF is about 1 on this GPU. The router chunks by sentence, so each sentence starts about when it would have finished generating; short sentences are better. Pocket TTS stays faster to first sound. This is a real cost of the GPU voice; the plan accepts it (richer emotion on mains power), but D-33 may deserve a second look.
- **Speech recognition latency regression was not measured.** The plan asks for a parallel `turn.timing` check with the HUD running; that needs live Groq turns and the HUD, which this autonomous run did not do. The hardware test measures only the voice. With 3.3 GB held, about 1.5 GB of the 6 GB remains while loaded; the policy's start condition (3823 MB free) protects the HUD and others from starting it when VRAM is scarce.
- The GPU utilisation on this desktop spikes briefly (one reading of 87 % with nothing running), so a single reading made the policy flap and skipped my first hardware run; the policy uses the median of three readings 0.25 s apart.

## Transitive packages (chatterbox-tts 0.1.7 tree, engines/chatterbox/uv.lock, 114)

aiofiles, annotated-doc, annotated-types, antlr4-python3-runtime, anyio, audioread, brotli, catalogue, certifi, cffi, cfgv, charset-normalizer, chatterbox-tts, click, cloudpickle, colorama, conformer, decorator, deprecated, diffusers, distlib, einops, fastapi, ffmpy, filelock, fsspec, gradio 6.8.0, gradio-client, groovy, h11, hf-xet, httpcore, httpx, huggingface-hub, identify, idna, importlib-metadata, jaconv, jinja2, joblib, lazy-loader, librosa, llvmlite, markdown-it-py, markupsafe, mdurl, ml-dtypes, mpmath, msgpack, narwhals, networkx, nodeenv, numba, numpy 1.26.4, omegaconf, onnx 1.23.2, opentelemetry-api, orjson, packaging, pandas, pillow, platformdirs, pooch, pre-commit, protobuf, pycparser, pydantic, pydantic-core, pydub, pygments, pykakasi, pyloudnorm, python-dateutil, python-discovery, python-multipart, pytz, pyyaml, regex, requests, resemble-perth 1.0.1, rich, s3tokenizer, safehttpx, safetensors, scikit-learn, scipy, semantic-version, setuptools 80.10.2, shellingham, six, soundfile, soxr, spacy-pkuseg, srsly, starlette, sympy, threadpoolctl, tokenizers, tomlkit, torch 2.6.0+cu124, torchaudio 2.6.0+cu124, tqdm, transformers 5.2.0, typer, typer-slim, typing-extensions, typing-inspection, tzdata, urllib3, uvicorn, virtualenv, wrapt, zipp (plus the project itself). All are well-known names; nothing unfamiliar or suspicious. Torch and torchaudio resolve to the official `download.pytorch.org/whl/cu124` index. Model weights: official `ResembleAI/chatterbox` (MIT, `gated: false` per the Hugging Face API), downloaded into the user-level Hugging Face cache (`C:\Users\avina\.cache\huggingface`), outside the repo; no model file is committed.

## Deviations from Plan

1. **[Rule 3 - Blocking] `constraint-dependencies = ["setuptools<81"]`** in `engines/chatterbox/pyproject.toml`. The first real load failed (`'NoneType' object is not callable`): resemble-perth, Chatterbox's output watermarker, imports `pkg_resources`, which setuptools 82+ removed, so the watermarker class is None. The lock had resolved setuptools 84. The constraint only caps the version of a package torch already pulls in (84.0.0 -> 80.10.2); no package was added and the watermark stays on. This is the one change beyond the plan's literal pins; flagged because of the instruction to report anything beyond them.
2. **[Rule 2] Control frames and median GPU look.** Added the bit-31 control frame for `load`/`vram` answers (the plan only described audio frames), and the median-of-three nvidia-smi reading plus the System32 fallback for `nvidia-smi` (found during the hardware run; this shell's PATH lacked System32). `own_vram_mb` and a post-speech cooldown keep Chatterbox's own VRAM and utilisation from tripping its own policy.
3. **`src/snow/voice/pipeline.py` not edited.** The router already publishes `voice.switch` / `voice.status` through the pipeline's emitter, so no pipeline change was needed. `src/snow/voice/__main__.py` was edited to register the engine (allowed).
4. **Did not perform the plan's `<human-check>`** (charger plug/unplug) and did not measure the speech-recognition regression (see above).

## Known limits (shortcuts)

- A reply cut off by barge-in is not aborted inside the server; the next sentence waits for the one still generating (a few seconds at most). Barge-in itself (playout abort) is unchanged.
- No hysteresis on the policy beyond the median look: a sustained busy GPU or an unplug stops the server on the next 30 s look.
- After an idle unload, the first reply speaks in Pocket while the model reloads (about 40 s); later replies use Chatterbox.
- Chatterbox's default voice differs from Pocket's `marius`; no consented audio reference is configured (Pocket's reference is a built-in preset, which Chatterbox cannot use), so the voice shifts when the GPU voice is active (the D-32 shift the user accepted).
- The first run on a fresh machine downloads the ResembleAI weights (about 3 GB) inside the 300 s load timeout; a slow link may need `load_timeout_s` raised.

## Known stubs

None.

## Pending for the user

1. The charger human-check (D7).
2. Decide whether first-audio of 1.3 to 3.3 s with RTF about 1 is acceptable for the everyday voice while plugged in, or whether Chatterbox should be limited to longer, calmer replies (D-33 follow-up).
3. Optionally supply a consented reference clip (`reference = { path = ..., consent = "self" }` under `[engines.chatterbox]`) so the GPU voice sounds like the Pocket voice.

## Threat flags

None new. T-01-51: separate hash-locked lock with `exclude-newer`, process isolation, scrubbed environment (verified by a test: no GROQ/hub/HF tokens reach it). T-01-52: GpuPolicy plus stop-on-false, measured above. T-01-SC: exact pins; the only extra is the setuptools cap (deviation 1). No audio on disk; `test_no_egress.py` and the no-disk proof still pass.

## Verification

- `uv run pytest tests/voice/test_chatterbox_policy.py -x -q`: 26 passed.
- `uv run pytest -x -q -m "not hardware and not network and not slow and not gpu"`: 423 passed (includes test_no_egress, no-disk proof, test_no_scripts).
- `uv run pytest -m "hardware and gpu" tests/hardware/test_chatterbox.py -x -q -s`: 1 passed (numbers above; "peak VRAM" line printed).
- `ruff check`, `ruff format --check`, `pyright` (0 errors), `snow.contracts.export --check`: clean. `grep -c chatterbox pyproject.toml` is 0; root `pyproject.toml` and `uv.lock` unchanged.
- No Chatterbox process left running; GPU memory back to baseline.

## Self-Check: PASSED

Files exist: engines/chatterbox/{pyproject.toml,uv.lock,.python-version,server.py}, src/snow/voice/tts/chatterbox.py, tests/voice/test_chatterbox_policy.py, tests/hardware/test_chatterbox.py. Commits 588ead8 and 4a6c782 exist.
