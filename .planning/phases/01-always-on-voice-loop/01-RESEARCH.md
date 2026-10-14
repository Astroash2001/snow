# Phase 1: Always-On Voice Loop - Research

**Researched:** 2026-10-15
**Domain:** Local always-on voice pipeline (wake, VAD/turn, STT, TTS, barge-in), multi-provider LLM fallback chain with privacy routing, event bus + durable log, process supervision, Electron HUD shell, Windows secrets, CI
**Confidence:** MEDIUM (stack and architecture HIGH-MEDIUM and partly measured on this machine; wake word "Hey Snow" model, STT latency/VRAM, Cartesia credit balance API and local-voice speed are open risks with spike gates)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Persona and replies**
- **D-01:** Snow talks like J.A.R.V.I.S. from the MCU (Paul Bettany): composed, competent, natural tone, with dry, sarcastic British-style humor as the normal register. The user wants it "as close to Jarvis as possible".
- **D-02:** Snow addresses the user as "sir", used naturally, the way Jarvis does.
- **D-03:** Guardrail: sarcasm switches off when something goes wrong (errors, failures, unreachable services) or when the user sounds stressed. In those moments Snow is plain, direct and helpful.
- **D-04:** Reply length matches the question. The LLM judges per turn: banter gets a line, a real question gets a full answer. No fixed sentence cap, but the reply must still start speaking within about 1 second (SPCH-04), so stream sentence by sentence.
- **D-05:** Voice is a male Cartesia voice. The researcher shortlists male Cartesia voices that fit a calm, dry, British-leaning Jarvis character. The user picks the final voice in a short audition step. The voice ID lives in config.
- **D-06:** Vocal emotion is natural and mostly upbeat. The LLM picks one emotion per reply from a small validated set (for example content, calm, excited, sympathetic, neutral), defaulting to warm or content, with strong emotions only when the moment calls for it. Invalid values fall back to neutral.

**Conversation flow**
- **D-07:** No push-to-talk key. The user wakes Snow by name only, like Tony calling Jarvis. VOIC-02 (push-to-talk hotkey) is dropped from Phase 1. ROADMAP.md success criterion 1 and REQUIREMENTS.md were updated on 2026-10-14 (VOIC-02 moved to Out of Scope). A developer-only test input (for example, injecting a recorded WAV or typed text into the pipeline for tests and CI) is allowed, but it is not a user-facing feature. — **Reversibility:** reversible — adding a hotkey later is a small, isolated input source on the event bus.
- **D-08:** Wake once, stay in conversation. After "Hey Snow", Snow keeps listening with no re-wake until the user ends it ("that's all", or similar) or about 30-60 seconds of silence pass. Then it returns to wake-word-only listening.
- **D-09:** Wake cue follows Jarvis behavior:
  - "Hey Snow, <command>" in one breath: Snow acts and replies directly. No acknowledgement first. The audio after the wake phrase must be captured as part of the turn (pre-roll/continuation), not lost.
  - "Hey Snow" alone: Snow speaks a short, LLM-written acknowledgement in Jarvis style (for example "Sir?") and waits.
  - No chime or earcon. The orb reacts immediately (HUD within 100 ms, HUD-03).
- **D-10:** Two quiet states:
  - **Soft sleep:** "Snow, go to sleep" (by voice). The mic stays on locally, and Snow ignores everything except the wake phrase.
  - **Hard mute:** the mic is fully off. Triggered by voice ("Snow, mute") or by clicking the orb or the tray icon. Unmute is by click only, because a muted mic cannot hear "unmute". The HUD must make the hard-mute state unmistakable (VOIC-03).

**HUD (Phase 1 form)**
- **D-11:** Two window forms:
  - **App open:** the full dashboard window.
  - **App minimized:** the full dashboard stops rendering (no background GPU/CPU cost), and a small always-on-top mini indicator shows that Snow is present and active.
  — **Reversibility:** costly — Phase 6 builds the ASCII orb, the full dashboard and the corner widget on top of this two-form window model, so changing it later touches both windows and the Electron shell.
- **D-12 (revised 2026-10-14):** The presence element is the ASCII network orb from day one, never a plain glowing circle. The user rejected the plain-circle version after seeing generated mockups: "I want the ASCII interpretation of the orb everywhere." In Phase 1 it is a 2D glyph orb: a sphere of nodes and connecting lines drawn from ASCII characters, digits and code fragments, each glyph keeping its own color, cyan to violet, glow on the orb only. It moves with the user's voice and with Snow's voice and is colored by state (sleeping, listening, thinking, speaking, muted). The same component appears in the full and mini forms. The orb needs audio-level events on the bus for both mic input and TTS output. Visual target: `.planning/phases/01-always-on-voice-loop/refs/snow-vision-ascii-orb-dashboard.png` (the orb, not the page around it). — **Reversibility:** reversible — Phase 6 swaps the renderer behind the same `Presence` props.
- **D-31:** The ASCII orb is Snow's only visual identity. A tiny rendering of the orb is also the app icon, the tray icon and Snow's avatar in the transcript. No snowflake or other logo. The rest of the interface stays clean (dark panels, modern sans-serif text, as in the reference image); only the orb is ASCII. Phase 6 upgrades the orb to the full 3D shader version (letters revealed on zoom, bloom, glyph atlas from the user's code) without changing where it appears.
- **D-13:** Mini indicator: top-right corner by default, draggable, position remembered, click-through so it never blocks clicks on the windows below, and clicking it opens the full dashboard. It shows only the orb while idle. While in conversation, a one-line caption of what Snow heard appears next to it, then fades.
- **D-14:** The full dashboard shows the transcript chat-style for the current conversation: the user's words updating live as they speak (VOIC-08), Snow's replies, newest at the bottom. The view clears when the conversation ends. Full history stays in the event log (the history view is Phase 6).
- **D-15:** The full dashboard also shows subsystem health (each subsystem up or down, QUAL-03), the mute or sleep state, and which voice is active (Cartesia or local) with remaining Cartesia credits.

**Fallback voice and privacy**
- **D-16:** Use Cartesia for every reply until credits run out or Cartesia is unreachable. Then switch to the local voice (kokoro-onnx) automatically, and switch back when Cartesia works again.
- **D-17:** On the first reply after a switch to the local voice, Snow mentions it once in an LLM-written line, in character (for example, a dry remark about its "budget voice"). The HUD always shows the active voice and the remaining credits.
- **D-18:** The event log stores text transcripts (what the user said, what Snow replied) plus event metadata. Raw audio is never written to disk by the conversation pipeline. — **Reversibility:** reversible going forward — audio not saved is gone, but the setting can change for future turns.
- **D-19:** Transcripts are kept 30 days, then deleted automatically. The retention period is configurable.

**LLM layer (added 2026-10-14 from the user's advisor session; locked)**
- **D-20:** Scope of Snow's own LLMs. Coding work is done by the user's Claude Code and Antigravity subscriptions, driven through the shell. The LLMs below are only Snow's own brain: conversation, turning speech into clean instructions for the agents, summarizing results, answering general questions, and later screen reading. Free options only. Experiential Labs credits are shared with the user's other projects, so fallbacks carry real traffic.
- **D-21:** Three roles, each with an ordered fallback chain (CORE-04, CORE-08). Snow tries entries in order and moves to the next on 429, `insufficient_quota`, 5xx, timeout or connection error.
  - **brain** (understanding, planning, summaries, general Q&A): 1) Experiential Labs `gpt-5.6-luna`; 2) Google AI Studio, newest Gemini Flash; 3) NVIDIA NIM, DeepSeek V4 Pro, then Kimi K3; 4) OpenRouter, Nemotron 3 Super 120B `:free`.
  - **fast** (spoken replies, intent detection, transcript cleanup): 1) Groq `openai/gpt-oss-120b`; 2) Groq Qwen3.8 27B; 3) Experiential Labs `deepseek-v4-flash`; 4) OpenRouter, any `:free` model with tool calling.
  - **vision** (Phase 5 screen reading; configured now, used in Phase 5): 1) Experiential Labs `gpt-5.6-luna`; 2) Google AI Studio Gemini Flash; 3) Experiential Labs `qwen3.8-27b`.
  - Exact model IDs other than those already given come from each provider's `GET /models` during the Phase 1 gateway spike. Do not guess IDs.
  — **Reversibility:** reversible — chains, order and models are config.
- **D-22:** Providers, all OpenAI-compatible. Use the plain `openai` SDK with `base_url`. Never use `litellm`.
  - Experiential Labs: `https://api.experientiallabs.ai/v1` (key `xpl_...`)
  - Groq: `https://api.groq.com/openai/v1` (key `gsk_...`)
  - Google AI Studio: `https://generativelanguage.googleapis.com/v1beta/openai/`
  - NVIDIA NIM: `https://integrate.api.nvidia.com/v1` (key `nvapi-...`)
  - OpenRouter: `https://openrouter.ai/api/v1` (key `sk-or-...`; free models only; the key's credit limit is 0)
- **D-23:** Chains, providers, model IDs and per-model quirks live in config, not code. Adding or reordering a provider is a config edit. Quirks are per model in config (for example, `gpt-5.6-luna` rejects the `temperature` parameter).
- **D-24:** Keys live only in Windows Credential Manager (keyring), never in a `.env` file. A setup command prompts for each provider key and stores it (SAFE-09). Keys never appear in config, logs, events or the HUD. The user never pastes keys in chat.
- **D-25:** Missing keys must not block Phase 1. A provider with no stored key is skipped in every chain and shown as "not configured" in subsystem health.
- **D-26:** Privacy routing (SAFE-12). Google AI Studio free tier and OpenRouter free models may log or train on data. They may receive only general questions and non-sensitive screenshots. Code, diffs, agent output, file contents and anything personal never go to them. If the only remaining providers in a chain are not allowed for that data, the call fails clearly instead of sending.
- **D-27:** Free-tier limits (CORE-09). Per-provider request and token counters; cool-down after a 429 using the reset headers; skip a provider while it cools down. Groq caps about 200K tokens/day per model, so summary inputs stay compact: built from recorded events, never full diffs or logs.
- **D-28:** Every LLM response records which provider and model served it (CORE-10). The HUD shows the active provider per role. Snow tells the user briefly, in character, when it has switched because of limits (same pattern as the voice switch in D-17).
- **D-29:** Phase 1 gateway spike: call `GET /models` on each provider with a stored key to confirm exact model IDs, streaming and tool calling (and image input for vision models). Record what each model supports in config or a spike note.
- **D-30:** Phase 1 latency test: compare Groq `openai/gpt-oss-120b` with Experiential Labs `deepseek-v4-flash` for time to first token and time to first audio. Pick the fast-role primary from the measured numbers.

### Claude's Discretion
- How "mute", "go to sleep" and "that's all" are recognized. Recommended: deterministic local phrase matching on the transcript, not an LLM call, so they work instantly and when the gateway is down.
- How the wake-alone acknowledgement stays LLM-written without adding latency (for example, a small pool of LLM-generated acknowledgements refreshed in the background). It must not be a hardcoded phrase (SPCH-01).
- Exact silence timeout inside the 30-60 second range, the orb's colors and motion, the dashboard layout and the mini indicator size.
- How the HUD gets credit balance and voice status from the core.
- How the fallback chain plugs into the voice pipeline (Pipecat's `OpenAILLMService` takes one `base_url`, so a chain needs a thin wrapper or a custom service), and how request data is tagged for privacy routing (D-26).
- Where enrollment or wake-word training recordings live, if any are needed. These are separate from the conversation log, created only by an explicit user action, and stored locally.

### Deferred Ideas (OUT OF SCOPE)
- **Phase 6 visual (locked by the user):** the orb moves and reacts as Snow speaks and as the user speaks, exactly like the Age of Ultron Jarvis. No ambient or background lighting effects; all effects live on the orb itself. Full dashboard when open, mini corner form when minimized (D-11).
- **Always-listening mode (Phase 2 or later):** an optional mode with no wake word, which reacts only to the verified user's voice when the user addresses Snow. Needs speaker verification first.
- **Push-to-talk hotkey:** removed from v1 by user decision (D-07). Revisit only if the wake word proves unreliable.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CORE-01 | Snow starts automatically at Windows logon and keeps running | Task Scheduler "At log on" task via `Register-ScheduledTask` with restart settings, `ExecutionTimeLimit` 0, battery flags; hub launches Electron with `--autostart` (Pattern 5, Code Example 6, Pitfalls 8, 9) |
| CORE-02 | Recovers on its own after a crash of any subsystem | Hub + worker-process topology, supervisor with backoff + heartbeat + Job Object `KILL_ON_JOB_CLOSE`; Task Scheduler restarts the hub (Pattern 5) |
| CORE-03 | Every action is a typed event (source, reason, risk tier, result) | Pydantic discriminated-union envelope, SQLite WAL durable log + ephemeral class, JSON Schema -> TS pipeline (Pattern 2, Code Examples 4-5) |
| CORE-04 | Provider, base URL, model per role are config only | `models.toml` with providers/roles/chains/quirks, `openai` SDK client per provider (Pattern 3, Code Example 2) |
| CORE-08 | Ordered fallback chain; moves on 429/insufficient_quota/5xx/timeout/connection error; skip keyless providers | `ChainLLMService` overriding `get_chat_completions`, `max_retries=0`, error classification table (Pattern 3, Pitfall 4) |
| CORE-09 | Per-provider counters, cooldown from reset headers | Per-provider header table, duration parser, cooldown policy (Pattern 3, Rate-limit table) |
| CORE-10 | Each LLM response records provider+model; HUD shows; Snow announces switches | `llm.call` durable event, `health.changed` role rows, switch-notice flow (Pattern 3) |
| VOIC-01 | Wake by "Hey Snow"; local; no idle audio leaves PC | openWakeWord runtime (measured 2.05 ms/frame), interim `hey_jarvis`, livekit-wakeword training recipe, network-guard test (Pattern 1, Wake Word section) |
| VOIC-03 | Hard-mute mic, unmistakable on HUD | Mute = close the sounddevice InputStream; persisted mute state; confirmed-state events (Pattern 6) |
| VOIC-04 | Local streaming English STT | faster-whisper turbo int8_float16 pseudo-streaming partials; CUDA DLL loading (Pattern 4, Code Example 1) |
| VOIC-05 | Waits for the user to finish a thought | Silero VAD + Smart Turn v3.2 (bundled CPU ONNX) driven by an external TurnEngine (Pattern 1) |
| VOIC-06 | Barge-in stops speech and cancels the reply | Pipecat interruption propagation + local playout abort, headphones assumption (Pattern 7) |
| VOIC-08 | Live transcript while speaking | `transcript.partial` ephemeral events from rolling re-decode (Pattern 4, HUD Data Needs) |
| SPCH-01 | LLM-written spoken lines; no hardcoded phrases | Persona prompt, background ack pool, lint test forbidding string literals into the speech path (Pattern 8) |
| SPCH-02 | LLM chooses emotion; Cartesia speaks it | Leading `[[emotion]]` header parsed against the Cartesia enum, inline `EMOTION_TAG` (Pattern 8, Code Example 3) |
| SPCH-03 | Local voice when Cartesia unavailable | Custom failover strategy + probe + kokoro-onnx, with MEASURED speed warning (Pattern 9, Pitfall 3) |
| SPCH-04 | Reply starts within ~1 s | Latency budget table, stage timing events, `UserBotLatencyObserver`, speculative generation option (Pattern 10) |
| HUD-03 | HUD reacts within 100 ms from local events | Event path wake thread -> hub -> HUD, Canvas 2D atlas orb, `performance.mark` test (Pattern 11) |
| QUAL-01 | Typed, linted, tested CI before merge | GitHub Actions windows-latest, ruff/pyright/pytest, Biome/tsc/Vitest, schema-drift gate; branch protection needs a public repo or paid plan (CI section, Open Question 2) |
| QUAL-03 | Structured logs + subsystem health on HUD | structlog JSON + redaction, loguru bridge, health snapshot/deltas (Pattern 12) |
| SAFE-09 | Secrets in Windows Credential Manager only; setup command | `keyring` WinVaultKeyring, `snow setup` with getpass, canary-secret test (Pattern 13) |
| SAFE-12 | Provider trust levels; private data never to untrusted; fail clearly | `trust` per provider, mandatory `DataClass` on every call, `PrivacyBlockedError`, zero-HTTP test (Pattern 3) |
</phase_requirements>

## Summary

Phase 1 is a greenfield Python 3.12 core plus an Electron/React HUD talking over a loopback WebSocket. The voice stack (Pipecat 1.12, faster-whisper turbo, openWakeWord, Silero, Smart Turn v3.2, Cartesia sonic-3.6, kokoro-onnx) installs cleanly on Python 3.12 / Windows with no torch (verified by installing it in a scratch venv this session). The cheap local models are very cheap on this CPU: openWakeWord 2.05 ms per 80 ms frame, Silero 0.12 ms per chunk. The expensive unknowns are the "Hey Snow" model (no pretrained model exists; train with livekit-wakeword off-machine, use pretrained `hey_jarvis` meanwhile), faster-whisper latency/VRAM on the RTX 4050 (not measured: disk full, see below), and the local fallback voice (kokoro-onnx int8 measured at real-time factor 0.86-1.03 warm on this CPU, i.e. it cannot start a reply in 1 s except for very short first chunks).

Two things must be decided before planning is useful. (1) The machine has about 1.4 GB free on C: (it was 0.22 GB mid-research until the scratch spike and the uv download cache were removed); CUDA wheels, the Whisper model, Electron and the Python env need roughly 8-10 GB, and wake-word training data needs tens of GB, so the user must free space first. (2) CORE-02 ("killing voice, brain or HUD brings it back") is only honestly testable if those subsystems are separate OS processes, which the CLAUDE.md single-"snow-core" sketch does not provide. This research recommends one small hub process (event bus, SQLite log, WebSocket server, supervisor, health) plus worker processes (`voice`, `brain`) plus the Electron HUD, all speaking one JSON-over-WebSocket protocol; the hub is restarted by Task Scheduler.

The thinnest real end-to-end slice (Walking Skeleton) is: hub + SQLite log + WS + HUD orb/transcript driven by real events, then a real mic through wake (interim `hey_jarvis`) -> VAD/Smart Turn -> faster-whisper -> fast-role Groq chain -> kokoro audio out, with the dev WAV-injection input (D-07) used for CI. Everything else (Cartesia, fallback chains with cooldowns, privacy routing, sleep/mute modes, ack pool, supervisor/autostart hardening, custom wake model, CI branch protection) layers on top.

**Primary recommendation:** Build hub-and-worker processes around one typed event contract (Pydantic -> JSON Schema -> TS), use Pipecat only for STT/LLM/TTS plumbing with an external, plain-Python `TurnEngine` that owns wake/sleep/mute/conversation state, and gate three spikes in Wave 0 (Pipecat fit with go/no-go, STT latency on GPU, gateway `GET /models` + fast-role latency) before committing the rest.

## Critical Findings the Planner Must Act On

| # | Finding | Evidence | Action |
|---|---------|----------|--------|
| F1 | **Disk is nearly full.** C: has 1.4 GB free of ~476 GB (was 0.22 GB after the research spike, cleaned afterwards). `uv pip install nvidia-cublas-cu12` failed with "There is not enough space on the disk. (os error 112)". | [VERIFIED: PowerShell `Get-PSDrive C` and uv error output, 2026-10-15] | Wave 0 task 0: user frees at least 15 GB. Put HF/uv caches and the wake-word training workspace off-machine or on another drive. Blocks CUDA wheels (~1.3 GB), Whisper model (~1.6 GB), Electron (~0.3 GB), venvs. |
| F2 | **Local fallback voice is not faster than real time here.** kokoro-onnx 0.6.1 int8 on i5-12500H CPU: warm RTF 0.86-1.03; cold first call per voice RTF 1.23-1.50; `create_stream` first chunk 11.7 s for two sentences. | [VERIFIED: local benchmark 2026-10-15, see Measured Data] | Design local TTS as clause-chunked with a 300-500 ms pre-roll buffer; spike kokoro fp32 and `pocket-tts` before accepting D-16's "kokoro-onnx" as sufficient. SPCH-04 (~1 s) can only be met on the local voice for a short first clause. |
| F3 | **No "Hey Snow" model exists and cannot be trained on this machine.** Official tooling targets Linux/Colab; livekit-wakeword documents macOS/Ubuntu only. | [CITED: github.com/livekit/livekit-wakeword README], [CITED: github.com/alfiedennen/openwakeword-colab-2026] | Interim: pretrained `hey_jarvis` (works, verified loads on Py 3.12 Windows). Train "hey snow" in Colab/cloud GPU (livekit-wakeword, Apache-2.0); non-blocking for the skeleton. |
| F4 | **No git remote exists** (`git remote -v` empty), and branch protection with required checks is not available on GitHub Free private repos. | [VERIFIED: `git remote -v` empty], [CITED: docs.github.com protected branches page: branch restrictions in public repos on Free; private needs Team/Enterprise (org)] | Success criterion 5 needs the user to either make the repo public or upgrade. Ask in discuss/plan (Open Question 2). |
| F5 | **Default `python` on PATH is 3.10.9 and `python3` is 3.14.4; 3.12 was not installed.** uv downloaded CPython 3.12.13 during this research. | [VERIFIED: `python --version`, `uv python list`, pipecat banner "Python 3.12.13"] | Pin `.python-version` = 3.12 and run everything through `uv run`; never call bare `python`. |
| F6 | The Pipecat OpenAI service's `get_chat_completions` is the clean seam for the multi-provider chain; the SDK's default `max_retries=2` would delay failover. | [VERIFIED: pipecat/services/openai/base_llm.py:325-361 read this session], [CITED: github.com/openai/openai-python README retries] | Subclass and override; construct every `AsyncOpenAI` with `max_retries=0`. |

## Project Constraints (from CLAUDE.md)

- **Shell/runtime:** Electron is the v1 HUD shell (not Tauri). Python 3.12 core + TS/React HUD over loopback WebSocket. Ignore Tauri/Rust/MSVC steps.
- **LLM layer:** plain `openai` SDK + `base_url` per provider; **never litellm** (compromised PyPI releases 1.82.7/1.82.8). Per-role fallback chains across Experiential Labs, Groq, Google AI Studio, NVIDIA NIM, OpenRouter (free models only). `gpt-5.6-luna` rejects `temperature`.
- **Secrets:** keys only in Windows Credential Manager; no `.env`; never in config, logs, events, HUD. Code and personal data never go to Google AI Studio free or OpenRouter free.
- **Provider independence / swap by config:** no hard dependency on any single provider/account; LLM layer swappable by configuration, not code.
- **Hardware:** 6 GB VRAM; local models limited to wake word, STT, (later) speaker verification; large LLMs remote. Windows 11 primary host.
- **Voice:** Cartesia TTS with local fallback; local faster-whisper STT on GPU; local openWakeWord; English only, headphones assumed, no AEC in v1.
- **Latency:** HUD feedback < 100 ms; spoken reply starts in about 1 s.
- **Security:** voice + always-on + full permissions is high risk; approval tiers/speaker verification are Phase 2, but secret isolation and no-idle-audio-egress are Phase 1.
- **Process model:** per-user Task Scheduler "At log on" job, NOT a Windows Service (Session 0 isolation). Run from `uv`-managed env with `uv sync --frozen`; hash-locked deps, `exclude-newer` delayed adoption.
- **Quality bar:** ruff (ASYNC, S, UP), pyright strict on `snow_core`, pytest + pytest-asyncio, Biome, Vitest, Playwright; gitleaks + pip-audit in CI; structlog with redaction.
- **No hardcoded spoken phrases** (SPCH-01); LLM writes wording and emotion; plain fallback only when the LLM is down.
- **Dogfooding:** from Phase 2 Snow drives Claude Code; Snow runs from a pinned copy (Phase 2). Not Phase 1 scope.
- **GSD workflow:** repo edits go through GSD commands; ask the user before creating a DECISIONS file.
- **Project memory:** "tell me first" requests must be answered in text before any tool (not applicable to this research run).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Mic capture, wake gate, VAD/turn, STT, TTS synth, playout, barge-in cut | Voice worker (audio plane, Python) | Hub (state/log) | Raw audio never leaves the process (privacy, latency); native ML crashes isolated from hub |
| Presence state, mute state, conversation state of record | Hub (projection reducer) | Voice worker (source of audio-derived events) | One authoritative snapshot for every HUD form; persisted mute survives restart |
| LLM chain, privacy routing, persona, ack pool, cooldowns | Brain worker (Python, network only) | Hub (events, health) | Network I/O isolated from audio; keys read from keyring inside this process only |
| Event bus, durable log, retention purge, schema contract | Hub | - | Single writer, seq assignment, snapshot-plus-delta |
| Supervision, restart, health aggregation | Hub supervisor | Task Scheduler (restarts hub) | Hub owns child lifetimes via Job Object; Task Scheduler is the outer watchdog |
| Autostart at logon | OS (Task Scheduler) | Hub launches Electron | Interactive session needed for audio; a Service is the wrong tier |
| Orb rendering, transcript, health UI, mute button | Electron renderer (Canvas 2D, React) | Electron main (window chrome only) | HUD is a WebSocket client; IPC only for window chrome/click-through/tray |
| Window forms, tray, single instance, drag, click-through | Electron main | - | Native window APIs |
| Secrets storage | OS (Credential Manager via keyring) | Brain/hub read at use time | Never serialized to config, env of children, logs |
| Idle audio containment | Voice worker | - | STT local, wake local; only text goes to LLM/Cartesia |

## Standard Stack

### Core (Python, uv-managed 3.12)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python (uv) | 3.12.x (3.12.13 present) | Runtime | Pipecat >=3.11, kokoro-onnx <3.14; `[VERIFIED: PyPI requires_python]` |
| pipecat-ai | 1.12.0 (2026-09-26) | STT/LLM/TTS frame pipeline, interruption, Cartesia service, observers | `[VERIFIED: PyPI + installed this session]`; extras used: `cartesia,whisper,kokoro,silero,openai` |
| faster-whisper / ctranslate2 | 1.2.1 / 4.8.2 (4.8.3 released 2026-10-13) | Local STT | `[VERIFIED: PyPI]`; ctranslate2 needs CUDA 12 + cuDNN 9 `[CITED: github.com/SYSTRAN/faster-whisper]` |
| nvidia-cublas-cu12 / nvidia-cudnn-cu12 | 12.9.2.10 / 9.27.0.42 | GPU libs via pip | `[VERIFIED: PyPI]`; Windows DLL registration needed (Code Example 1) |
| openwakeword | 0.6.0 (2024-02-11) | Streaming wake runtime (ONNX on Windows) | `[VERIFIED: installed + benchmarked]`; frames of 1280 samples |
| livekit-wakeword | 0.3.0 (2026-09-30) | **Training only** (off-machine): synthetic data, conv-attention head, ONNX export | `[CITED: github README]` Apache-2.0; `[ASSUMED]` ONNX conv-attention head loads in the openWakeWord runtime (README claims backward compatible) - spike |
| sounddevice | 0.5.6 | Mic + speaker transport (WASAPI) | `[VERIFIED: PyPI]`; `WasapiSettings(auto_convert=True)` for 16 kHz in shared mode `[CITED: python-sounddevice docs]` |
| kokoro-onnx | 0.6.1 | Local fallback TTS (D-16) | `[VERIFIED: PyPI, benchmarked]` - speed caveat F2 |
| openai | 3.29.0 pinned by `exclude-newer` (3.31.0 is 1 day old) | Chat client for all providers | `[VERIFIED: PyPI]`, retries/timeout/errors `[CITED: openai-python README]` |
| pydantic / pydantic-settings | 2.14.1 / 2.15.0 | Event contract, config | `[VERIFIED: PyPI]` |
| fastapi / uvicorn / websockets | 0.143.0 / 0.54.0 / 17.2 | Hub WS/HTTP server | `[VERIFIED: PyPI]` (pipecat already pulls websockets 17.2) |
| aiosqlite (or stdlib sqlite3 in a writer thread) | 0.22.1 | Event log | `[VERIFIED: PyPI]` |
| keyring | 25.7.0 | Windows Credential Manager | `[VERIFIED: PyPI]` |
| structlog | 26.1.0 | JSON logs + redaction | `[VERIFIED: PyPI]` |
| pywin32 | 312 | Job Objects (`win32job`), DPAPI later | `[VERIFIED: PyPI]` |
| psutil | 7.2.2 | Process liveness, connection audit in tests | `[VERIFIED: PyPI]` |

### Core (HUD, Node)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| electron | 44.7.2 | Shell | `[VERIFIED: npm]`; engines node >=22.12 (Node 25.6.0 present; use LTS in CI) |
| electron-vite | 6.0.0 | Build/dev (main/preload/renderer) | peer vite ^6 \|\| ^7 \|\| ^8 `[VERIFIED: npm]` |
| vite / @vitejs/plugin-react | 8.3.4 / 6.1.2 | Renderer build | plugin peer vite ^8 `[VERIFIED: npm]` |
| react / react-dom | 19.3.1 (UI-SPEC says 19.3.0) | UI | R3F not used in Phase 1, so no <19.4 cap |
| zustand | 5.0.15 | HUD store; WS reducer outside React | |
| tailwindcss + @tailwindcss/vite | 4.3.3 | Tokens as CSS variables (`--snow-*`) | |
| typescript | 7.0.2 (npm `latest`) | Types | fall back to newest 6.x if a tool blocks |
| vitest | 5.0.4 | Unit tests | peer vite ^6.4 \|\| ^7 \|\| ^8 |
| @playwright/test | 1.64.1 | HUD e2e + Electron perf marks | `_electron` API is experimental `[ASSUMED]` |
| @biomejs/biome | 2.5.15 | Lint/format | |
| json-schema-to-typescript | 16.0.0 | Event types from JSON Schema | `[ASSUMED]` handles Pydantic `oneOf`+`const` unions - verify in skeleton |
| ajv | 8.x | Contract tests (golden JSON vs schema) | |
| lucide-react, @fontsource-variable/inter, @fontsource/jetbrains-mono | 1.57.0, 5.3.0, 5.3.0 | UI-SPEC icons/fonts, bundled locally | `[VERIFIED: npm]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pipecat aggregator-driven turns | **External `TurnEngine` + Pipecat `ExternalUserTurnStartStrategy`/`ExternalUserTurnStopStrategy`** (recommended) | Wake pre-roll replay is a burst of audio faster than real time, which wall-clock-timer based built-in strategies may mishandle; bespoke wake/sleep/mute/conversation state belongs in plain testable Python. `[VERIFIED: strategies exist in pipecat/turns/ via GitHub]` |
| kokoro-onnx (D-16 locked) | kokoro fp32 model; `pocket-tts` 3.3.0 (MIT, 100M params, README claims ~2.3-2.5x real time on x86 CPU, needs PyTorch) | Spike only if F2 proves a problem; D-16 names kokoro, so deviation needs user OK |
| openWakeWord runtime for "Hey Snow" | livekit-wakeword's own `WakeWordModel` (stateless, 2 s windows) | Runtime recomputes features on 2 s windows each call; keep openWakeWord streaming runtime if the exported head loads |
| One `snow-core` process (CLAUDE.md sketch) | Hub + worker processes | CORE-02 is only provable with separable crash domains; cost: one WS protocol and ~2 extra Python processes |
| Task Scheduler + hub launching Electron | Electron `setLoginItemSettings` as backup | One start path is simpler; double-start prevented by single-instance lock if both are ever used |

**Installation (illustrative; pin through `uv.lock`):**
```bash
uv python install 3.12
uv init --python 3.12
uv add "pipecat-ai[cartesia,whisper,kokoro,silero,openai]==1.12.0" openwakeword==0.6.0 sounddevice keyring structlog \
  pydantic pydantic-settings fastapi "uvicorn" websockets aiosqlite pywin32 psutil nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
uv add --dev pytest pytest-asyncio ruff pyright respx pip-audit
# [tool.uv] exclude-newer = "<date >= 7 days ago>"   # delayed adoption policy
# HUD
npm create electron-vite@latest hud   # or hand-scaffold with electron-vite 6
```

**Version verification:** versions above were read from the PyPI JSON API and `npm view` on 2026-10-15. `exclude-newer` should resolve `openai` to 3.29.0 and `ctranslate2` to 4.8.2 (both match STACK.md) because 3.31.0 / 4.8.3 are 1-2 days old.

## Package Legitimacy Audit

Seam run: `gsd-tools query package-legitimacy check` (pypi and npm), 2026-10-15. Verdicts are driven by missing PyPI download statistics (`unknown-downloads`), very recent latest-release timestamps (`too-new`), or PyPI metadata lacking a repo URL. No package returned `SLOP`; none has a postinstall script. Package names below were all named in project STACK.md / UI-SPEC or official documentation, and each resolves to a well-known upstream repo; the SUS verdicts are statistical artifacts, so I do not recommend a human-verify checkpoint per package. The `exclude-newer` delayed-adoption policy removes the "too-new" class automatically.

| Package | Registry | Latest release | Source Repo | Verdict | Disposition |
|---------|----------|----------------|-------------|---------|-------------|
| pipecat-ai | PyPI | 2026-09-26 | github.com/pipecat-ai/pipecat | SUS (too-new, unknown-downloads) | Approved; pin 1.12.0 |
| faster-whisper | PyPI | 2025-10-31 | github.com/SYSTRAN/faster-whisper | SUS (unknown-downloads) | Approved |
| ctranslate2 | PyPI | 2026-10-13 | github.com/OpenNMT/CTranslate2 | SUS (too-new) | Approved; pin 4.8.2 via exclude-newer |
| openwakeword | PyPI | 2024-02-11 | github.com/dscripka/openWakeWord | SUS (unknown-downloads) | Approved (unmaintained since 2024; pinned, used as runtime only) |
| livekit-wakeword | PyPI | 2026-09-30 | github.com/livekit/livekit-wakeword | SUS (too-new, unknown-downloads) | Approved for off-machine training only; **checkpoint:human-verify before first install** (new, vendor-benchmarked, 286 stars) |
| sounddevice | PyPI | 2026-08-17 | none in PyPI metadata (upstream spatialaudio/python-sounddevice) | SUS (no-repository) | Approved `[ASSUMED]` upstream repo identity |
| kokoro-onnx | PyPI | 2026-08-19 | github.com/thewh1teagle/kokoro-onnx | SUS (unknown-downloads) | Approved |
| openai | PyPI | 2026-10-14 | github.com/openai/openai-python | SUS (too-new) | Approved; pin 3.29.0 via exclude-newer |
| keyring | PyPI | 2025-11-16 | github.com/jaraco/keyring | SUS (unknown-downloads) | Approved |
| structlog, aiosqlite, numpy | PyPI | recent | none in PyPI metadata (hynek/structlog, omnilib/aiosqlite, numpy/numpy) | SUS (no-repository) | Approved `[ASSUMED]` upstream identity |
| pydantic, fastapi, uvicorn, websockets, pywin32, psutil, pytest, pytest-asyncio, ruff, pyright, respx | PyPI | 2025-2026 | upstream repos present | SUS (unknown-downloads / too-new) | Approved |
| nvidia-cublas-cu12, nvidia-cudnn-cu12 | PyPI | 2026-04 / 2026-09 | developer.nvidia.com | SUS (unknown-downloads / too-new) | Approved (NVIDIA-published); ~1.3 GB, needs disk (F1) |
| typescript, zustand, tailwindcss, @tailwindcss/vite, json-schema-to-typescript, @fontsource/*, ajv | npm | - | upstream repos | OK | Approved |
| electron, electron-vite, vite, react, react-dom, vitest, @playwright/test, @biomejs/biome, lucide-react, @vitejs/plugin-react, ws | npm | recent | upstream repos | SUS (too-new only; 8M to 288M weekly downloads) | Approved; pin exactly in lockfile |

**Packages removed due to SLOP verdict:** none
**Packages flagged SUS needing a checkpoint:** `livekit-wakeword` only (judgement call; others are statistical SUS on well-known projects).
**Do not use:** `litellm` (project rule), `pyaudio` (last release 2023-11-07; sounddevice instead), `piper-tts` as a fallback voice (GPL; also needed only for wake-word training, which livekit-wakeword vendors).

## Measured Data (this machine, 2026-10-15)

Hardware: i5-12500H (12C/16T), RTX 4050 Laptop 6141 MiB (1292 MiB already used by the desktop), driver 596.49, on AC power, Python 3.12.13, onnxruntime 1.24.4 (CPU). `[VERIFIED: local benchmark scripts, since deleted from scratch space]`

| Item | Result |
|------|--------|
| Pipecat 1.12.0 + extras `cartesia,whisper,kokoro,silero,openai` on Python 3.12 / Windows | Installed cleanly, no torch (numba 0.68.0, numpy 2.5.4, scipy 1.18.1, onnxruntime 1.24.4, ctranslate2 4.8.3 resolved) |
| openWakeWord 0.6.0, `inference_framework="onnx"`, model `hey_jarvis_v0.1` | 2.05 ms median, 2.55 ms p95, 3.44 ms max per 80 ms frame (about 2.6 % of one core). `utils.download_models(model_names=["hey_jarvis"])` works |
| Silero VAD (Pipecat `SileroVADAnalyzer`) | 0.119 ms median, 0.137 ms p95 per 512-sample chunk |
| Smart Turn v3.2 (Pipecat `LocalSmartTurnAnalyzerV3`) | Loads bundled `smart-turn-v3.2-cpu.onnx` in 0.06 s; methods `append_audio`, `analyze_end_of_turn`, `clear`, `speech_triggered` |
| kokoro-onnx 0.6.1 int8, `bm_george`, 4.4 s audio | Load 1.08 s. First call per voice RTF 1.23-1.50. Warm RTF 1.0-1.03 (default threads), 0.86-0.88 (4 or 8 intra-op threads), 0.99-1.0 (12). `create_stream` first chunk 11.7 s for 8.4 s of audio |
| faster-whisper turbo on GPU | **Not measured**: disk full (F1); HF download of the model also returned an auth error (stale token behavior), irrelevant once disk is freed |

British male voices present in the kokoro voices file: `bm_daniel, bm_fable, bm_george, bm_lewis` (`am_*` also present) `[VERIFIED: voices-v1.0.bin listing]`.

## Architecture Patterns

### System Architecture Diagram

```
 LOGON ──> Task Scheduler task "Snow" (At log on, restart on failure, no time limit)
              │ launches
              ▼
 ┌────────────────────────── HUB  (python -m snow.hub) ───────────────────────────┐
 │  Supervisor ── spawns/monitors (Job Object KILL_ON_JOB_CLOSE, backoff, heartbeat)│
 │  Event bus ──> durable events ──append──> SQLite WAL (events, state, ack_pool)   │
 │      │            ephemeral (levels, partials, deltas) broadcast only            │
 │  Projections: presence, mute (persisted), conversation, health, voice, providers │
 │  WS server 127.0.0.1:PORT  (token + Origin check)  snapshot-then-delta           │
 └───────▲───────────────▲──────────────────────────▲──────────────────────────────┘
         │ WS (worker)    │ WS (worker)               │ WS (hud)
 ┌───────┴────────┐ ┌─────┴─────────────┐   ┌────────┴──────────────────────────┐
 │ VOICE worker   │ │ BRAIN worker      │   │ Electron HUD (React, Canvas 2D)   │
 │ mic─►wake gate │ │ persona+history   │   │ dashboard window | mini window    │
 │  ring buffer   │ │ ChainLLM (5 provs)│   │ tray, single instance             │
 │ ─►TurnEngine   │ │ privacy routing   │   └───────────────────────────────────┘
 │ (Silero+Smart  │ │ cooldown/counters │
 │  Turn+state)   │ │ ack pool refresh  │        External: Groq / Experiential /
 │ ─►STT (GPU,    │ │ keys from keyring │        Gemini / NIM / OpenRouter (text only)
 │  partials)     │ └─────────▲─────────┘        Cartesia WS (text in, audio out)
 │ ◄─ reply deltas─┘ (via hub) │
 │ ─►TTS router (Cartesia ⇄ kokoro) ─► playout ─► speakers (headphones)
 │ audio.level 30 Hz, barge-in cut local
 └─────────────────────────────────────────────────────────────────────────────────┘
 Raw audio never crosses a process boundary; only text, flags, levels do.
 Turn path: user speech ─► transcript.final ─► BRAIN ─► reply.delta* ─► VOICE TTS ─► audio
 Dev input (D-07): `snow dev inject-wav` swaps MicSource for FileSource (same interface).
```

### Recommended Project Structure
```
asssistant/                       # existing repo root (planning docs live in .planning/)
├── pyproject.toml  uv.lock  .python-version(3.12)
├── src/snow/
│   ├── contracts/     # Pydantic envelope + event/command models; schema export script
│   ├── hub/           # bus, eventlog (sqlite), projections, ws_server, supervisor, health, autostart
│   ├── config/        # settings.py, models.toml loader, secrets.py (keyring), snow setup CLI
│   ├── brain/         # providers.py, chain.py, cooldown.py, privacy.py, persona.py, acks.py, conversation.py
│   ├── voice/         # sources.py (Mic/File), wake.py, turn_engine.py, stt.py, tts/ (cartesia, kokoro, router), pipeline.py, playout.py
│   ├── logging.py     # structlog + loguru bridge + redaction
│   └── cli.py         # snow setup | run | install-autostart | dev inject-wav | dev kill <worker>
├── config/            # models.toml, snow.toml defaults (no secrets)
├── contracts/events.schema.json       # generated, committed, drift-gated in CI
├── training/wakeword/hey_snow.yaml    # livekit-wakeword config (run off-machine)
├── scripts/install-autostart.ps1
├── hud/               # electron-vite: src/main, src/preload, src/renderer, src/generated
├── tests/             # python: unit, integration, fixtures/audio (synthetic WAV), hardware/ (marked)
└── .github/workflows/ci.yml
```

### Pattern 1: External TurnEngine owns wake / listen / sleep / mute (plain Python)
**What:** `WakeGate` + `TurnEngine` are framework-free classes fed 16 kHz int16 frames. States: `MUTED` (stream closed), `SLEEPING` (wake model only; soft sleep and idle), `AWAKE` (VAD + Smart Turn running; conversation timer). Wake path: 80 ms frames (1280 samples) to openWakeWord; a RAM-only ring buffer of the last ~2 s runs in parallel. On detection, emit `wake.detected` immediately (HUD path), then replay ring audio from `detect_frame - 4 frames (~320 ms)` into the engine so a command spoken in the same breath is not lost (D-09); Raw audio never touches disk (D-18). Strip a leading "hey snow" (tolerant regex over ASR variants) from the final transcript. **Wake-alone:** if no VAD speech onset occurs between `t_detect + 0.2 s` and `t_detect + ~1.0 s`, treat as wake-alone and request an acknowledgement (Pattern 8). The engine tells Pipecat about turn boundaries via `UserStartedSpeakingFrame`/`ProposedUserStartedSpeakingFrame` and the external stop strategy.
**When to use:** always; this is the logic most needing WAV-fixture tests.
**Why not Pipecat's aggregator-owned VAD:** the replay burst and the conversation/sleep/mute states are bespoke; built-in strategies use wall-clock timers. `[ASSUMED]` that bursts break them; Wave 0 spike A decides, with the external design as the default.
**Tunables (config):** `wake.threshold` (start 0.5, tune by false accepts per hour), `wake.patience_frames`, `turn.vad_stop_secs` 0.2, `conversation.silence_timeout_s` default **45** (inside D-08's 30-60 s), `wake.command_window_s` 1.0.
**Deterministic commands (Claude's discretion):** match the *whole* final utterance (<= 6 words after wake strip) against normalized phrase sets for sleep ("go to sleep"), mute ("mute"), end ("that's all"/"that is all"/"thanks that's all"); never substring-match ("mute the speaker in the call" must not mute). No LLM, works with the gateway down.

### Pattern 2: Typed event contract and durable log (build first)
**Envelope** (Pydantic v2, discriminated on `type`): `{seq?, ts_ns, type, source, correlation_id (conversation/turn), causation_id?, user_id="owner", risk_tier="free", reason?, result?, payload}`. CORE-03 asks for source, reason, risk tier, result; Phase 2 enforces tiers but the fields exist now.
**Two classes:** durable = `wake.detected, conversation.started/ended, transcript.final, reply.final, reply.interrupted, mute.changed, presence.state (transitions), llm.call, llm.blocked_privacy, voice.switch, voice.status, health.changed (transitions), turn.timing, worker.started/crashed/restarted`; ephemeral (broadcast only, coalesced latest-wins) = `audio.level` (30 Hz, only in matching state), `transcript.partial`, `reply.delta`, `heartbeat`.
**SQLite (WAL, `synchronous=NORMAL`, single writer thread):**
```sql
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts_ns INTEGER NOT NULL, type TEXT NOT NULL,
  source TEXT NOT NULL, correlation_id TEXT, causation_id INTEGER,
  user_id TEXT NOT NULL DEFAULT 'owner', risk_tier TEXT NOT NULL DEFAULT 'free',
  reason TEXT, result TEXT, payload TEXT NOT NULL,        -- JSON, no free text of speech
  content TEXT);                                          -- transcript/reply text only (retention target)
CREATE INDEX events_ts ON events(ts_ns); CREATE INDEX events_type ON events(type, seq);
CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT NOT NULL);       -- mute, voice choice, etc.
CREATE TABLE ack_pool (id INTEGER PRIMARY KEY, text TEXT NOT NULL, emotion TEXT NOT NULL, generated_at INTEGER NOT NULL);
```
**Retention (D-19):** speech text lives in `content`; a purge at startup and daily runs `UPDATE events SET content=NULL WHERE content IS NOT NULL AND ts_ns < :cutoff` (default 30 days, config). Event metadata stays, which keeps the audit trail Phase 2 needs. Numbered-SQL migrator (`PRAGMA user_version`); no Alembic yet.
**Contract pipeline:** `TypeAdapter(Event).json_schema()` -> `contracts/events.schema.json` -> `json-schema-to-typescript` -> `hud/src/generated/events.d.ts`; CI regenerates both and fails on `git diff`. Golden JSON samples (one per event type, produced from model examples) are validated by pytest (pydantic) and Vitest (ajv).
**Snapshot-plus-delta:** on connect the hub sends `snapshot` (presence, mode, mute, health, voice, providers per role, current conversation transcript) then deltas; HUD reducer is a pure function. HUD derives nothing the hub already computed.

### Pattern 3: ChainLLM with privacy routing (brain worker)
**Seam:** subclass `OpenAILLMService` and override `get_chat_completions(context)` `[VERIFIED: base_llm.py:325-361]`; `build_chat_completion_params` `[VERIFIED: :363-397]` is where per-model quirks are applied (drop `temperature`, drop `stream_options`, set `reasoning_effort`). Keep the chain logic in a Pipecat-free `LLMChain` class; the Pipecat subclass is 30 lines of adapter. Build one `AsyncOpenAI(base_url, api_key, max_retries=0, timeout=...)` per provider (SDK default is 2 automatic retries, which would delay failover `[CITED: openai-python README]`). Use `client.chat.completions.with_raw_response.create(stream=True)` then `.parse()` to read rate-limit headers `[CITED README for with_raw_response; ASSUMED for streaming interplay - verify]`.
**Per-call data class (SAFE-12):** every call carries `data_class: Literal["general","private"]`, default **`private`** (fail closed). Providers carry `trust: "trusted"|"untrusted"` in config (Google AI Studio free and OpenRouter free = untrusted per D-26). Chain construction filters: no key -> skip + `not_configured`; cooling down -> skip; `private` + untrusted -> skip; if nothing remains raise `PrivacyBlockedError` (distinct from "all failed"), emit `llm.blocked_privacy`, HUD shows the documented UI-SPEC row. The tag is set by the calling code path, never by the model or by transcript text. `general` is used only for prompts containing no user content (ack-pool generation, switch/voice-switch notices).
**Error classification -> action:**

| Signal | Action |
|--------|--------|
| 429 (any) | cooldown provider; next entry |
| 429 `insufficient_quota` (Experiential: `key_daily_cap`, `insufficient_credits`, `free_limit_reached`) | long cooldown (config default 30 min, until next day for `key_daily_cap`); next |
| 429 `unavailable_route` / `gateway_overloaded` | short cooldown (5-30 s); next |
| 5xx incl. 502 `all_routes_failed`, 503 `deadline_exceeded` (Retry-After 2 s) | short cooldown; next |
| `APITimeoutError`, `APIConnectionError` | short cooldown; next |
| 400 `unsupported_parameter` | do not retry same entry; record quirk and surface as config error; next |
| 400 `refusal` | do not fall over (retry does not help) `[CITED: Experiential llms.txt]`; return refusal to persona layer |
| 401/403 | mark entry "Failing" (bad key); next |
**Time-to-first-token deadline:** per-entry `ttft_timeout_s` (fast role ~2.5 s, brain ~6 s) so a hung provider does not eat the 1 s budget; the timeout counts as a failure.
**Cooldown from headers:** Groq `retry-after` seconds on 429, `x-ratelimit-reset-requests` like `2m59.56s`, `x-ratelimit-reset-tokens` like `7.66s` `[CITED: console.groq.com/docs/rate-limits]` (write a tiny `parse_duration` for `1h2m3.5s`/`250ms` forms); OpenRouter 429 carries `X-RateLimit-Limit/Remaining/Reset` and `Retry-After` when available `[CITED: openrouter.ai/docs]`; Google documents no headers (limits per project, RPD resets midnight Pacific) so use body `retryDelay` if present else exponential default `[CITED: ai.google.dev rate-limits]`; Experiential documents no rate-limit headers; NIM unknown (about 40 RPM trial reported by forum/blog, LOW). Counters: requests and tokens per provider per day from the final `usage` chunk (`stream_options.include_usage`; fall back to `len(text)/4` estimate when absent). Counters and cooldowns are in memory plus a daily snapshot in `state` (resettable).

**Rate-limit facts that shape the design:**

| Provider | Limits relevant to Snow | Source |
|----------|------------------------|--------|
| Groq `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` | 30 RPM, 1K RPD, **8K TPM**, 200K TPD ("base Developer-plan limits"; verify in account) | `[CITED: console.groq.com/docs/rate-limits]` |
| OpenRouter `:free` | 20 RPM; **50 requests/day** unless >= 10 credits purchased (key limit is 0) | `[CITED: openrouter.ai/docs/api-reference/limits]` |
| Google AI Studio | per project, no published numbers on the page; 429 `RESOURCE_EXHAUSTED`; no header docs | `[CITED: ai.google.dev/gemini-api/docs/rate-limits]` |
| NVIDIA NIM | about 40 RPM reported | `[CITED: forums.developer.nvidia.com, medium]` LOW |
| Experiential Labs | 429 codes above; no rate-limit headers documented; response header `x-experiential-ignored-parameters` shows dropped params | `[CITED: platform.experientiallabs.ai/llms.txt (first 100K of 163K chars read)]` |

Consequence: with Groq at 8K TPM and 200K TPD, a conversational turn must stay about 1.5-2.5K tokens (system prompt <= 500, history capped at ~1,200 tokens, last 4-6 turns, reply capped). That is roughly 80-130 turns/day on Groq before falling to Experiential. Cap in code and show counters on the HUD.

**Model facts verified from the Experiential public catalog (`GET https://api.experientiallabs.ai/api/models`, keyless, fetched 2026-10-15):**
- `gpt-5.6-luna`: `input_modalities ['text','pdf','image']`, `supported_params {'tools': True, 'top_p': False, 'reasoning': True, 'temperature': False, 'response_format': True, 'structured_outputs': True}` -> omit `temperature` and `top_p` `[VERIFIED]`. (A newer `gpt-6-luna` also exists in the catalog; user locked 5.6.)
- `deepseek-v4-flash`: text only, `tools: True, temperature: True, reasoning: True` `[VERIFIED]`.
- `qwen3.8-27b`: `input_modalities ['text','image','video']`, tools true `[VERIFIED]`.
- Reasoning is on for luna, deepseek-v4-flash and gpt-oss: reasoning tokens inflate time-to-first-token and daily token use. Put `reasoning_effort` per model in config (low/minimal; Gemini 3 cannot disable reasoning, use `minimal` `[CITED: ai.google.dev/gemini-api/docs/openai]`; Experiential "none" can 400 if the route cannot turn reasoning off `[CITED: llms.txt]`). Measure in the D-30 latency test.
- Other IDs from docs: Groq `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` `[CITED: groq rate-limits page]`; Gemini docs example `gemini-3.8-flash` `[CITED]`. NIM (DeepSeek V4 Pro, Kimi K3) and OpenRouter Nemotron IDs are **unknown until `GET /models`** (D-29); do not guess.

### Pattern 4: Streaming STT = rolling re-decode on a single GPU worker
Pipecat's `WhisperSTTService` is a `SegmentedSTTService`: it transcribes only after VAD stop and pushes one finalized `TranscriptionFrame` `[VERIFIED: stt_service.py:798-938, whisper/stt.py:224]`. Live partials (VOIC-08) need a custom STT processor:
- Accumulate the current turn's audio; every ~400 ms, if the decoder is idle, decode the last <= 8 s with `beam_size=1`, `language="en"`, `condition_on_previous_text=False`, `without_timestamps=True`, `vad_filter=False`; push `InterimTranscriptionFrame` (-> `transcript.partial`). If busy, skip (never queue partials).
- On turn stop run the final decode (beam 1-2 for speed; tune against WER on fixtures) with 0.5 s trailing silence padding (Pipecat default `trailing_silence_secs=0.5` rationale: models drop the last word otherwise).
- One decoder thread, one `WhisperModel("large-v3-turbo"/"turbo", device="cuda", compute_type="int8_float16")`; load once at worker start (warm-up decode on 1 s of silence).
- Anti-hallucination: drop segments with `no_speech_prob > 0.6 and avg_logprob < -1.0`, and a short denylist of silence hallucinations; wake-strip happens after STT.
- VRAM/latency: published large-v2 numbers are fp16 4.5 GB vs int8 2.9 GB on an 8 GB card `[CITED: faster-whisper README]`; turbo int8_float16 is estimated 1.2-2 GB and 150-300 ms for a 3 s utterance `[ASSUMED, unmeasured]` - spike gate S2 must measure on this RTX 4050 with the HUD running.
- English only (VOIC-04): consider `distil-large-v3` (English-only) as a speed option if turbo misses budget `[ASSUMED]`.

### Pattern 5: Hub supervisor, Task Scheduler, Job Object (CORE-01, CORE-02)
- **Outer watchdog:** `Register-ScheduledTask` for the current user, trigger *At log on*, settings: `-RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew`. Microsoft documents that without `ExecutionTimeLimit` Task Scheduler uses a **three-day default** `[CITED: learn.microsoft.com New-ScheduledTaskSettingsSet]`; battery defaults stop laptop jobs (Pitfall 9). Action: `.venv\Scripts\pythonw.exe -m snow.hub` (no console window). `snow install-autostart` / `uninstall` is idempotent.
- **Hub as supervisor:** spawns `voice`, `brain` workers (`subprocess.Popen` with `CREATE_NO_WINDOW`) and Electron (with `--autostart`), all inside a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (pywin32 `win32job`) so a dead hub never leaves an orphan holding the mic or GPU. Children get only `SNOW_HUB_URL` and a per-launch `SNOW_TOKEN` in a scrubbed env; the brain reads provider keys from keyring itself.
- **Restart policy:** exponential backoff 0.5 s -> 30 s with jitter, reset after 60 s stable; crash-loop breaker after 5 crashes in 2 min -> status Down ("Could not restart. See logs.") and retry every 60 s. Workers send heartbeats every 2 s; 3 missed -> kill and restart (hang detection, e.g. wedged CUDA call). Emit `worker.crashed/restarted` and `health.changed`.
- **Quit semantics:** tray "Quit Snow" -> HUD sends `app.quit` -> hub stops workers and exits **code 0**. `[ASSUMED]` Task Scheduler restarts only on failed runs; verify so Quit actually stays quit until next logon.
- **Test hooks:** `snow dev kill voice|brain|hud` for CORE-02 verification, plus a pytest using a fake worker script that exits non-zero or stops heartbeating.

### Pattern 6: Mute, sleep, conversation modes
- **Hard mute** = the voice worker closes the `sounddevice` input stream (not just ignoring samples), so the Windows mic indicator goes off; the hub persists `mute=true` in `state` and the worker starts muted after any restart or reboot (fail safe: never silently unmute). Confirmed-state: the HUD flips only on `mute.changed` from the hub (UI-SPEC).
- **Soft sleep:** stream open, only the wake model runs; `presence.mode=soft_sleep`.
- **Conversation end:** silence timer (reset by user speech start and by bot speech end), phrase "that's all", or `sleep`. Emit `conversation.ended`; HUD fades transcript after 2 s (UI-SPEC).

### Pattern 7: Barge-in (headphones, no AEC)
- Pipecat interruptions are enabled by default; a user turn start cancels bot speech and in-flight work `[CITED: docs.pipecat.ai speech-input]`. Because the TurnEngine owns turn starts, barge-in = TurnEngine detects VAD speech >= `barge_in_min_ms` (start ~250 ms) while state is SPEAKING -> emits turn-start with interruption -> pipeline cancels LLM request (brain gets `turn.cancelled` via hub), TTS context, and the playout buffer is aborted (`stream.abort()` on the output stream; keep blocksize ~20 ms so the tail is short).
- Persist `reply.interrupted` with the text actually spoken so far (word timestamps from Cartesia WS `add_timestamps` when available; sentence granularity otherwise) so conversation history reflects what the user heard.
- Without AEC, speaker playback self-triggers. Phase 1 assumes headphones; add a config flag `audio.assume_headphones=true` and a first-run warning. `[ASSUMED]` acceptable per project decision "headphones for v1".

### Pattern 8: Persona, emotion, acknowledgements (SPCH-01/02, D-09)
- **Emotion header:** the persona prompt requires the reply to start with `[[emotion]]` (one of a small enum), e.g. `[[content]] Of course, sir.` A streaming parser buffers <= 32 chars until `]]`, validates against the allowed set, falls back to `neutral`, and strips the header before TTS. Cartesia values available `[VERIFIED: pipecat/services/cartesia/tts.py:163-172]`: `NEUTRAL = "neutral"`, `ANGRY = "angry"`, `EXCITED = "excited"`, `CONTENT = "content"`, `SAD = "sad"`, `SCARED = "scared"` (primary), plus `CALM = "calm"`, `SYMPATHETIC = "sympathetic"`, `CURIOUS = "curious"`, `JOKING_COMEDIC = "joking/comedic"` and others. Apply per reply by prepending `EMOTION_TAG(emotion)` = `<emotion value="..." />` to the first sentence `[VERIFIED: tts.py:466-468]` (kokoro ignores/strips it) or via `GenerationConfig(emotion=...)` `[VERIFIED: tts.py:59-76]`. Cartesia says emotion works best with voices Leo, Jace, Kyle, Gavin, Maya, Tessa, Dana, Marian `[VERIFIED: tts.py:68-71]` - a British-leaning "Jarvis" voice may be less emotion-responsive, so the voice audition (D-05) must test each candidate with at least `content`, `sympathetic`, `neutral`.
- **Allowed set (config):** `neutral, content, calm, curious, sympathetic, excited` (D-06 example list, all valid Cartesia strings). Error context forces `neutral`/`sympathetic` by a deterministic rule, not by the model (D-03).
- **Wake-alone acknowledgement without latency:** the brain keeps a pool of 6-10 LLM-written one-liners (persona prompt, `data_class=general`, fast chain) stored in `ack_pool`, refreshed in the background at startup and whenever the pool drops below 3, never at wake time. At wake-alone it pops one and sends it to TTS (so Cartesia credits are spent only on use). If the pool is empty and every provider is down, speak a minimal plain fallback tagged `source=fallback` in the event (SPCH-01 permits this only when the LLM is down); this conflicts with D-09's "no chime", so use a spoken word, not an earcon (Open Question 5).
- **Switch notices (D-17, D-28):** the brain generates the one-time remark for the next reply via the normal persona prompt with a "context facts" line (`voice_switched=true`, `provider_switched=true`), so it stays LLM-written; the HUD system row stays plain UI copy.
- **Voice candidates for D-05 (names only, IDs unresolved):** third-party catalog lists male British Cartesia voices Benedict ("Royal Narrator"), Casper ("Gentle Narrator"), Caspian ("Oracle"), Archie ("Approachable Mate") `[CITED: famulor.io Cartesia British catalog; LOW, unofficial]`; Cartesia's own guide lists stable male voices Daniel, Archie, Parker, Jameson, Corey and emotive male Brandon, Cory, Alec `[CITED: docs.cartesia.ai choosing-a-voice]`. IDs must come from `GET /voices` with the user's key; build `snow dev audition-voices` that lists English male voices and speaks one fixed line per candidate with `content` and `neutral`.
- **Speech hygiene:** strip markdown/URLs/code fences from LLM text before TTS (persona prompt asks for plain speech; sanitizer is the backstop).

### Pattern 9: TTS router: Cartesia primary, kokoro fallback (SPCH-03, D-16/17)
- Pipecat `CartesiaTTSService` (WebSocket, default model `sonic-3.6`, `text_aggregation_mode` default SENTENCE, word timestamps, 5-minute idle timeout with auto reconnect) `[CITED: docs.pipecat.ai Cartesia page]`. Configure through `Settings(voice=..., generation_config=...)`, not the deprecated constructor args.
- **Failure/out-of-credit detection:** Pipecat forwards a Cartesia WS `error` message as a generic `push_error` without status discrimination `[VERIFIED: tts.py:752-755]`; the Cartesia error schema carries `status_code`, `title`, `message`, optional `error_code`, `context_id` `[CITED: docs.cartesia.ai tts websocket]`; no documented code for insufficient credits; credits cost about 1 credit per character and failed requests consume none `[CITED: docs.cartesia.ai/pricing.md]`. Implement `CartesiaHealth` (pure Python): states `ok | out_of_credits | unreachable`; classify by `status_code` in {401, 402, 403, 429}, messages containing "credit"/"quota", and consecutive connection errors; log the raw error payload on first occurrence so the real out-of-credit shape is captured (spike S4 with the real key).
- **Switching:** use Pipecat `ServiceSwitcher` with a custom `ServiceSwitcherStrategyFailover` subclass overriding `handle_error` (documented extension point); failed services stay in the list and need `set_usable(True)` to come back `[CITED: docs.pipecat.ai service-switcher]`; failback = background probe every 60-120 s while on the fallback (a cheap authenticated read such as `GET /voices?limit=1`, spending no credits), then `set_usable(True)` and switch. Mid-reply failure: remaining sentences continue on kokoro. If the ServiceSwitcher fit is poor in spike S1, hand-roll a 100-line `FailoverTTS` processor.
- **Credits for the HUD:** Cartesia's published OpenAPI catalog lists `GET /usage/credits` (third-party catalog; Cartesia's own doc page requires login), response shape unconfirmed `[CITED: apievangelist catalog; LOW]`. Until spike S4 confirms the response, `voice.status.credits_remaining = null` and the HUD shows "Unavailable" exactly as UI-SPEC prescribes (the UI-SPEC unresolved row).
- **Local voice speed (F2):** kokoro-onnx int8 warm RTF 0.86-1.03 on this CPU. Mitigations to implement: split the first clause at the first comma/short sentence (<= ~6 words) to make time-to-first-audio about 0.5-0.7 s; buffer 300-500 ms before starting playback of a local reply; run synthesis in a separate thread with `intra_op_num_threads=4`; spike kokoro fp32 and `pocket-tts` if gaps persist. Output sample rate 24 kHz for both voices.
- **Transcript hygiene:** pass the same sanitized text to both engines; both emit `tts.started/stopped` and `audio.level` from the PCM actually written.

### Pattern 10: Latency instrumentation and budget (SPCH-04)
Per-turn `turn.timing` durable event: `vad_stop, stt_final, llm_first_token, tts_first_audio, audio_out_first_sample` (monotonic ns). Pipecat ships `UserBotLatencyObserver` and `TurnTrackingObserver` `[VERIFIED: pipecat/observers/ listing]`; use them plus own marks.

| Stage | Estimate | Status |
|-------|----------|--------|
| VAD stop confirm (`stop_secs`) | 200 ms | config |
| Smart Turn decision | 10-30 ms | `[ASSUMED]` CPU ONNX |
| STT final (turbo, GPU, ~3 s speech) | 150-300 ms | `[ASSUMED]` spike S2 |
| Hub hops (voice->hub->brain->hub->voice) | 4-10 ms | `[ASSUMED]` loopback JSON |
| LLM TTFT (Groq gpt-oss-120b, low reasoning) | 250-500 ms | `[ASSUMED]` spike D-30 |
| First sentence/clause accumulation | 80-200 ms | `[ASSUMED]` |
| Cartesia first audio (warm WS) | 150-250 ms | `[ASSUMED]` |
| Output device buffer | 20-60 ms | `[ASSUMED]` |
| **Sum** | **~0.9-1.6 s** | misses 1 s at the high end |

Levers if the sum is too high: (1) speculative generation on VAD stop, cancelled if the user resumes (Pipecat 1.12 contains `eager_end_of_turn_mixin`, `speculation_gate`, `EagerTranscriptionFrame` `[VERIFIED: turns/ listing]`; behavior unread - evaluate), (2) clause-level TTS flush, (3) `reasoning_effort` minimal, (4) keep the Cartesia WS and provider HTTP connections warm, (5) shorter first reply via persona prompt. Define "about 1 second" as VAD-stop to first audio sample, p50 <= 1.0 s, p95 <= 1.6 s, measured in the hardware suite.

### Pattern 11: HUD and Electron (HUD-03, D-11..D-15)
- **Event path:** wake thread -> `loop.call_soon_threadsafe` -> voice WS send -> hub fan-out -> renderer `onmessage` -> write to refs -> next `requestAnimationFrame` paint. Target: `wake.detected` timestamp to first painted frame <= 100 ms (HUD-03) and renderer event-to-paint <= 50 ms (UI-SPEC). The wake model's own lag (the phrase must finish) is outside the 100 ms and is measured separately.
- **Orb renderer:** Canvas 2D with a pre-rendered glyph atlas (OffscreenCanvas per hue/size), `drawImage` per glyph, no `fillText` in the frame loop, glyph count by size (dense at 192 px, sparse at 40 px), rotate positions in typed arrays, levels read from refs, never React state. 60/30/15/0 fps per UI-SPEC; cancel rAF when hidden. `[ASSUMED]` a few hundred sprite blits per frame cost well under 2 ms; assert with a perf test (below).
- **Mini window:** `setIgnoreMouseEvents(true, { forward: true })` is documented for Windows and macOS; forwarded mouse-moves enable `mouseleave` `[CITED: electronjs.org BrowserWindow]`; toggle off on orb `pointerenter`. `setAlwaysOnTop(true, 'floating')` sits below the taskbar on Windows `[CITED]`. Transparent frameless windows on Windows are the known-quirk area; Wave 0 spike S5 validates: click-through, hover toggle, drag threshold 4 px, no residual border, mixed-DPI clamp.
- **Single instance:** `app.requestSingleInstanceLock()` + `second-instance` focuses the dashboard `[ASSUMED standard Electron API]`. **Hide on close** per UI-SPEC; quit only via tray/mini menu.
- **Security of the renderer:** `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, CSP `default-src 'self'; connect-src ws://127.0.0.1:*`; preload exposes only window-chrome IPC and the token handoff. `@electron/fuses` hardening is Phase 7.
- **GPU contention:** the 2D canvas is light; also set Windows Graphics Settings so `electron.exe` uses the Intel iGPU (manual step) `[ASSUMED]` per ARCHITECTURE D3.
- **Playwright Electron test:** launch the packaged renderer against a mock hub that sends a scripted event stream; `performance.mark` on message receipt and in the rAF callback; assert delta <= 50 ms across 200 events.

### Pattern 12: Logging and health (QUAL-03)
- structlog JSON to rotating file under `%LOCALAPPDATA%\Snow\logs`, processors: add timestamp/level/worker, **redact**, render JSON. Redaction: (1) key-name filter (`api_key|authorization|token|secret|password|cookie`), (2) value regexes for `xpl_`, `gsk_`, `nvapi-`, `sk-or-`, `AIza[0-9A-Za-z_-]{35}`, `sk_car_`, bearer tokens, (3) exact-match against the secret set loaded from keyring (so unfamiliar formats are still caught).
- **Pipecat logs through loguru and logs the full LLM context at DEBUG** (`Generating chat from context {...}` in `get_chat_completions` `[VERIFIED: base_llm.py:336-338]`), which would write transcripts into logs. `logger.remove()` at startup, add one loguru sink that forwards WARNING+ into structlog (so redaction applies); transcripts exist only in the event log (retention-managed).
- Third-party loggers (`openai`, `httpx`, `websockets`) at WARNING.
- Health model: per subsystem `{name, status: running|starting|restarting|down, since, detail}`; per provider `{status: active|fallback|cooling_down(until)|failing|not_configured|not_used_yet}`; per role `{active_provider, active_model, chain: [...], fallback_index}` matching UI-SPEC rows.

### Pattern 13: Secrets (SAFE-09, D-24/D-25)
- `snow setup`: for each provider (and Cartesia) prompt with `getpass`, `keyring.set_password("snow", "<provider>", value)`; Enter skips (provider stays "not configured", D-25); `snow setup --status` prints configured/not-configured only. WinVaultKeyring blobs are limited (~2.5 KB per STACK.md, plenty for API keys) `[ASSUMED]`.
- Never put keys in `os.environ` of children or in config; the key getter returns a `SecretStr`-like wrapper whose `__repr__` is redacted; the OpenAI client receives the string at construction only.
- Canary test (SAFE-09): store a fake key matching a real pattern in an in-memory keyring backend, run a scripted turn through brain with `respx`, then assert the canary appears in no log line, no event row, no WS frame, and no config file (gitleaks also runs in CI).

### Pattern 14: CI (QUAL-01)
- GitHub Actions on `windows-latest` (no GPU, no audio device): jobs `python` (`astral-sh/setup-uv`, `uv sync --frozen`, `ruff check`, `ruff format --check`, `pyright`, `pytest -m "not hardware"`), `hud` (setup-node LTS, `npm ci`, `biome ci`, `tsc --noEmit`, `vitest run`, Playwright Electron smoke), `contracts` (regenerate schema + TS, `git diff --exit-code`), `security` (`pip-audit`, `npm audit --omit=dev`, gitleaks). Pin third-party actions by commit SHA. Fake voice transport and WAV fixtures stand in for hardware. Smart Turn/Silero/openWakeWord CPU models are real in CI.
- "A failing change cannot be merged": needs a GitHub remote and enforced required checks: branch protection/rulesets on a private repo need a paid plan; public repos can use them on Free `[CITED: docs.github.com protected branches; private repos need Team/Enterprise for branch restrictions]`. The repo has no remote today (F4). Fallback if the user wants a private free repo: local `pre-push` hook running the same commands; this does not satisfy "cannot be merged" literally, so ask.

### Anti-Patterns to Avoid
- **Bare `python`/`pip`:** default PATH python is 3.10.9. Always `uv run`.
- **`AsyncOpenAI` with default retries** in a chain (delays failover).
- **Putting provider keys in env vars passed to workers**, or reading keys in the hub.
- **Sending any text from conversation turns to untrusted providers** by defaulting `data_class` to `general`.
- **Logging Pipecat DEBUG** (transcripts and prompts in logs).
- **Rendering the orb with `fillText` per frame or in React state** (misses 50 ms/60 fps).
- **Treating Windows Service as "always-on"** (Session 0, no mic).
- **Muting by discarding samples** while the stream stays open (mic indicator stays on; VOIC-03 "mic fully off").
- **Silencing the wake model during TTS** (kills barge-in; headphone assumption makes it safe to keep listening).
- **Training the wake model on this laptop** (disk, Linux-only tooling).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Voice activity detection | Energy thresholds | Silero via `SileroVADAnalyzer` (0.12 ms/chunk measured) | Noise/TV robustness |
| End-of-turn detection | Silence timeout only | Smart Turn v3.2 bundled ONNX (`LocalSmartTurnAnalyzerV3`) | Prevents cutting off mid-thought (VOIC-05) |
| Wake word model/features | Custom CNN | openWakeWord runtime + livekit-wakeword training | Hard negatives, adversarial phrase generation, threshold optimization already built |
| Cartesia WS protocol, contexts, word timestamps | Raw WebSocket client | Pipecat `CartesiaTTSService` | Context handling, reconnect, timestamps |
| Sentence segmentation for TTS | Regex splitter | Pipecat text aggregation (`sentencex`) | Abbreviations/decimals |
| Windows credential storage | DPAPI/file encryption | `keyring` (WinVaultKeyring) | OS-managed, no custom crypto |
| Child process lifetime | PID files / taskkill loops | Windows Job Object (`win32job`) | Guaranteed kill-on-close |
| Autostart + restart on failure | Custom launcher service | Task Scheduler `Register-ScheduledTask` | Built-in restart, logon trigger |
| Schema <-> TS types | Hand-synced interfaces | Pydantic `TypeAdapter.json_schema()` + `json-schema-to-typescript` + drift gate | Single source of truth (Pitfall in ARCHITECTURE Anti-Pattern 9) |
| SQLite migrations | Alembic now | Numbered SQL + `PRAGMA user_version` | One user, tiny schema |
| Window dragging | `-webkit-app-region: drag` | Pointer events + IPC (UI-SPEC) | `drag` swallows clicks |
| Duration header parsing | Ad-hoc string splits | One tested `parse_duration` for `1h2m3.5s`/`250ms` | Groq returns `2m59.56s` style |
| LLM client | Raw `httpx` calls | `openai` SDK with `base_url`, `max_retries=0` | Streaming/errors typed; never litellm |

**Key insight:** every component that touches audio, security or retry semantics already has a battle-tested home; Snow's own code is the glue with state machines (TurnEngine, chain, supervisor), which are exactly the parts to cover with fixtures and fakes.

## Common Pitfalls

### Pitfall 1: The wake phrase lands in the transcript or eats the first command word
**What goes wrong:** "Hey Snow open the project" is transcribed as "snow open the project" or "open the project" with "open" clipped.
**Why:** detector fires 1-3 frames (80-240 ms) after the phrase ends; starting the turn at detection loses the first word, starting at the phrase start includes "Hey Snow".
**How to avoid:** replay ~320 ms before detection, strip the wake phrase with a tolerant regex, test on fixtures with 0 ms, 150 ms and 600 ms gaps between "Snow" and the command; tune `command_window_s` for wake-alone.
**Warning signs:** transcripts beginning with "snow"/"so", first words missing.

### Pitfall 2: "Snow" false accepts ("hey, so...", "no", TV)
**What goes wrong:** short two-syllable phrase; a synthetic-only model false-fires on real speech.
**How to avoid:** train with adversarial negatives plus real negative hours (user's own TV/music/typing recorded locally by explicit action, kept local); threshold chosen from measured false accepts per hour (target < 1/h; livekit's own model reports 0.08 FPPH on its validation set, vendor number); use `vad_threshold` gate in openWakeWord; optional second-stage text check from STT ("snow" in first words) before opening the conversation. Keep `hey_jarvis` as the A/B baseline.

### Pitfall 3: Local voice cannot keep up (F2)
**What goes wrong:** kokoro RTF about 1.0: gaps mid-sentence or a 3-4 s wait before the first local audio.
**How to avoid:** first-clause chunking, playback pre-buffer, thread tuning, spike fp32/pocket-tts, set expectations in the plan (SPCH-04 for the local voice is best-effort). Measure end-to-end, not just `create()`.

### Pitfall 4: OpenAI SDK retries and mid-stream errors
**What goes wrong:** default `max_retries=2` retries 429 with backoff before failover; a stream can die after the first chunk.
**How to avoid:** `max_retries=0`; fail over only before the first content chunk; after the first chunk, surface `reply.interrupted`-style error and let the next turn use the next entry; per-entry TTFT deadline.

### Pitfall 5: Reasoning tokens blow latency and daily quotas
**What goes wrong:** luna/deepseek-flash/gpt-oss reasoning adds seconds and burns Groq's 200K TPD.
**How to avoid:** `reasoning_effort` per model in config (see Pattern 3), measure in D-30, check `x-experiential-ignored-parameters`.

### Pitfall 6: CUDA/cuDNN DLLs not found under Task Scheduler
**What goes wrong:** works from the terminal, fails at logon with `Could not locate cudnn_ops64_9.dll`; Task Scheduler does not inherit shell PATH changes `[CITED: runaihome.com article]`.
**How to avoid:** at worker start, before importing `ctranslate2`/`faster_whisper`, call `os.add_dll_directory` for `nvidia/cublas/bin` and `nvidia/cudnn/bin` and also prepend them to `os.environ["PATH"]` (cuDNN lazy-loads sub-libraries; `[ASSUMED]` PATH prepend needed in addition, verify in S2). Official docs only describe the Linux pip route and a Windows archive `[CITED: faster-whisper README]`; pip wheels on Windows put DLLs under `site-packages\nvidia\*\bin` `[CITED]`.

### Pitfall 7: Pipecat/loguru leaks transcripts and the banner prints on import
**How to avoid:** Pattern 12 loguru sink; set `LOGURU_LEVEL`; do not log contexts. Also `import pipecat` prints a banner to stdout (harmless but noisy).

### Pitfall 8: Autostart path assumptions
**What goes wrong:** Task Scheduler launches with a different working dir/PATH; `pythonw.exe` has no stdout (prints crash silently); GPU DLL path missing.
**How to avoid:** absolute paths to the venv interpreter, explicit `-WorkingDirectory`, file logging from first line of the hub, `pythonw` only after smoke-testing with `python.exe`.

### Pitfall 9: Task Scheduler defaults hurt a laptop daemon
**What goes wrong:** default `ExecutionTimeLimit` of 3 days kills the hub; "stop on battery" kills it unplugged.
**How to avoid:** `-ExecutionTimeLimit (New-TimeSpan -Seconds 0)`, `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`, `-MultipleInstances IgnoreNew` `[CITED: learn.microsoft.com]`.

### Pitfall 10: Mic stream breaks on device change / sleep-resume / Bluetooth
**What goes wrong:** headset unplugged or system resume leaves a dead stream; sample rate changes.
**How to avoid:** the voice worker's source layer catches `PortAudioError`, reopens with backoff, reports `health` degraded, and never crashes the worker; open at 16 kHz with `WasapiSettings(auto_convert=True)` in shared mode (only valid in shared mode `[CITED: sounddevice docs]`) or open at the device rate and resample with `soxr` (already a Pipecat dependency).

### Pitfall 11: Loopback WebSocket is reachable by any local process and by browsers
**What goes wrong:** a web page can open `ws://127.0.0.1:PORT` (WebSockets are not subject to CORS).
**How to avoid:** per-launch 256-bit token (query/subprotocol), reject unexpected `Origin` and `Host`, bind 127.0.0.1 only, random port written to a user-ACL'd file, token passed to children via env and to the HUD via preload; validate every inbound message with Pydantic (extra=forbid).

### Pitfall 12: GitHub Free private repo cannot enforce checks (F4)
See Pattern 14 / Open Question 2.

### Pitfall 13: Voice "Snow, mute" substring false triggers
Handled by whole-utterance matching (Pattern 1).

### Pitfall 14: Hugging Face downloads fail with auth errors
A stale `HF_TOKEN`/cached token makes public repos return "Invalid username or password" (observed on `snapshot_download`). Pre-fetch models in an install step with `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` or without a token; cache under a configurable directory (disk F1).

## Code Examples

Design sketches; Pipecat/Electron API names tagged where verified.

### 1. GPU DLL registration (voice worker entrypoint, before any faster-whisper import)
```python
# Source: pattern from runaihome.com cuDNN article [CITED] + PATH prepend hardening [ASSUMED, verify in S2]
import os, sys
from pathlib import Path

def register_cuda_dlls() -> None:
    site = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for sub in ("cublas", "cudnn"):
        d = site / sub / "bin"
        if d.is_dir():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = f"{d}{os.pathsep}{os.environ['PATH']}"

register_cuda_dlls()
from faster_whisper import WhisperModel  # noqa: E402
model = WhisperModel("turbo", device="cuda", compute_type="int8_float16")
```

### 2. Chain seam (Pipecat adapter over a Pipecat-free LLMChain)
```python
# Source: pipecat/services/openai/base_llm.py get_chat_completions:325-361 [VERIFIED]; chain logic is design
class ChainLLMService(OpenAILLMService):
    def __init__(self, chain: "LLMChain", **kw):
        super().__init__(api_key="unused", **kw)   # real clients live inside LLMChain
        self._chain = chain

    async def get_chat_completions(self, context):
        adapter = self.get_llm_adapter()
        base = adapter.get_llm_invocation_params(
            context, system_instruction=assert_given(self._settings.system_instruction),
            convert_developer_to_user=not self.supports_developer_role)
        # data_class is set by the caller (conversation=private, ack generation=general)
        return await self._chain.stream(messages_params=base, data_class=self.current_data_class)

# LLMChain.stream(): for entry in self.eligible(data_class): try with_raw_response.create(stream=True,
# **entry.params(base)) -> record headers -> return stream; except openai errors -> classify,
# set cooldown, emit llm.switch, continue; raise PrivacyBlockedError / AllProvidersFailed.
# Each AsyncOpenAI is constructed with max_retries=0.
```

### 3. Emotion tag per reply
```python
# Source: pipecat/services/cartesia/tts.py:466-468 [VERIFIED]
def EMOTION_TAG(emotion): return f'<emotion value="{emotion}" />'
ALLOWED = {"neutral","content","calm","curious","sympathetic","excited"}   # config, D-06
def parse_header(buf: str) -> tuple[str, str]:
    m = re.match(r"\s*\[\[([a-z/ ]{3,16})\]\]\s*", buf)
    emo = m.group(1) if m and m.group(1) in ALLOWED else "neutral"
    return emo, buf[m.end():] if m else buf
```

### 4. Event envelope and schema export
```python
# Source: design; Pydantic v2 discriminated union [ASSUMED API, standard]
class Envelope(BaseModel, extra="forbid"):
    type: str; source: str; ts_ns: int; seq: int | None = None
    correlation_id: str | None = None; causation_id: int | None = None
    user_id: str = "owner"; risk_tier: Literal["free","announce","ask","always_ask"] = "free"
    reason: str | None = None; result: str | None = None

class WakeDetected(Envelope): type: Literal["wake.detected"]; score: float
class TranscriptPartial(Envelope): type: Literal["transcript.partial"]; text: str
Event = Annotated[WakeDetected | TranscriptPartial | ..., Field(discriminator="type")]
Path("contracts/events.schema.json").write_text(json.dumps(TypeAdapter(Event).json_schema(), indent=2))
```

### 5. SQLite pragmas
```python
conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;")
```

### 6. Autostart registration (PowerShell, run by `snow install-autostart`)
```powershell
# Source: learn.microsoft.com New-ScheduledTaskSettingsSet [CITED]
$action  = New-ScheduledTaskAction -Execute "$env:LOCALAPPDATA\Snow\.venv\Scripts\pythonw.exe" -Argument "-m snow.hub" -WorkingDirectory "$env:LOCALAPPDATA\Snow"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$set = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Snow" -Action $action -Trigger $trigger -Settings $set -Force
```
(Phase 1 path points at the working tree venv; the pinned install location is CORE-06 / Phase 2.)

### 7. Click-through mini window
```ts
// Source: electronjs.org BrowserWindow setIgnoreMouseEvents/forward [CITED]
mini.setIgnoreMouseEvents(true, { forward: true })
ipcMain.on('mini:hover', (_e, over: boolean) => mini.setIgnoreMouseEvents(!over, { forward: true }))
mini.setAlwaysOnTop(true, 'floating'); mini.setSkipTaskbar(true)
```

### 8. Redaction processor
```python
# Source: design [ASSUMED]
SECRET_RX = re.compile(r"(xpl_|gsk_|nvapi-|sk-or-|sk_car_|AIza)[A-Za-z0-9_\-]{12,}")
def redact(_, __, ev: dict) -> dict:
    for k in list(ev):
        if re.search(r"key|token|secret|password|authorization|cookie", k, re.I): ev[k] = "[REDACTED]"
        elif isinstance(ev[k], str):
            v = SECRET_RX.sub("[REDACTED]", ev[k])
            for s in known_secrets(): v = v.replace(s, "[REDACTED]")
            ev[k] = v
    return ev
```

### 9. Wake gate with RAM-only ring buffer
```python
# Source: openWakeWord model.predict on 1280-sample int16 frames [CITED: README, VERIFIED run]
RING = collections.deque(maxlen=25)            # ~2 s of 80 ms frames, memory only (D-18)
def on_frame(frame: np.ndarray):               # 1280 int16 samples @ 16 kHz
    RING.append(frame)
    scores = oww.predict(frame)
    if scores["hey_snow"] >= THRESH and patience_ok():
        replay = list(RING)[-5:]               # ~4 frames before detection + current
        emit_threadsafe(WakeDetected(score=...)); engine.start_turn(preroll=replay)
```

### 10. Pipecat observer to publish to the bus (no pipeline changes)
```python
# Source: pipecat/observers/base_observer.py exists [VERIFIED listing]; API shape [ASSUMED]
class BusObserver(BaseObserver):
    async def on_push_frame(self, data):          # map TranscriptionFrame/InterimTranscriptionFrame/
        ...                                       # BotStarted/StoppedSpeakingFrame -> typed events
```

## Wake Word Plan (resolves research focus 1)

1. **Interim (skeleton, today):** openWakeWord pretrained `hey_jarvis_v0.1` (ONNX, 1.27 MB) `[VERIFIED: downloaded + benchmarked]`. It matches the Jarvis persona and exercises the full wake/pre-roll/wake-alone path. License of pretrained models is CC BY-NC-SA 4.0 `[CITED: openWakeWord README]` (fine for personal use; flag for "others later").
2. **Target model "hey snow":** train with **livekit-wakeword 0.3.0** (Apache-2.0): one YAML (`model_name: hey_snow`, `target_phrases: ["hey snow"]`, `n_samples: 10000`, `model_type: conv_attention`, `model_size: small`, `steps: 50000`, `target_fp_per_hour: 0.2`), stages `setup -> generate -> augment -> train -> export -> eval` or `run`; Piper VITS synthetic positives with 904-speaker SLERP blending plus phoneme-based adversarial negatives (CMUdict) `[CITED: livekit-wakeword docs]`. Its published results are on its own "hey livekit" set: conv-attention head FPPH 0.08, recall 86.1% vs openWakeWord DNN 8.50 / 68.6% `[CITED, vendor benchmark]`. Documented platforms are macOS and Ubuntu; run on Colab/cloud GPU/WSL2 (not this disk). Fallback recipe: community Colab `alfiedennen/openwakeword-colab-2026` (MIT; fixes Python 3.12 `piper-phonemize` wheel gap, about 75-90 min on Colab L4/Pro, 2.5 h on free T4) `[CITED]`.
3. **Compatibility spike (S3):** confirm the exported ONNX conv-attention classifier (input `embeddings` shape (1,16,96), output `score`) loads in the **openWakeWord** streaming runtime via `Model(wakeword_models=[path], inference_framework="onnx")`. If not, either use `livekit.wakeword.WakeWordModel` (stateless, ~2 s windows; the runtime cost is higher but cheap versus 80 ms cadence budget `[ASSUMED]`) or train with the `dnn` head, which exports bit-exact to the openWakeWord format `[CITED]`.
4. **Real negatives:** an explicit user action (`snow dev record-negatives`) records ambient/TV/typing locally to a user-chosen folder (never the conversation log); fed to the training run as `background_paths`/hard negatives; stays local (Claude's-discretion item on recording location).
5. **Acceptance:** false accepts/hour on >= 2 h of real ambient+TV audio under a threshold, recall >= 90 % on the user's own 50 utterances at 3 mic distances; document the chosen threshold in config.
6. **sherpa-onnx keyword spotting** (named as an interim in the brief) is unnecessary because `hey_jarvis` already provides a working interim with zero extra dependency; keep it only as a spike comparator if both oWW options fail `[ASSUMED]`.

## Resolved Research Questions (index)

| Brief item | Where resolved |
|------------|----------------|
| openWakeWord/"Hey Snow" recipe, interim, post-wake audio | Wake Word Plan; Pattern 1; Pitfalls 1-2 |
| faster-whisper partials, latency/VRAM, DLL loading | Pattern 4; Pitfall 6; Code Example 1; spike S2 |
| Pipecat fit, sounddevice transport, Smart Turn, barge-in, chain wrapper | Standard Stack alternatives; Patterns 1, 3, 7; spike S1 |
| Cartesia emotion, failure/credit detection, kokoro switch | Pattern 8-9; spike S4; F2 |
| Provider rate-limit headers, quirks | Pattern 3 tables |
| Electron click-through, tray, single instance, autostart, supervisor | Patterns 5, 11; spike S5 |
| Event log schema, contract pipeline, retention | Pattern 2 |
| keyring setup, structlog redaction | Patterns 12-13 |
| CI | Pattern 14 |
| Canvas 2D orb budget | Pattern 11; Validation Architecture |

## Suggested Build Slices (for the planner; Walking Skeleton first)

| Slice | Content | Proves |
|-------|---------|--------|
| W0 | Disk freed (F1); repo scaffold: uv 3.12, ruff/pyright/pytest, hud toolchain, CI skeleton, contract pipeline, spikes S1-S6 | Tooling and go/no-go gates |
| W1 (skeleton) | Hub: bus + SQLite log + WS + snapshot/delta; HUD (Electron, dashboard + mini, Canvas orb, transcript, mute button) driven by a scripted fake voice worker | CORE-03, HUD-03 (no audio yet), QUAL-03 basics |
| W2 | Real voice worker: MicSource/FileSource, wake gate (hey_jarvis), TurnEngine, STT with partials, kokoro out, brain worker with Groq fast chain and persona | VOIC-01/04/05/08, SPCH-01/04 (local voice) end to end |
| W3 | Cartesia + router/failover + emotion + credits probe; barge-in; modes (sleep, mute persisted, conversation timeout); ack pool | VOIC-03/06, SPCH-02/03 |
| W4 | Full chains, cooldown/counters, privacy routing, secrets (`snow setup`), provider health in HUD, gateway spike notes | CORE-04/08/09/10, SAFE-09/12 |
| W5 | Supervisor, worker kill tests, Task Scheduler autostart, retention purge, redaction canary, hardware suite, "hey snow" model integration, CI required checks | CORE-01/02, QUAL-01/03, VOIC-01 final |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pipecat `InputParams`/constructor args | `Settings` dataclasses (deprecated since 0.0.105) | 2026 | Use `settings=...` for Cartesia/OpenAI services `[VERIFIED: base_llm.py]` |
| Aggregator-only VAD turns | Pluggable user turn start/stop strategies (Smart Turn default, external strategies) | Pipecat 1.x | External turn control is first-class |
| openWakeWord DNN head | Conv-attention head (livekit-wakeword) | 2026 | Lower false positives (vendor benchmark) |
| ctranslate2 + cuDNN 8 | cuDNN 9 from ctranslate2 >= 4.5 | 2024 | pip `nvidia-cudnn-cu12==9.*` `[CITED]` |
| Porcupine free tier | openWakeWord (free tier AccessKeys ended 2026-06-30, secondary source) | 2026 | Project already chose oWW |

**Deprecated/outdated:** `pyaudio` (2023), `litellm` (compromised releases), Pipecat deprecated constructor params, Piper (GPL) as shipped fallback.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | NVIDIA NIM and Groq are `trusted` providers (D-26 names only Google AI Studio free and OpenRouter free as untrusted) | Pattern 3 | Private data would flow to a provider the user considers untrusted; user must confirm |
| A2 | Voice-conversation turns default to `data_class=private` (fail closed), so Gemini/OpenRouter serve only content-free prompts | Pattern 3 | If user wants Gemini/OpenRouter to answer general chat, the config flag must be flipped; otherwise brain chain loses entries 2 and 4, fast chain loses entry 4 |
| A3 | Exported livekit-wakeword conv-attention ONNX loads in the openWakeWord streaming runtime | Wake Word Plan | Need `livekit.wakeword` runtime or the `dnn` head; spike S3 |
| A4 | Wake-alone window of ~1.0 s after detection and 320 ms pre-roll are workable defaults | Pattern 1 | Tuning only; fixtures decide |
| A5 | faster-whisper turbo int8_float16 gives 150-300 ms final decode and 1.2-2 GB VRAM on the RTX 4050 with the HUD running | Pattern 4/10 | Latency budget misses 1 s; fall back to distil-large-v3, smaller beam |
| A6 | PATH prepend is needed in addition to `os.add_dll_directory` for cuDNN lazy loads | Pitfall 6 | Harmless if unneeded; if both fail use Purfview archive path |
| A7 | Task Scheduler restarts only on failed (non-zero) exit, so exit code 0 on Quit stays quit | Pattern 5 | Quit would auto-relaunch; verify in S6 |
| A8 | Pipecat's wall-clock-based built-in turn strategies mishandle a pre-roll burst | Pattern 1 | If wrong, thinner integration possible; spike S1 |
| A9 | `with_raw_response.create(stream=True).parse()` works in openai 3.29 for async streaming | Pattern 3 | Need header capture via httpx event hooks instead |
| A10 | `json-schema-to-typescript` 16 renders Pydantic `oneOf`+`const` unions correctly | Pattern 2 | Use quicktype-core or datamodel->TS alternative |
| A11 | Cartesia `GET /usage/credits` exists and returns a usable remaining-credit figure | Pattern 9 | HUD shows "Unavailable" permanently (acceptable per UI-SPEC) |
| A12 | Out-of-credits arrives as a WS `error` message with status 402/429/403 or credit/quota text | Pattern 9 | Misclassification delays fallback; log raw payload and adjust |
| A13 | Kokoro fp32 or pocket-tts would be faster than the int8 model on this CPU | Pattern 9 | Local voice stays at RTF ~1 |
| A14 | WinVaultKeyring size limit (~2.5 KB) is sufficient for all keys; keyring works in the Task Scheduler logon session | Pattern 13 | Keys unreadable at logon; verify in S6 |
| A15 | Playwright `_electron` suffices for HUD perf-mark tests | Pattern 11 | Use Playwright against the renderer in Chromium with a mock hub |
| A16 | Famulor catalog's voice names exist in the user's Cartesia library and fit the Jarvis tone | Pattern 8 | Audition tool lists real voices; shortlist is only a starting point |
| A17 | Windows Graphics Settings can pin `electron.exe` to the iGPU | Pattern 11 | Orb shares dGPU with STT (light for Canvas 2D) |
| A18 | A plain spoken fallback line is acceptable when the LLM is down (SPCH-01) despite D-09's "no chime/earcon" | Pattern 8 | User may prefer silence plus HUD text |

## Open Questions

1. **Free disk space (F1)**
   - Known: 1.4 GB free; Phase 1 needs ~8-10 GB local plus off-machine training.
   - Unclear: whether the user can free space or move caches to another drive (only C: exists).
   - Recommendation: block execution on this; make it Wave 0 task 0 with a verification command (`Get-PSDrive C` free >= 15 GB).
2. **GitHub remote and branch protection (F4)**
   - Known: no remote; Free private repos lack enforced required checks; user's other repos are a mix of public/private.
   - Unclear: will Snow's repo be public (it will contain no secrets by design) or private?
   - Recommendation: ask the user; if private-free, document that "cannot be merged" is enforced by convention + pre-push hook only.
3. **Trust levels for NIM and Groq (A1) and default data class for conversation (A2)**
   - Recommendation: confirm before the privacy-routing task; both are one-line config.
4. **Who trains "hey snow" and on what compute?**
   - Recommendation: a Colab/cloud run using a committed YAML; plan an explicit human-action task with acceptance criteria (Wake Word Plan 5); `livekit-wakeword` needs a checkpoint:human-verify.
5. **Wake-alone fallback when the LLM and the ack pool are both empty (A18)**
   - Recommendation: allow a one-word spoken fallback tagged `source=fallback`; confirm with the user.
6. **Cartesia key and credit endpoint**
   - Unclear: whether the user has a Cartesia account/key; `GET /usage/credits` shape.
   - Recommendation: spike S4 once the key is stored; HUD shows "Unavailable" until then.
7. **Is local voice quality/speed acceptable (F2)?**
   - Recommendation: run the kokoro fp32/pocket-tts spike and let the user hear it; if still poor, ask whether D-16's local voice may change engine.
8. **Process topology deviation from CLAUDE.md (hub + workers)**
   - Recommendation: planner treats as a design decision with user visibility in the plan summary; the single-process alternative cannot demonstrate CORE-02 for native crashes.
9. **Gateway facts that need keys (D-29, D-30)**
   - IDs for NIM models and OpenRouter Nemotron, streaming/tool-call behavior per provider, Groq vs deepseek-v4-flash latency. Requires stored keys; any missing key is skipped per D-25.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | Python/venv/lock | yes | 0.11.8 (PyPI latest 0.13.0 per STACK) | - |
| Python 3.12 | core | yes (uv-managed, fetched during research) | 3.12.13 | - |
| System Python | - | 3.10.9 default, 3.14.4 `python3` | do not use | uv |
| Node.js / npm | HUD | yes | 25.6.0 / 11.3.0 (non-LTS) | use LTS in CI |
| git / gh | VCS, CI | yes; gh authenticated as Astroash2001 | 2.52.0 / 2.96.0 | - |
| Git remote | CI, branch protection | **no** | - | create repo (Open Q2) |
| NVIDIA GPU + driver | STT | yes | RTX 4050 6141 MiB, driver 596.49, 1292 MiB used | CPU smaller Whisper model |
| CUDA toolkit | - | not needed (pip wheels) | - | - |
| Free disk | everything | **no (1.4 GB)** | - | free space (F1) |
| Docker / ffmpeg | - | no / no | not needed | - |
| Microphone + headphones | hardware suite | unknown | - | FileSource WAV injection (D-07) for CI |
| Provider API keys (5) + Cartesia key | gateway spike, TTS | not stored (unknown) | - | skipped per D-25; kokoro voice |
| Internet | downloads, providers | yes | - | - |

**Missing dependencies with no fallback:** free disk space; GitHub remote for QUAL-01 enforcement.
**Missing with fallback:** provider keys (skipped), mic (WAV injection), LTS Node (CI only).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (asyncio_mode=auto), respx for HTTP mocks; Vitest 5.0.4; @playwright/test 1.64.1 (Electron) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (markers: `hardware`, `gpu`, `slow`), `hud/vitest.config.ts`, `hud/playwright.config.ts` - all Wave 0 |
| Quick run command | `uv run pytest -x -q -m "not hardware and not gpu and not slow"` ; `npm --prefix hud run test` |
| Full suite command | `uv run pytest -m "not hardware" && npm --prefix hud run test && npm --prefix hud run e2e` (CI); local hardware suite adds `-m "hardware or gpu"` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CORE-01 | Task XML/args correct (logon trigger, restart, no time limit, battery flags); actual logon boot | unit + manual-only (reboot) | `pytest tests/hub/test_autostart.py -x` | Wave 0 |
| CORE-02 | Worker crash/hang restarted with backoff; real `snow dev kill voice/brain/hud` returns to Running | integration | `pytest tests/hub/test_supervisor.py -x` | Wave 0 |
| CORE-03 | Every turn produces typed events; schema-valid; golden turn | unit | `pytest tests/contracts tests/hub/test_eventlog.py -x` | Wave 0 |
| CORE-04 | Editing `models.toml` changes provider/base_url/model with no code change | unit (respx) | `pytest tests/brain/test_config_swap.py -x` | Wave 0 |
| CORE-08 | 429/insufficient_quota/5xx/timeout/connection error -> next entry; keyless skipped, shown not_configured | unit (respx) | `pytest tests/brain/test_chain.py -x` | Wave 0 |
| CORE-09 | Counters, header-based cooldown, skip while cooling | unit | `pytest tests/brain/test_cooldown.py -x` | Wave 0 |
| CORE-10 | `llm.call` has provider+model; switch notice emitted | unit | `pytest tests/brain/test_provenance.py -x` | Wave 0 |
| VOIC-01 | Wake TP/hard-negative fixtures; no network sockets from voice worker while asleep | unit + integration | `pytest tests/voice/test_wake.py tests/voice/test_no_egress.py -x` ; FP/hour = hardware | Wave 0 |
| VOIC-03 | Mute closes input stream; persists across restart; HUD banner | unit + e2e | `pytest tests/voice/test_mute.py -x` ; `npm --prefix hud run e2e -- mute` | Wave 0 |
| VOIC-04 | STT on fixture WAVs under WER bound | gpu | `pytest -m gpu tests/voice/test_stt_wer.py` | Wave 0 |
| VOIC-05 | Pause mid-thought does not end turn (real Smart Turn on CPU) | unit | `pytest tests/voice/test_turn_engine.py -x` | Wave 0 |
| VOIC-06 | Speech during TTS cancels LLM + playout <= 150 ms; `reply.interrupted` | integration (fake transport) | `pytest tests/voice/test_bargein.py -x` | Wave 0 |
| VOIC-08 | `transcript.partial` stream then final; HUD partial row | unit + e2e | `pytest tests/voice/test_partials.py -x` ; `npm --prefix hud run e2e -- transcript` | Wave 0 |
| SPCH-01 | No literal speech strings on speech path (lint-style test); acks LLM-sourced; fallback tagged | unit | `pytest tests/brain/test_no_scripts.py -x` | Wave 0 |
| SPCH-02 | Emotion header parse/validate/fallback; Cartesia request carries emotion | unit (mock WS) | `pytest tests/brain/test_emotion.py tests/voice/test_cartesia_req.py -x` | Wave 0 |
| SPCH-03 | Cartesia 402/connection failure -> kokoro; failback after probe; `voice.status` events | integration | `pytest tests/voice/test_tts_failover.py -x` | Wave 0 |
| SPCH-04 | Pipeline overhead < 100 ms with fakes; real p50 <= 1.0 s / p95 <= 1.6 s | unit + hardware | `pytest tests/voice/test_latency_fake.py -x` ; `pytest -m hardware tests/hardware/test_latency.py` | Wave 0 |
| HUD-03 | wake -> `listening` painted <= 100 ms; event->paint <= 50 ms | e2e perf | `npm --prefix hud run e2e -- perf` | Wave 0 |
| QUAL-01 | CI runs all gates; failing PR blocked | manual-only (open failing PR) + CI config lint | `gh run list` / PR check | Wave 0 |
| QUAL-03 | JSON logs; health snapshot lists subsystems; Down state visible | unit + e2e | `pytest tests/test_logging.py tests/hub/test_health.py -x` | Wave 0 |
| SAFE-09 | Canary secret absent from logs, events, WS frames, config; `snow setup` stores to keyring | unit | `pytest tests/test_secrets_canary.py -x` | Wave 0 |
| SAFE-12 | Private data + only untrusted providers -> `PrivacyBlockedError`, zero HTTP calls | unit (respx assert_all_called=False, no routes hit) | `pytest tests/brain/test_privacy.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** quick run command (< 30 s target; heavy model tests marked `slow`/`gpu`).
- **Per wave merge:** full suite (CI set) green.
- **Phase gate:** full CI suite plus local hardware suite (latency percentiles, false accepts, barge-in on headphones) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `pyproject.toml` (pytest markers, ruff, pyright strict), `uv.lock`, `.python-version`
- [ ] `tests/conftest.py`: fake audio source/sink, fake hub client, in-memory keyring backend, respx fixtures, fake clock
- [ ] `tests/fixtures/audio/*.wav`: synthetic fixtures (kokoro-generated): wake only, wake+command at 0/150/600 ms gap, mid-thought pause, TV-like negatives, "that's all"/"mute" phrases, barge-in overlap
- [ ] `hud/` toolchain: vitest, playwright (electron), biome, ajv contract tests; mock hub for e2e
- [ ] `.github/workflows/ci.yml`; gitleaks config; pip-audit
- [ ] `tests/hardware/` harness (marked) for latency p50/p95, FP/hour, barge-in on headphones, reboot-logon checklist

## Security Domain

`security_enforcement` is enabled (ASVS level 1, block on high).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (local components) | Per-launch 256-bit token on the loopback WS for HUD and workers |
| V3 Session Management | limited | Token lifetime = process launch; regenerate on hub restart |
| V4 Access Control | yes | Bind 127.0.0.1; Origin/Host checks; worker vs HUD roles with distinct allowed commands |
| V5 Input Validation | yes | Pydantic `extra="forbid"` on every inbound WS message; max frame size |
| V6 Cryptography | yes | `keyring` (OS credential store); no custom crypto; TLS to providers via SDK defaults |
| V7 Error Handling and Logging | yes | structlog redaction + canary test; loguru bridged |
| V8 Data Protection | yes | No raw audio on disk (D-18); transcripts 30-day retention; privacy routing (SAFE-12) |
| V10 Malicious Code / Supply chain | yes | uv hash-locked `uv.lock`, `exclude-newer`, pip-audit, npm audit, gitleaks, Actions pinned by SHA, no litellm |
| V12/V13 API/WebSocket | yes | message schema contract; no unauthenticated endpoints; no `0.0.0.0` |
| V14 Configuration | yes | No secrets in repo/config; Electron `contextIsolation`, `sandbox`, CSP |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Local process or web page connects to the hub WS (DNS rebinding / cross-origin) | Spoofing/Elevation | Token + Origin/Host allowlist + loopback bind |
| API key leaks into logs/events/HUD/config | Information disclosure | Credential Manager only; redaction processor; canary test; no key in child env |
| Personal data to a provider that trains on it | Information disclosure | `data_class` + `trust` routing, fail closed, zero-HTTP test |
| Idle audio exfiltration | Information disclosure | Wake/VAD/STT local; socket-level egress test for the voice worker; Cartesia/LLM receive text only |
| Orphan worker keeps the mic/GPU after hub death | Denial of service/Privacy | Job Object KILL_ON_JOB_CLOSE |
| Transcripts in third-party debug logs | Information disclosure | loguru sink at WARNING+; no context logging |
| Unmute race / silent unmute after restart | Tampering | Persisted mute, confirmed-state events, worker starts muted |
| Supply-chain compromise of a Python dependency | Tampering | Hash-locked installs, delayed adoption, audit scanners; avoid litellm |
| Wake phrase triggered by TV/other audio | Spoofing | Threshold from measured FP/hour; speaker verification arrives in Phase 2 (VOIC-07); Phase 1 acts on nothing dangerous (no tools yet) |
| Prompt injection via transcript | Tampering | Phase 1 has no tools or file access; persona prompt treats user text as chat; risk tiers arrive Phase 2 |

## Sources

### Primary (HIGH confidence)
- Local source reads and runs this session: `pipecat/services/openai/base_llm.py`, `services/cartesia/tts.py`, `services/stt_service.py`, `services/whisper/stt.py`, `transports/local/audio.py`, observers/turns listings (Pipecat 1.12.0 installed in a scratch venv, since removed); PyPI JSON API; npm registry; `https://api.experientiallabs.ai/api/models` public catalog; local benchmarks listed in Measured Data.
- https://github.com/pipecat-ai/pipecat (turns/user_stop, user_start/external_user_turn_start_strategy.py via GitHub API)
- https://docs.pipecat.ai/pipecat/learn/speech-input.md ; /api-reference/server/services/tts/cartesia ; /api-reference/server/utilities/service-switchers/service-switcher ; /api-reference/server/services/llm/openai
- https://github.com/livekit/livekit-wakeword (README, docs/overview, data-generation, training, export-and-inference via GitHub API)
- https://github.com/dscripka/openWakeWord README
- https://platform.experientiallabs.ai/llms.txt (first 100K of 163K chars)
- https://console.groq.com/docs/rate-limits ; https://openrouter.ai/docs/api-reference/limits ; https://ai.google.dev/gemini-api/docs/openai ; https://ai.google.dev/gemini-api/docs/rate-limits
- https://docs.cartesia.ai/pricing.md ; /api-reference/tts/tts ; /examples/error-handling.md ; /build-with-cartesia/capability-guides/choosing-a-voice.md
- https://github.com/openai/openai-python README
- https://learn.microsoft.com/powershell/module/scheduledtasks/new-scheduledtasksettingsset
- https://www.electronjs.org/docs/latest/api/browser-window (first 100K of 113K chars)
- https://python-sounddevice.readthedocs.io (WasapiSettings)
- https://github.com/SYSTRAN/faster-whisper README

### Secondary (MEDIUM confidence)
- https://github.com/alfiedennen/openwakeword-colab-2026 (MIT community Colab, claims about Python 3.12 fixes)
- https://runaihome.com/blog/cudnn-ops64-9-dll-error-fix-2026/ (cuDNN DLL guidance)
- https://github.com/kyutai-labs/pocket-tts README (speed claims on other hardware)
- https://docs.github.com/.../about-protected-branches (partial plan information)

### Tertiary (LOW confidence)
- https://www.famulor.io/voices/cartesia/languages/en/accents/british (voice names only)
- NVIDIA developer forums / Medium for NIM 40 RPM
- apievangelist catalog entry for Cartesia `GET /usage/credits`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH for versions and Python 3.12/Windows installability (installed and run); MEDIUM for GPU STT (unmeasured)
- Architecture: MEDIUM-HIGH; hub+workers is a reasoned deviation from the CLAUDE.md sketch; Pipecat fit pending spike S1
- Pitfalls: MEDIUM-HIGH; several verified locally (disk, kokoro speed, logging), others from official docs
- Wake word "Hey Snow": LOW-MEDIUM until the trained model is evaluated

**Spike gates for Wave 0 (go/no-go):** S1 Pipecat fit (custom sounddevice transport, external turn strategies with replay burst, interruption cancel latency, ServiceSwitcher failover); S2 faster-whisper turbo on GPU (latency, VRAM, DLL loading under Task Scheduler, partial cadence); S3 livekit-wakeword ONNX head in the openWakeWord runtime; S4 provider/Cartesia facts with real keys (`GET /models`, streaming, tool calls, Groq vs deepseek-v4-flash TTFT and time-to-first-audio, Cartesia error shape, `/usage/credits`); S5 Electron transparent click-through mini window on Windows (hover toggle, drag, DPI clamp); S6 Task Scheduler behaviors (exit code 0 stays quit, keyring and CUDA DLLs at logon).

**Research date:** 2026-10-15
**Valid until:** 2026-10-22 for provider limits and package versions (fast-moving); 30 days for architecture
