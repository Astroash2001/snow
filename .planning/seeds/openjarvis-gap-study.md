# Gap study: OpenJarvis vs Snow (voice pipeline)

Date: 2026-10-28. Ideas only: no code was copied, and nothing from the repo was installed or run.

**Target.** github.com/open-jarvis/openjarvis, a shallow clone of `main` at `dd68dce` (2026-10-27), read only. OpenJarvis paths below are relative to the clone root.

## 1. What it is

- **What it is:** "Personal AI, On Personal Devices". It is a local-first agent platform in Python with a FastAPI server, a React web UI, a Tauri desktop app, chat channels (Telegram, Discord), connectors, evals and a Rust workspace. Voice is a small side module.
- **Licence:** Apache-2.0 (`LICENSE`). We may borrow ideas freely. Copying code would need the notice and a change statement, but we copy none.
- **Activity:** very active. It has 12.2k stars, 100+ contributors, and 100+ commits in the last 30 days. The last speech commit was 2026-10-21 (ElevenLabs TTS).
- **Its own voice status:** `docs/development/roadmap.md:77` rates its voice interface as **"Research-Stage"**. The whole speech stack is about 2,000 lines, against Snow's 4,780 in `src/snow/voice/`.

## 2. Its voice pipeline, end to end

| Stage | OpenJarvis | File |
|---|---|---|
| Wake | **None.** In the CLI you press Enter on an empty line to talk. In the web UI you click the mic button. | `src/openjarvis/cli/_voice_chat.py` (`read_voice_input`), `frontend/src/components/Chat/MicButton.tsx` |
| VAD / end of turn | An **RMS energy gate**: 500 RMS counts as voice, 1.5 s of silence stops the turn, it gives up after 5 s with no speech, and a turn is capped at 30 s. The web UI has no VAD (click to stop). | `src/openjarvis/speech/voice_io.py` (`record_until_silence`) |
| STT | It probes backends in this order: local **faster-whisper** (default model `base`, compute type float16 with fallback), then OpenAI `whisper-1`, then Deepgram `nova-2` with `smart_format`. It runs once per turn on the whole WAV. There is no prompt or vocabulary, no `vad_filter`, no partials, and language is optional (`speech.language`). | `speech/_discovery.py`, `speech/faster_whisper.py`, `speech/openai_whisper.py`, `speech/deepgram.py`, `core/config.py:1623` |
| Echo / barge-in | **None, because it never listens while it speaks.** The CLI records, then calls `sd.play` + `sd.wait`. The web UI uses `getUserMedia({audio:true})`, so Chromium's own echo cancellation is on by default, and it has a manual Stop. | `voice_io.py` (`play_wav`), `frontend/src/hooks/useSpeech.ts`, `frontend/src/lib/tts.ts` |
| TTS | The default is **Kokoro (PyTorch)**, voice `bm_george`, with `device="auto"`, so it **runs on CUDA when available**. One KModel is shared across language pipelines. Fallbacks are OpenAI TTS, Cartesia (`/tts/bytes`, not streaming) and ElevenLabs. It synthesises the **whole reply** before playing. | `speech/kokoro_tts.py`, `speech/_tts_discovery.py`, `speech/cartesia_tts.py` |
| Text for speech | `toSpeakableText` strips code blocks, URLs, markdown and emoji. | `frontend/src/lib/message-text.ts` |
| Audio I/O | `sounddevice` in blocking mode with the default devices. In the web UI, MediaRecorder sends webm to `/v1/speech/transcribe`, and replies play through an `<audio>` element. | `voice_io.py`, `server/api_routes.py:990` |
| Threading | The CLI is synchronous. The server runs STT in `asyncio.to_thread`. Kokoro sits behind an RLock. The web UI keeps one shared player with an abort token, so two replies never overlap. | `kokoro_tts.py`, `frontend/src/lib/tts.ts` |

## 3. Side by side

| Stage | Snow | OpenJarvis | Who is ahead |
|---|---|---|---|
| Wake | openWakeWord "Hey Snow", trained on the user's voice, with preroll | Enter key or click | Snow |
| VAD / turn | Silero + Smart Turn (stop 0.7 s), max silence, wake-alone window | RMS 500, 1.5 s of silence | Snow |
| STT final | Groq whisper-large-v3-turbo, `language=en`, prompt, a silence/hallucination drop, local fallback | faster-whisper `base` or whisper-1 or Deepgram nova-2, no prompt | Snow on accuracy; their Deepgram option is the one novelty |
| STT live | Moonshine tiny partials | none | Snow |
| Echo | livekit AEC3 with a warm-up guard, an echo-word filter and speaker verification | avoided by half-duplex | Snow in capability; theirs is simpler and has no self-echo by design |
| Barge-in | pause at 150 ms, check, then cut or resume; the brain is told what the user heard | Stop button only | Snow |
| TTS | Kokoro **ONNX on CPU, 10 threads**, streamed by clause; Cartesia, Chatterbox and Pocket routed | Kokoro **PyTorch on GPU if present**, whole reply | Snow on latency and design; theirs is lower on CPU cost |
| Backend failure | per-role chains, cooldowns, health | first healthy backend, cached per session; on failure it drops the backend and tries the next | about equal |

## 4. What they do right that we don't (ranked by impact on Snow's live issues)

1. **Half-duplex as a deliberate mode (self-echo).** OpenJarvis never hears itself because it never listens while speaking.
   - *Adopt:* add a "speakers-unsafe" duplex mode to `turn.py`/`bargein.py`. While Snow speaks, only the **wake model** (or a HUD tap or hotkey) can interrupt, never raw VAD speech. Snow never says "Hey Snow", so its echo cannot trigger it.
   - *When it turns on:* when the output path is not the AEC reference, i.e. FxSound or another enhancement APO is in the chain, or when the measured AEC residual is high. Speech within the existing windows stays full duplex.
   - *Effort:* S (a gate in the pause trigger plus one config flag).
   - *Risk:* the "just say stop" feel is lost in that mode, and "Hey Snow, stop" is slower. Make it automatic and visible on the HUD, not the default.
2. **Kokoro on the GPU (CPU cost, first audio).** `kokoro_tts.py` picks CUDA automatically. Snow pins `CPUExecutionProvider` at 10 threads (`src/snow/voice/tts/kokoro.py:83`).
   - Since STT moved to Groq, the "6 GB VRAM is taken by Whisper" argument behind CPU Kokoro no longer holds. Kokoro is 82M parameters, well under 1 GB.
   - *Adopt:* backlog 999.1 is already this. Use the CUDA or DirectML ONNX provider in a **separate process**, because Pipecat pins CPU onnxruntime. Gate it on mains power and an idle GPU, like Chatterbox.
   - *Effort:* M.
   - *Risk:* fights with the HUD WebGL, DLL setup, and a second process to supervise.
3. **A second cloud STT with a different acoustic model (accent mishearing).** Deepgram is a first-class backend in OpenJarvis (`speech/deepgram.py`). It is a different model family from Whisper, and it has free credits.
   - Note that they do **not** tune it for accents; this idea comes from the structure, not from tuning.
   - *Adopt:* add an STT A/B harness that sends the same recorded turns (the "moon"→"moving" set) to Groq Whisper and to Deepgram, and compare word error rates on the user's own voice. Only then decide on a fallback or primary slot. Deepgram's newer models take key-term prompts. That is from my own knowledge, not from this repo, so check it before relying on it.
   - *Effort:* S for the harness, M for the backend.
   - *Risk:* the user's audio goes to one more vendor, and the user must approve that (a constraint: no idle audio leaves the PC, which still holds).
4. **One shared, abortable player with a token fence** (`frontend/src/lib/tts.ts`). Snow's playout already does more, so this is only a check that the HUD and phone never get a second audio path. Effort XS, risk none.

## 5. What we already do better (honestly: nearly everything)

OpenJarvis is a push-to-talk demo next to Snow. It has:

- no wake word, no real VAD and no turn model;
- no partials, no echo cancellation and no barge-in;
- no speaker verification and no tone detection;
- no clause streaming, so the first audio waits for the whole reply.

Its STT defaults (`base` with no prompt) would mishear the user more than Groq turbo with `language=en` and a prompt. **Nothing in it fixes Snow's four live issues directly.** Their only real edge is that they avoid the problem: half-duplex has no echo to cancel.

## 6. Recommended next 3 steps

The first and third steps go beyond OpenJarvis; the comparison only points at them.

1. **Fix the AEC reference rather than tune around it.**
   - Feed AEC3 the **post-FxSound** signal: use a WASAPI loopback capture of the actual output device as the `render()` reference, instead of the pre-FxSound PCM in `aec.py`.
   - Otherwise, refuse to enable voice barge-in when an enhancement APO is in the output path, and fall back to idea 1.
   - This targets the self-echo issue at its cause. It also widens the speaker margin (0.41 vs 0.26), because less of Snow's voice leaks into the check.
2. **Ship idea 1, wake-word-only interruption, as the automatic degraded duplex mode,** so echo can never cut Snow off while step 1 is being proven.
3. **Prime the engines at start and A/B the STT.**
   - Run one throwaway Kokoro synthesis right after `load()`. ONNX's first inference is slow, and Snow's loader in `tts/router.py` loads the engine but never primes it.
   - Then run the recorded-turn Groq vs Deepgram comparison (idea 3) before any change to the STT chain.
