---
phase: 01-always-on-voice-loop
plan: 26
subsystem: voice
tags: [tts, pocket-tts, playout, sentence-chunking, cpu, presence]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "Approved pocket-tts 3.3.0 (01-02), reply.delta/reply.final and the silent fallback (01-16), TurnEngine.reply_finished (01-18), voice pipeline (01-20, 01-22, 01-24)"
provides:
  - "snow.voice.tts: TtsEngine protocol, EngineName, EngineError/EngineLoadError, sanitize(), SentenceChunker, PocketEngine, TtsConfig"
  - "snow.voice.playout.Playout: WASAPI ring buffer, prebuffer, abort, on_first_audio/on_level/on_drained"
  - "Pipeline speaks every reply; presence speaking from the first sample, audio.level (tts), tts.spoken, voice.status, health speech_output"
  - "config/tts.toml (router order, prebuffer, engine switches)"
affects: [01-28 voice router, 01-29 barge-in, 01-31 Cartesia, 01-32 user voice, 01-33 Chatterbox]

commits: 1
plan_head_before: e0bc743454ed56360ed99c7f0aa48ae2d4cd1fe7
plan_head_after: a254664

actuals:
  tokens: 45000
  tasks: 1
  commits: 1

tech-stack:
  added: ["pocket-tts==3.3.0 (CPU-only torch 2.14.1+cpu)"]
  patterns:
    - "Engine runs its blocking generator in an executor thread and hands chunks to the loop through an asyncio.Queue; cancel sets the library's stop event"
    - "Playout callbacks fire on the audio thread and only hop onto the event loop with call_soon_threadsafe, so event order is preserved"
    - "Chunker drops fenced code across deltas and only splits at a boundary followed by whitespace (decimals and file names never split)"

key-files:
  created:
    - src/snow/voice/tts/__init__.py
    - src/snow/voice/tts/base.py
    - src/snow/voice/tts/text.py
    - src/snow/voice/tts/pocket.py
    - src/snow/voice/tts/config.py
    - src/snow/voice/playout.py
    - config/tts.toml
    - tests/voice/test_tts_text.py
    - tests/voice/test_tts_pipeline.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/snow/voice/pipeline.py
    - src/snow/voice/__main__.py

key-decisions:
  - "Preset voice is `marius` (Kyutai tts-voices, voice-donations/Selfie.wav, licence CC0); the model repo kyutai/pocket-tts-without-voice-cloning is CC-BY-4.0 and not gated. Gender and taste are unchecked by ear (pending human check)"
  - "reply_finished now fires at the end of playback (Playout.on_drained); a reply with no text calls it at once"
  - "prebuffer_ms stays 300 (plan acceptance). Measured RTF 0.4 would allow about 100 to 150 ms; left for the user's listening test"
  - "Pocket ignores `emotion` (no style control); it is passed through so the router in 01-28 can use it"

requirements-completed: [SPCH-03, SPCH-04]

coverage:
  - id: D1
    description: "Reply deltas are sanitized, chunked (first clause early), synthesized by Pocket TTS on CPU and played"
    status: tested
  - id: D2
    description: "presence speaking at first sample, listening after drain; audio.level tts only while speaking; tts.spoken chars"
    status: tested
  - id: D3
    description: "Empty reply: no audio, no speaking state, no speaker opened, reply_finished at once"
    status: tested
  - id: D4
    description: "Markdown, code fences (split across deltas), URLs, emoji never reach the engine"
    status: tested
  - id: D5
    description: "Real Pocket TTS on CPU: first chunk time and real-time factor"
    status: tested
  - id: D6
    description: "Hear the reply on headphones, orb pink and pulsing with the voice, back to listening after"
    status: pending
    reason: "Human check needs speakers; not run by this agent"
---

# Phase 1 Plan 26: Everyday local voice Summary

Snow now answers out loud: reply text is cleaned and cut at the first clause, synthesized by Pocket TTS on the CPU, played through a prebuffered WASAPI stream, and the orb states and levels follow the actual audio.

## What was built

- `tts/text.py`: `sanitize()` removes fences, inline code, images and links (keeps link labels), URLs, headings and list markers, emphasis, emoji and bracket residue. `SentenceChunker.feed/flush`: first chunk at the first comma, semicolon, colon or dash once it holds 3 words, else at the first sentence end; later chunks at sentence ends. A boundary needs the whitespace after it, so `3.5`, `example.com`, `Dr.`, `Mr.`, `e.g.`, `i.e.` and `1.` list numbers do not split. Fenced code is dropped even when the fence is split across deltas.
- `tts/pocket.py`: `PocketEngine` sets `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, `torch.set_num_threads(4)`, loads `TTSModel` (CPU only) and the preset voice state; `stream()` runs the generator in a worker thread and yields float32 chunks; `cancel()` sets the library's stop event. The weights were not gated, so there was no auth gate.
- `playout.py`: `Playout` with a thread-safe ring buffer, 20 ms blocks, `WasapiSettings(auto_convert=True)`, prebuffer, `abort()` (clears, `stream.abort()` then `start()`), first-audio / level (about every 40 ms, RMS mapped from -60..0 dBFS) / drained callbacks.
- `pipeline.py`: `reply.delta` feeds the chunker and a per-reply task speaks chunks in order; `reply.final` closes the text (and speaks it whole when no deltas came, as for wake acknowledgements). `presence.state(speaking)` at the first sample, `audio.level(tts)` only while speaking, `tts.spoken(engine, chars, first_audio_ms)` at drain. `engine.reply_finished()` now runs at the end of playback (01-18's hand-over); for replies no turn waits for (acks) the pipeline emits `listening` itself. Mute aborts speech at once. `voice.status` and `health.subsystem(speech_output)` are republished with the other health rows (start, hub reconnect); `down` if the voice fails to load, and replies then stay silent without blocking the loop.
- `config/tts.toml` and `TtsConfig` (strict). `__main__.py` builds `PocketEngine` when enabled.

## Measurements (this laptop, CPU, 4 torch threads)

| What | Result |
|------|--------|
| torch | 2.14.1+cpu, `torch.cuda.is_available()` False; no nvidia or triton packages in the lock |
| Model load, warm cache | 8.7 s (first run 78 s including the download) |
| First chunk (80 ms of audio) after `stream()` starts | 0.09 to 0.11 s (cold and warm) |
| Real-time factor, one sentence of about 2.2 s | 0.40 (cold) and 0.42 (warm) |
| First clause "Well, I think so, yes." to 300 ms of audio buffered | 0.19 s |

Derived, not measured end to end: spoken reply starts about 0.2 s after the first clause leaves the chunker, plus the LLM time to produce that clause. Nothing was played through speakers.

## Preset voice and licence

`marius`: Kyutai `tts-voices/voice-donations/Selfie.wav`, a voice-donation clip licensed CC0 (Kyutai's catalog page). Model weights `kyutai/pocket-tts-without-voice-cloning`: CC-BY-4.0, ungated; attribution should go into the project credits before distribution. The predefined voice is an embedding downloaded from that repo, so no voice is recorded or cloned.

## New dependencies

Top-level: `pocket-tts==3.3.0` only. New transitive packages in `uv.lock` (22): annotated-doc, click, einops, fastapi, fsspec, hf-xet, huggingface-hub, jinja2, markupsafe, networkx, opentelemetry-api, pocket-tts, python-multipart, safetensors, sentencepiece, setuptools, shellingham, starlette, tokenizers, torch, typer, uvicorn. Torch is a single 124 MB win_amd64 wheel from PyPI (Windows PyPI wheels are CPU-only), so no custom index was needed. `onnxruntime` stays at 1.24.4 (pipecat's pin). fastapi, starlette and uvicorn come from pocket-tts's own optional web server, which Snow never starts. `pip-audit` was not run in this session.

## Deviations from Plan

1. **[Rule 3 - Blocking] `src/snow/voice/__main__.py` edited** (not in files_modified): the worker had to build the engine and pass `tts_cfg`, or nothing would speak.
2. **Speech orchestration lives in `pipeline.py`** (a `_Reply` record and `_speak*`/`_finish` methods) instead of a new module, to stay inside the file list.
3. **Injectable `tts`, `tts_cfg`, `stream_factory`** on `VoicePipeline`/`build_pipeline` (all optional, default off) so tests need no device; existing flows are untouched when `tts` is None.
4. **Levels about every 40 ms** (2 blocks of 20 ms) rather than 31 ms, because the 31 ms floor falls between blocks.
5. **prebuffer left at 300** although RTF 0.4 would allow less (plan acceptance fixes `prebuffer_ms = 300`).

No contract changes: every event used (ReplyDelta, ReplyFinal, PresenceState, AudioLevel, TtsSpoken, VoiceStatus, HealthSubsystem) is already in the 01-04 catalog.

## Known limits and risks

- `ReplyDelta` has no emotion field, so chunks spoken before `reply.final` get emotion `neutral`. Harmless for Pocket (no style control); the router in 01-28 must take the emotion from somewhere earlier if Cartesia is to use it for streamed chunks.
- The turn engine's `reply_timeout_s` (20 s of audio) still ends the wait mid-speech for a reply longer than that, and the wake acknowledgement is spoken while the engine is not deaf. Both are for 01-29 (echo and barge-in); headphones are assumed.
- If synthesis ever falls below real time the speaker just goes quiet during the gap (no re-buffering); at the measured RTF this does not happen.
- A `_drained` hop that raced a mute could land on the next reply; the window is a few microseconds and the effect would be a reply listening early.

## Known stubs

None.

## Pending (needs the user)

- Human check: on headphones, wake Snow and ask a question; hear the reply in the Marius voice, the orb turns pink and pulses with it, and returns to listening. Also judge whether the voice suits (the user's own voice comes in 01-32) and whether `prebuffer_ms` can drop to about 150.

## Threat flags

None new. T-01-43 (sanitize before any engine, tested incl. split fences), T-01-44 (weights only via the approved package from Kyutai repos, implicit HF token disabled), T-01-SC (exact pin, hash-locked lock, installed after the 01-02 verdict) are implemented as planned. Audio is never written to disk (in-memory chunks and ring buffer only).

## Verification

- `uv run pytest tests/voice/test_tts_text.py tests/voice/test_tts_pipeline.py -x -q`: 19 passed.
- `uv run pytest -m slow tests/voice/test_tts_pipeline.py -q`: 1 passed (real Pocket TTS, numbers above).
- `uv run pytest -x -q -m "not hardware and not network and not slow"`: 327 passed (includes test_no_egress, the no-disk proof and test_no_scripts).
- `ruff check`, `ruff format`, `pyright`: clean.
- Acceptance: `pocket-tts==3.3.0` in pyproject; `set_num_threads` present and no `cuda` in `pocket.py`; `prebuffer_ms = 300` and the router order line in `config/tts.toml`.

## Self-Check: PASSED
