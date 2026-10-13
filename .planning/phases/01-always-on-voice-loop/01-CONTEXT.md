# Phase 1: Always-On Voice Loop - Context

**Gathered:** 2026-10-14
**Status:** Ready for planning

<domain>
## Phase Boundary

The user wakes Snow by saying "Hey Snow", talks naturally, and hears a fast, LLM-written, emotion-voiced reply in a Jarvis-like voice, with a local fallback voice when Cartesia is unavailable. Underneath: the event bus and durable event log, a supervisor that restarts crashed subsystems, autostart at Windows logon, secrets in Windows Credential Manager, config-swappable LLM roles, and typed/linted/tested CI.

The HUD in this phase is light: a full dashboard window (presence orb, live transcript, subsystem health, mute state) and a minimized mini indicator. No coding agents, no PC control, no ASCII orb (Phase 6), no speaker verification (Phase 2).

Requirements: CORE-01..04, VOIC-01, VOIC-03..06, VOIC-08, SPCH-01..04, HUD-03, QUAL-01, QUAL-03, SAFE-09. VOIC-02 is removed from this phase by user decision (see D-07).

</domain>

<decisions>
## Implementation Decisions

### Persona and replies
- **D-01:** Snow talks like J.A.R.V.I.S. from the MCU (Paul Bettany): composed, competent, natural tone, with dry, sarcastic British-style humor as the normal register. The user wants it "as close to Jarvis as possible".
- **D-02:** Snow addresses the user as "sir", used naturally, the way Jarvis does.
- **D-03:** Guardrail: sarcasm switches off when something goes wrong (errors, failures, unreachable services) or when the user sounds stressed. In those moments Snow is plain, direct and helpful.
- **D-04:** Reply length matches the question. The LLM judges per turn: banter gets a line, a real question gets a full answer. No fixed sentence cap, but the reply must still start speaking within about 1 second (SPCH-04), so stream sentence by sentence.
- **D-05:** Voice is a male Cartesia voice. The researcher shortlists male Cartesia voices that fit a calm, dry, British-leaning Jarvis character. The user picks the final voice in a short audition step. The voice ID lives in config.
- **D-06:** Vocal emotion is natural and mostly upbeat. The LLM picks one emotion per reply from a small validated set (for example content, calm, excited, sympathetic, neutral), defaulting to warm or content, with strong emotions only when the moment calls for it. Invalid values fall back to neutral.

### Conversation flow
- **D-07:** No push-to-talk key. The user wakes Snow by name only, like Tony calling Jarvis. VOIC-02 (push-to-talk hotkey) is dropped from Phase 1. This changes ROADMAP.md success criterion 1 ("or pressing the push-to-talk hotkey") and REQUIREMENTS.md VOIC-02. Update both before or during planning. A developer-only test input (for example, injecting a recorded WAV or typed text into the pipeline for tests and CI) is allowed, but it is not a user-facing feature. — **Reversibility:** reversible — adding a hotkey later is a small, isolated input source on the event bus.
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
- **D-12:** Presence element in Phase 1 is a simple voice-reactive orb: a basic glowing circle that moves with the user's voice and with Snow's voice, colored by state (sleeping, listening, thinking, speaking, muted). The same element appears in the full and mini forms. The ASCII orb replaces it in Phase 6. The orb needs audio-level events on the bus for both mic input and TTS output.
- **D-13:** Mini indicator: top-right corner by default, draggable, position remembered, click-through so it never blocks clicks on the windows below, and clicking it opens the full dashboard. It shows only the orb while idle. While in conversation, a one-line caption of what Snow heard appears next to it, then fades.
- **D-14:** The full dashboard shows the transcript chat-style for the current conversation: the user's words updating live as they speak (VOIC-08), Snow's replies, newest at the bottom. The view clears when the conversation ends. Full history stays in the event log (the history view is Phase 6).
- **D-15:** The full dashboard also shows subsystem health (each subsystem up or down, QUAL-03), the mute or sleep state, and which voice is active (Cartesia or local) with remaining Cartesia credits.

### Fallback voice and privacy
- **D-16:** Use Cartesia for every reply until credits run out or Cartesia is unreachable. Then switch to the local voice (kokoro-onnx) automatically, and switch back when Cartesia works again.
- **D-17:** On the first reply after a switch to the local voice, Snow mentions it once in an LLM-written line, in character (for example, a dry remark about its "budget voice"). The HUD always shows the active voice and the remaining credits.
- **D-18:** The event log stores text transcripts (what the user said, what Snow replied) plus event metadata. Raw audio is never written to disk by the conversation pipeline. — **Reversibility:** reversible going forward — audio not saved is gone, but the setting can change for future turns.
- **D-19:** Transcripts are kept 30 days, then deleted automatically. The retention period is configurable.

### Claude's Discretion
- How "mute", "go to sleep" and "that's all" are recognized. Recommended: deterministic local phrase matching on the transcript, not an LLM call, so they work instantly and when the gateway is down.
- How the wake-alone acknowledgement stays LLM-written without adding latency (for example, a small pool of LLM-generated acknowledgements refreshed in the background). It must not be a hardcoded phrase (SPCH-01).
- Exact silence timeout inside the 30-60 second range, the orb's colors and motion, the dashboard layout and the mini indicator size.
- How the HUD gets credit balance and voice status from the core.
- Where enrollment or wake-word training recordings live, if any are needed. These are separate from the conversation log, created only by an explicit user action, and stored locally.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project scope and requirements
- `.planning/PROJECT.md` — vision, constraints, Key Decisions table (Electron shell, Experiential Labs gateway, dogfooding order)
- `.planning/REQUIREMENTS.md` — CORE-01..04, VOIC-01..06, VOIC-08, SPCH-01..04, HUD-03, QUAL-01, QUAL-03, SAFE-09 (note D-07: VOIC-02 removed from Phase 1)
- `.planning/ROADMAP.md` § "Phase 1: Always-On Voice Loop" — goal, success criteria, notes (criterion 1 must drop the push-to-talk wording per D-07)
- `.planning/STATE.md` — gateway details and open concerns (Cartesia free tier about 25 min/month)

### Stack and architecture research
- `.claude/CLAUDE.md` — technology stack with versions; user decisions of 2026-10-13 override research text (Electron, not Tauri; gateway roles; luna rejects `temperature`)
- `.planning/research/STACK.md` — library choices and versions (Pipecat, openWakeWord, faster-whisper, Cartesia, kokoro-onnx, keyring, structlog)
- `.planning/research/ARCHITECTURE.md` — ports and adapters, durable event log, snapshot-plus-delta, supervisor, loopback WebSocket with token
- `.planning/research/PITFALLS.md` — known failure modes (wake-word training, CUDA/cuDNN DLLs, latency, barge-in)
- `.planning/research/FEATURES.md` — table-stakes voice features
- `.planning/research/SUMMARY.md` — consolidated recommendations and phase research flags

### External
- Experiential Labs gateway docs: https://platform.experientiallabs.ai/docs and https://platform.experientiallabs.ai/llms.txt — base URL `https://api.experientiallabs.ai/v1`, model catalog at `https://api.experientiallabs.ai/api/models`

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
- The Phase 1 orb is a placeholder, but it must already move with both voices, because that is the core of the look the user wants (see Deferred, Phase 6).

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
