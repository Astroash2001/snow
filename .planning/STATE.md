---
gsd_state_version: "1.0"
current_phase: 01
current_phase_name: Always-On Voice Loop
status: executing
stopped_at: Phase 1 UI-SPEC approved
last_updated: "2026-10-26T13:19:55.741Z"
last_activity: 2026-10-19
last_activity_desc: Phase 01 execution started
state_head: cb6968a127e378ff4ac6fe769ed7e45d7fd8e5fc
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 33
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-13)

**Core value:** The user can do real, tangible work by voice alone: Snow understands the request, carries it out through coding agents and the PC, asks back by voice when it needs a decision, and visibly shows what it did.
**Current focus:** Phase 01 — Always-On Voice Loop

## Current Position

Phase: 01 (Always-On Voice Loop) — EXECUTING
Plan: 1 of 33
Status: Executing Phase 01
Last activity: 2026-10-19 - 01-30 Task 1 done (awaiting Colab training); 01-10 local CI files done (awaiting push approval)

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Python 3.12 core (voice, brain, policy, agent runner) + TypeScript/React HUD in an Electron shell
- [Roadmap]: Dogfooding order: Snow drives Claude Code by voice at the end of Phase 2, then helps build Phases 3-7
- [Roadmap]: Safety gate (deterministic tiers, fail-closed approvals, kill switch outside the LLM, speaker verification) ships in the same phase as agent control
- [Roadmap]: v1 is English only with headphones (speaker-mode echo cancellation is v2); Claude Code only, behind a generic adapter contract; phone channel is Snow's own Telegram bot over Tailscale
- [Roadmap]: The "what happened?" brief runs only on explicit request

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1]: LLM layer decided 2026-10-14: per-role fallback chains (brain, fast, vision) across Experiential Labs, Groq, Google AI Studio, NVIDIA NIM and OpenRouter free models; privacy routing keeps code and personal data off Google AI Studio free and OpenRouter free; keys only in Windows Credential Manager (no .env). Exact model IDs, streaming, tool calling and vision to confirm via GET /models in the Phase 1 spike; Groq vs deepseek-v4-flash latency test picks the fast primary. See 01-CONTEXT.md D-20 to D-30
- [Phase 2/3]: Two dogfooding mechanics have no REQ-ID yet (stable running copy separate from the dev copy; self-upgrade only on approval with rollback); confirm and add before planning Phase 2
- [Phase 2]: Claude Code account is borrowed; confirm Agent SDK headless permission behaviour and account terms
- [Phase 5]: WhatsApp Desktop automation carries account-ban risk; confirm the target app before planning
- [General]: Cartesia free tier is 20K credits/month (about 27 min, no cloning); by design (Phase 1 D-33) Pocket TTS carries everyday speech and Cartesia only big moments

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 261018-glq | Real echo cancellation (livekit APM) so Snow works on laptop speakers and mic | 2026-10-18 | 10b4e0d | [261018-glq-real-echo-cancellation-livekit-apm-so-sn](./quick/261018-glq-real-echo-cancellation-livekit-apm-so-sn/) |
| 2 | Hardware echo test: raw vs clean diagnostics while the user talks | 2026-10-18 | 561490a | — |
| 3 | Strip emotion tags repeated mid-reply | 2026-10-18 | 5acacd1 | — |
| 261018-pvq | Voice robustness batch: priority, playout rebuffer, sleep-aware supervisor, Groq STT filter | 2026-10-19 | 17d6386 | [261018-pvq-voice-robustness-batch-priority-playout-](./quick/261018-pvq-voice-robustness-batch-priority-playout-/) |
| 261019-3g3 | Jarvis voice: calm persona, paul voice, polish stage (48k soxr, loudness, pauses, EQ, reverb) | 2026-10-19 | cd7337d | [261019-3g3-jarvis-voice-calm-persona-paul-voice-pol](./quick/261019-3g3-jarvis-voice-calm-persona-paul-voice-pol/) |
| 261026-nvh | Per-model cooldown: a model timeout no longer skips its provider's other models (UAT G-01-16) | 2026-10-26 | cb6968a | [261026-nvh-per-model-cooldown-so-one-slow-model-doe](./quick/261026-nvh-per-model-cooldown-so-one-slow-model-doe/) |

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

## Session Continuity

Last session: 2026-10-14T11:51:02.750Z
Stopped at: Phase 1 UI-SPEC approved
Resume file: .planning/phases/01-always-on-voice-loop/01-UI-SPEC.md
