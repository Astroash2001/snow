# Phase 1: Always-On Voice Loop - Context

**Gathered:** 2026-10-14
**Status:** Ready for planning

<domain>
## Phase Boundary

The user wakes Snow by saying "Hey Snow", talks naturally, and hears a fast, LLM-written, emotion-voiced reply in a Jarvis-like voice that responds to the user's tone. The laptop does as little heavy work as possible: speech-to-text runs on Groq's cloud, everyday speech is a light CPU voice, and Cartesia is kept for the big emotional moments (D-32 to D-41, revised 2026-10-15). Underneath: the event bus and durable event log, a supervisor that restarts crashed subsystems, autostart at Windows logon, secrets in Windows Credential Manager, config-swappable LLM roles, and typed/linted/tested CI.

The HUD in this phase is light: a full dashboard window (presence orb, live transcript, subsystem health, mute state) and a minimized mini indicator. No coding agents, no PC control, no speaker verification (Phase 2). The ASCII orb ships in Phase 1 as a 2D glyph renderer (D-12, D-31); Phase 6 upgrades it to the full 3D shader version.

Requirements: CORE-01..04, VOIC-01, VOIC-03..06, VOIC-08, SPCH-01..04, HUD-03, QUAL-01, QUAL-03, SAFE-09. VOIC-02 is removed from this phase by user decision (see D-07).

</domain>

<decisions>
## Implementation Decisions

### Persona and replies
- **D-01:** Snow talks like J.A.R.V.I.S. from the MCU (Paul Bettany): composed, competent, natural tone, with dry, sarcastic British-style humor as the normal register. The user wants it "as close to Jarvis as possible".
- **D-02:** Snow addresses the user as "sir", used naturally, the way Jarvis does.
- **D-03:** Guardrail: sarcasm switches off when something goes wrong (errors, failures, unreachable services) or when the user sounds stressed. In those moments Snow is plain, direct and helpful.
- **D-04:** Reply length matches the question. The LLM judges per turn: banter gets a line, a real question gets a full answer. No fixed sentence cap, but the reply must still start speaking within about 1 second (SPCH-04), so stream sentence by sentence.
- **D-05 (revised 2026-10-15):** Snow has one male voice, calm, dry, British-leaning, Jarvis-like. The local engines (Pocket TTS, Chatterbox) clone it from one reference voice, so they sound the same. The reference must come from a consenting source: the user's own voice, a friend who agrees, or a licensed preset voice. It must never be a clone of the film actor or any other real person who has not agreed. Cartesia's free plan has no voice cloning, so Cartesia uses the closest stock male voice; the user picks both in a short audition step. Voice IDs and the reference clip path live in config. Who provides the reference voice is still open; until the user decides, use a licensed Pocket TTS preset voice.
- **D-06:** Vocal emotion is natural and mostly upbeat. The LLM picks one emotion per reply from a small validated set (for example content, calm, excited, sympathetic, neutral), defaulting to warm or content, with strong emotions only when the moment calls for it. Invalid values fall back to neutral.

### Conversation flow
- **D-07:** No push-to-talk key. The user wakes Snow by name only, like Tony calling Jarvis. VOIC-02 (push-to-talk hotkey) is dropped from Phase 1. ROADMAP.md success criterion 1 and REQUIREMENTS.md were updated on 2026-10-14 (VOIC-02 moved to Out of Scope). A developer-only test input (for example, injecting a recorded WAV or typed text into the pipeline for tests and CI) is allowed, but it is not a user-facing feature. — **Reversibility:** reversible — adding a hotkey later is a small, isolated input source on the event bus.
- **D-08:** Wake once, stay in conversation. After "Hey Snow", Snow keeps listening with no re-wake until the user ends it ("that's all", or similar) or about 30-60 seconds of silence pass. Then it returns to wake-word-only listening.
- **D-09:** Wake cue follows Jarvis behavior:
  - "Hey Snow, <command>" in one breath: Snow acts and replies directly. No acknowledgement first. The audio after the wake phrase must be captured as part of the turn (pre-roll/continuation), not lost.
  - "Hey Snow" alone: Snow speaks a short, LLM-written acknowledgement in Jarvis style (for example "Sir?") and waits.
  - No chime or earcon. The orb reacts immediately (HUD within 100 ms, HUD-03).
- **D-10:** Two quiet states:
  - **Soft sleep:** "Snow, go to sleep" (by voice). The mic stays on locally, and Snow ignores everything except the wake phrase.
  - **Hard mute:** the mic is fully off. Triggered by voice ("Snow, mute") or by clicking the orb or the tray icon. Unmute is by click only, because a muted mic cannot hear "unmute". The HUD must make the hard-mute state unmistakable (VOIC-03).

### HUD (Phase 1 form)
- **D-11:** Two window forms:
  - **App open:** the full dashboard window.
  - **App minimized:** the full dashboard stops rendering (no background GPU/CPU cost), and a small always-on-top mini indicator shows that Snow is present and active.
  — **Reversibility:** costly — Phase 6 builds the ASCII orb, the full dashboard and the corner widget on top of this two-form window model, so changing it later touches both windows and the Electron shell.
- **D-12 (revised 2026-10-14):** The presence element is the ASCII network orb from day one, never a plain glowing circle. The user rejected the plain-circle version after seeing generated mockups: "I want the ASCII interpretation of the orb everywhere." In Phase 1 it is a 2D glyph orb: a sphere of nodes and connecting lines drawn from ASCII characters, digits and code fragments, each glyph keeping its own color, cyan to violet, glow on the orb only. It moves with the user's voice and with Snow's voice and is colored by state (sleeping, listening, thinking, speaking, muted). The same component appears in the full and mini forms. The orb needs audio-level events on the bus for both mic input and TTS output. Visual target: `.planning/phases/01-always-on-voice-loop/refs/snow-vision-ascii-orb-dashboard.png` (the orb, not the page around it). — **Reversibility:** reversible — Phase 6 swaps the renderer behind the same `Presence` props.
- **D-31:** The ASCII orb is Snow's only visual identity. A tiny rendering of the orb is also the app icon, the tray icon and Snow's avatar in the transcript. No snowflake or other logo. The rest of the interface stays clean (dark panels, modern sans-serif text, as in the reference image); only the orb is ASCII. Phase 6 upgrades the orb to the full 3D shader version (letters revealed on zoom, bloom, glyph atlas from the user's code) without changing where it appears.
- **D-13:** Mini indicator: top-right corner by default, draggable, position remembered, click-through so it never blocks clicks on the windows below, and clicking it opens the full dashboard. It shows only the orb while idle. While in conversation, a one-line caption of what Snow heard appears next to it, then fades.
- **D-14:** The full dashboard shows the transcript chat-style for the current conversation: the user's words updating live as they speak (VOIC-08), Snow's replies, newest at the bottom. The view clears when the conversation ends. Full history stays in the event log (the history view is Phase 6).
- **D-15 (revised 2026-10-15):** The full dashboard also shows subsystem health (each subsystem up or down, QUAL-03), the mute or sleep state, which voice engine spoke last (Pocket TTS, Cartesia, Chatterbox or Kokoro), the remaining Cartesia credits, and the speech-to-text source (Groq cloud or local).

### Fallback voice and privacy
- **D-16 (superseded 2026-10-15 by D-33):** ~~Use Cartesia for every reply until credits run out, then kokoro-onnx.~~ Cartesia is now used only for big emotional moments; see D-33.
- **D-17 (revised 2026-10-15):** When Snow loses a capability it normally has (Cartesia credits run out, speech-to-text falls back to the local model, the GPU voice is unavailable), Snow mentions it once in an LLM-written line, in character (for example, a dry remark about its "budget voice"). The HUD always shows the active voice, the speech-to-text source and the remaining credits.

### Voice, tone and speech-to-text (added 2026-10-15; locked by the user)
- **D-32:** Goal: Snow sounds emotional and human while the laptop does as little heavy processing as possible, and it stays free. The user accepted these compromises: everyday emotion is basic (a few moods) and the full emotion comes only in the big moments; the voice can shift slightly between engines; with no internet Snow hears through a weaker local model; free limits can run out on heavy days; Groq hears what the user says after the wake word. Snow's capabilities (agents, PC control, phone, memory) are not reduced by any of this.
- **D-33:** Voice router. Each reply goes to one engine, chosen per reply:
  1. **Pocket TTS (Kyutai) on CPU** is the everyday voice. Streaming; the project claims about 200 ms to first audio on 2 CPU cores (not yet measured here). Windows wheels pull CPU-only PyTorch.
  2. **Cartesia `sonic-3.6`** speaks only the big emotional moments: greetings, jokes, bad news, serious warnings. The LLM marks a reply as a big moment together with its emotion (D-06). A per-day budget protects the free plan (20K credits a month, about 27 minutes of audio; 1 credit is 1 character). When credits run out or Cartesia is unreachable, the line goes to Pocket TTS.
  3. **Chatterbox (Resemble AI) on GPU** is used only when the laptop is on mains power and the GPU is idle (enough free VRAM). Use the base model for the emotion dial (`exaggeration`); sources conflict on whether Chatterbox-Turbo supports it, so check in the spike. VRAM use is not measured.
  4. **kokoro-onnx** is the last fallback (flat voice) if the other local engines fail to load.
  — **Reversibility:** reversible — the router, budgets and engine order are config.
- **D-34:** Everyday emotion with Pocket TTS comes from mood clips: 4-5 reference clips of the same voice (for example calm, upbeat, serious, playful, sympathetic). The emotion the LLM picks (D-06) selects the clip. Pocket TTS has no emotion parameter; how well a clip carries emotion is unverified and must be judged by the user in the spike.
- **D-35:** Tone detection, local and light, so Snow responds to how the user sounds, not only the words. For every user turn, measure pitch, loudness and speaking speed, and run a small speech-emotion model on CPU. Candidates: the community `emotion2vec-web-distill` ONNX (about 2.2M parameters, 9.7 MB) or an official emotion2vec+ model; check accuracy, speed and licence in the spike. The result goes to the fast LLM as a short tag next to the transcript (for example `[user tone: stressed, fast, loud]`). The audio stays in memory and is never written to disk (D-18).
- **D-36:** Tone stance is to balance, like Jarvis with Tony: when the user is stressed or angry, Snow stays calm, plain and brief (this extends D-03); when the user is upbeat, Snow matches the energy; reply length and pace follow the user's pace (quick user, short reply). Chosen by Claude as the default; the user can change it.
- **D-37:** Speech-to-text runs on Groq's cloud Whisper (`whisper-large-v3-turbo`) through the same `gsk_` key, one request per finished turn. The Groq rate-limits page lists 20 requests a minute, 2,000 a day, 7,200 audio seconds an hour and 28,800 a day for this model; confirm in the user's account during the spike. Only audio from an active conversation (after the wake word) is sent. Wake detection stays local, and no idle audio leaves the PC (VOIC-01). The user approved Groq hearing these turns. faster-whisper on the GPU is not used in Phase 1. — **Reversibility:** reversible — the speech-to-text source is config.
- **D-38:** A local CPU speech-to-text model (Moonshine, English, streaming) does two jobs: it shows the user's words live on the HUD while they speak (VOIC-08), because Groq returns text only after the turn ends; and it is the full fallback when Groq is unreachable, rate-limited or offline.
- **D-39:** What runs on the laptop in normal use: wake word, voice activity and turn detection, tone detection, Moonshine live words and Pocket TTS, all on CPU. The GPU is used only by Chatterbox when D-33 allows it.

### Defaults set by Claude when the user said "move ahead" (2026-10-15; each is reversible config or convention)
- **D-40:** Process topology follows the research recommendation: one small hub process (event bus, SQLite log, WebSocket server, supervisor, health) plus `voice` and `brain` worker processes plus the Electron HUD, all in one Windows Job Object; Task Scheduler restarts the hub. This deviates from the single `snow-core` sketch in CLAUDE.md so that CORE-02 can be tested honestly.
- **D-41:** Open research questions resolved by default:
  - Disk: C: now has 58.5 GB free, so the disk blocker (research F1) is closed.
  - Repo: no GitHub remote yet. Default is a private repo; "cannot merge when checks fail" is enforced by CI plus a local pre-push hook, because GitHub Free does not enforce required checks on private repos. The user can make the repo public later to get enforced branch protection.
  - Trust: the user's own privacy rule (D-26) excludes only Google AI Studio free and OpenRouter free. Groq, NVIDIA NIM and Experiential Labs are trusted. Conversation turns default to the personal data class.
  - "Hey Snow" wake model: Claude prepares a pinned training recipe (livekit-wakeword or openWakeWord, Colab or another cloud GPU); the user runs it as a human-action checkpoint. Until then the pretrained `hey_jarvis` model is a stand-in for development only.
  - When every LLM provider is down and the acknowledgement pool is empty, Snow stays silent: no spoken literal (project rule: no hard-coded spoken phrases) and no earcon (D-09). The orb shows its alert state and the HUD shows the degraded notice; the event carries `reply_source=fallback`. (Revised 2026-10-15 after plan check; replaces the earlier one-word "Sir?" fallback.)
  - Cartesia key: if none is stored, Cartesia is skipped (same rule as D-25) and big moments use Pocket TTS.
- **D-18:** The event log stores text transcripts (what the user said, what Snow replied) plus event metadata. Raw audio is never written to disk by the conversation pipeline. — **Reversibility:** reversible going forward — audio not saved is gone, but the setting can change for future turns.
- **D-19:** Transcripts are kept 30 days, then deleted automatically. The retention period is configurable.

### LLM layer (added 2026-10-14 from the user's advisor session; locked)
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope and requirements
- `.planning/PROJECT.md` — vision, constraints, Key Decisions table (Electron shell, multi-provider LLM fallback chains, dogfooding order)
- `.planning/REQUIREMENTS.md` — CORE-01..04, VOIC-01..06, VOIC-08, SPCH-01..04, HUD-03, QUAL-01, QUAL-03, SAFE-09 (note D-07: VOIC-02 removed from Phase 1)
- `.planning/ROADMAP.md` § "Phase 1: Always-On Voice Loop" — goal, success criteria, notes (criterion 1 must drop the push-to-talk wording per D-07)
- `.planning/STATE.md` — gateway details and open concerns (Cartesia free tier about 25 min/month)

### Stack and architecture research
- `.claude/CLAUDE.md` — technology stack with versions; user decisions of 2026-10-13 and 2026-10-14 override research text (Electron, not Tauri; LLM roles and fallback chains; luna rejects `temperature`)
- `.planning/research/STACK.md` — library choices and versions (Pipecat, openWakeWord, faster-whisper, Cartesia, kokoro-onnx, keyring, structlog)
- `.planning/research/ARCHITECTURE.md` — ports and adapters, durable event log, snapshot-plus-delta, supervisor, loopback WebSocket with token
- `.planning/research/PITFALLS.md` — known failure modes (wake-word training, CUDA/cuDNN DLLs, latency, barge-in)
- `.planning/research/FEATURES.md` — table-stakes voice features
- `.planning/research/SUMMARY.md` — consolidated recommendations and phase research flags

### External
- Experiential Labs gateway docs: https://platform.experientiallabs.ai/docs and https://platform.experientiallabs.ai/llms.txt — base URL `https://api.experientiallabs.ai/v1`, model catalog at `https://api.experientiallabs.ai/api/models`
- Groq OpenAI compatibility and rate limits: https://console.groq.com/docs/openai and https://console.groq.com/docs/rate-limits
- Google AI Studio OpenAI compatibility: https://ai.google.dev/gemini-api/docs/openai
- NVIDIA NIM API catalog: https://build.nvidia.com
- OpenRouter API and free-model limits: https://openrouter.ai/docs
- Groq speech-to-text and its rate limits: https://console.groq.com/docs/speech-to-text and https://console.groq.com/docs/rate-limits
- Pocket TTS (Kyutai): https://github.com/kyutai-labs/pocket-tts (code MIT; check the weights and preset-voice licences on Hugging Face)
- Chatterbox (Resemble AI): https://github.com/resemble-ai/chatterbox and https://huggingface.co/ResembleAI/chatterbox-turbo
- Cartesia free plan: https://cartesia.ai/pricing (20K credits a month, no voice cloning on Free)
- Moonshine streaming speech-to-text: https://github.com/moonshine-ai/moonshine
- Small speech-emotion model candidate: https://huggingface.co/thomashallock/emotion2vec-web-distill

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None. The repository holds only planning documents and GSD tooling. Phase 1 is greenfield.

### Established Patterns
- None yet. Phase 1 sets the conventions (Python 3.12 via uv, ruff, pyright strict, pytest; TypeScript HUD with Biome and Vitest; Electron shell).

### Integration Points
- Everything later phases build reads from the Phase 1 event bus and event log, and the HUD is a WebSocket client of the core. Get the event contract (Pydantic models exported to JSON Schema, generated TS types) right here.

</code_context>

<specifics>
## Specific Ideas

- Reference character: J.A.R.V.I.S. in the MCU, in particular how he responds when Tony calls him: no button, no chime, he simply answers or acts, says "sir", is calm under pressure and dryly sarcastic.
- The user may share YouTube clips of Jarvis. Claude cannot watch video, so treat them as listening references for the Cartesia voice audition (D-05), not as research input.
- Generated mockups (ChatGPT, 2026-10-14) in `.planning/phases/01-always-on-voice-loop/refs/`:
  - `snow-vision-ascii-orb-dashboard.png`: approved orb look. Ignore its sidebar, search bar with Ctrl+Space hotkey, typed input box and message actions; those are not in scope.
  - `snow-vision-mini-orb-desktop.png`: approved mini widget (orb plus caption pill, top-right).
  - `snow-phase1-plain-orb-rejected.png`: layout and cards match the plan, but the plain glowing circle was rejected. Provider labels in it are wrong ("OpenAI").
- The orb must move with both voices from Phase 1, because that is the core of the look the user wants (see Deferred, Phase 6).

</specifics>

<deferred>
## Deferred Ideas

- **Phase 6 visual (locked by the user):** the orb moves and reacts as Snow speaks and as the user speaks, exactly like the Age of Ultron Jarvis. No ambient or background lighting effects; all effects live on the orb itself. Full dashboard when open, mini corner form when minimized (D-11).
- **Always-listening mode (Phase 2 or later):** an optional mode with no wake word, which reacts only to the verified user's voice when the user addresses Snow. Needs speaker verification first.
- **Push-to-talk hotkey:** removed from v1 by user decision (D-07). Revisit only if the wake word proves unreliable.

</deferred>

---

*Phase: 01-always-on-voice-loop*
*Context gathered: 2026-10-14*
