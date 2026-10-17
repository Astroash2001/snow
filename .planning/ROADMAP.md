# Roadmap: Snow

## Overview

Snow is built in the order that lets it help build itself. Phase 1 delivers an always-on voice loop (local wake phrase, cloud speech-to-text with a local fallback, tone-aware LLM reply, a light local everyday voice with Cartesia for big moments) on top of the event bus, supervisor, secrets store and CI that everything else depends on. Phase 2 puts Claude Code under voice control behind a deterministic safety gate (risk tiers, fail-closed approvals, a kill switch outside the LLM, speaker verification); from the end of Phase 2 the user drives Snow's own development through Snow, with a stable running copy building a separate dev copy. Phase 3 makes agent work steerable, honest and reversible (status, redirect, fact-based summaries, worktree isolation, accept or discard). Phase 4 lets the user walk away: background tasks, Snow's Telegram bot over Tailscale, presence-routed approvals and a task board. Phase 5 extends voice control to the whole PC. Phase 6 delivers the full glass-box HUD with the Jarvis-style ASCII network orb, the corner widget and the phone view. Phase 7 ships Snow as an installable, self-updating, private product.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Always-On Voice Loop** - Say "Hey Snow", talk naturally, hear a fast human reply; event bus, supervisor, secrets store and CI in place
- [ ] **Phase 2: Voice-Driven Claude Code with Safety Gate** - Start, instruct, answer and stop Claude Code by voice with risk tiers, fail-closed approvals, kill switch and speaker verification (Snow starts building Snow)
- [ ] **Phase 3: Steerable and Reviewable Agent Work** - Ask for status, redirect mid-task, hear fact-based summaries, follow the activity stream, accept or discard worktree-isolated changes
- [ ] **Phase 4: Hand-off & Phone** - Walk away while Snow works; Telegram notifications, one-tap approvals and replies over Tailscale; task board and on-request brief
- [ ] **Phase 5: PC Control** - Apps, windows, volume, media, files, API-less apps through screen control, drafts confirmed before sending, dev setup and git by voice
- [ ] **Phase 6: Glass-box HUD & Jarvis Body** - ASCII network-orb body with state visuals, spawn-on-demand dashboard, corner widget, phone HUD, history, silent mode, one design system
- [ ] **Phase 7: Production Release** - Installer with approved auto-update and rollback, clear failure explanations, verified privacy

## Phase Details

### Phase 1: Always-On Voice Loop

**Goal:** As a developer, I want to wake Snow by voice and talk with it naturally, so that I can speak to my PC instead of typing.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-08, CORE-09, CORE-10, VOIC-01, VOIC-03, VOIC-04, VOIC-05, VOIC-06, VOIC-08, SPCH-01, SPCH-02, SPCH-03, SPCH-04, HUD-03, QUAL-01, QUAL-03, SAFE-09, SAFE-12
**Success Criteria** (what must be TRUE):
  1. After the user logs in to Windows, Snow is already running; saying "Hey Snow" opens a turn (no key needed; Snow stays in the conversation until dismissed or silent) and the HUD shows "listening" within 100 ms, and no idle audio ever leaves the PC
  2. User speaks naturally, pausing mid-thought without being cut off, watches the live transcript on the HUD, and hears an LLM-written, emotion-voiced reply start within about 1 second; speaking over Snow stops it mid-sentence and cancels the rest of the reply
  3. Everyday replies use the local voice and big emotional moments use Cartesia; when Cartesia is unreachable or out of credits, Snow keeps talking in the local voice, and when cloud speech-to-text is unreachable it keeps hearing through the local model; changing the LLM provider, base URL, model or fallback order for the brain, fast and vision roles is a configuration edit with no code change; when a provider hits a limit or fails, Snow moves to the next one in the chain, says so briefly, and the HUD shows the active provider; personal data and code never go to providers marked untrusted; API keys live only in Windows Credential Manager and never appear in config files or logs
  4. Killing any running Snow subsystem (voice, brain, HUD) brings it back on its own; the HUD shows each subsystem as up or down and makes the hard-mute state unmistakable; every turn is recorded as typed events in the durable event log
  5. Every change to Snow's repository runs typed, linted, tested CI, and a failing change cannot be merged

**Plans:** 30/33 plans executed

Plans:
**Wave 1**
- [x] 01-01-PLAN.md — Walking skeleton A: uv project and pins, typed event contract, hub with SQLite event log and loopback WebSocket
- [x] 01-02-PLAN.md — Package legitimacy gate (human): pocket-tts, moonshine-voice, chatterbox-tts, livekit-wakeword

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 01-03-PLAN.md — Walking skeleton B: settings, keyring secrets, HubClient, brain answers through the first fast provider
- [x] 01-04-PLAN.md — Full event catalog, snapshot projection, mute persistence, role matrix, JSON Schema and golden samples
- [x] 01-05-PLAN.md — Synthetic speech fixtures (wake, pauses, commands, tone) with a wake-score check

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 01-06-PLAN.md — Walking skeleton C: `snow` CLI, hub entry with scrubbed worker launch, `snow run` and `snow dev say`
- [x] 01-07-PLAN.md — HUD toolchain: pinned project, lint/typecheck/test, generated contract types validated against samples
- [x] 01-08-PLAN.md — LLM fallback chains, privacy routing and provenance (CORE-04, 08, 10, SAFE-12)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 01-09-PLAN.md — Walking skeleton D: Electron dashboard connected to the hub showing the live conversation
- [ ] 01-10-PLAN.md — CI on windows-latest, private repo, secret and dependency scans, pre-push hook (QUAL-01)
- [x] 01-11-PLAN.md — `snow setup` keys in Credential Manager, redacting structured logs, canary proof (SAFE-09, QUAL-03)
- [x] 01-12-PLAN.md — Free-tier limits: header-driven cooldowns and daily counters (CORE-09)
- [x] 01-13-PLAN.md — Voice in: wake gate with pre-roll, TurnEngine, Groq speech-to-text, transcript to the brain
- [x] 01-14-PLAN.md — Always-on: supervisor with Job Object, health, Task Scheduler autostart, quit, retention (CORE-01, CORE-02)

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 01-15-PLAN.md — HUD reconnect banner, reducer tests, design tokens and renderer lockdown
- [x] 01-16-PLAN.md — Jarvis persona, emotion header, tone-aware replies, acknowledgement pool, silent all-providers-down path
- [x] 01-17-PLAN.md — Gateway probe and fast-role latency test (D-29, D-30)
- [x] 01-18-PLAN.md — Conversation flow: stay awake, wake-alone, pauses, end and sleep phrases, dev WAV input

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 01-19-PLAN.md — HUD ASCII network orb with levels, alert marker and latency proof (HUD-03)
- [x] 01-20-PLAN.md — Hard mute that closes the mic, startup mute rule, no-egress and no-disk proofs

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 01-21-PLAN.md — HUD transcript view, mute button, banners and empty states
- [x] 01-22-PLAN.md — Moonshine live words and local fallback with the STT router

**Wave 8** *(blocked on Wave 7 completion)*
- [x] 01-23-PLAN.md — HUD health panel, voice card, dashboard layout and visual baseline
- [x] 01-24-PLAN.md — Local tone detection attached to every turn

**Wave 9** *(blocked on Wave 8 completion)*
- [x] 01-25-PLAN.md — HUD mini indicator and two-form window model
- [x] 01-26-PLAN.md — Voice out: Pocket TTS everyday voice, chunking and playout

**Wave 10** *(blocked on Wave 9 completion)*
- [x] 01-27-PLAN.md — HUD tray, drag and remembered position, single instance, logon mode, quit
- [x] 01-28-PLAN.md — Voice router with mid-reply failover and kokoro fallback

**Wave 11** *(blocked on Wave 10 completion)*
- [x] 01-29-PLAN.md — Barge-in and per-turn latency, fake and real-hardware suites

**Wave 12** *(blocked on Wave 11 completion)*
- [ ] 01-30-PLAN.md — "Hey Snow" wake model: recipe, user training (human action), calibrated integration
- [x] 01-31-PLAN.md — Cartesia big moments with daily budget, credits and failback

**Wave 13** *(blocked on Wave 12 completion)*
- [x] 01-32-PLAN.md — Everyday voice moods, consent-tagged references and voice audition

**Wave 14** *(blocked on Wave 13 completion)*
- [ ] 01-33-PLAN.md — Chatterbox GPU voice in an isolated environment behind a power and VRAM policy

**UI hint**: yes

Notes:
- Event bus and durable event log come first; every later view (HUD, phone, history, audit) reads from it.
- Architecture (decided 2026-10-13): Python 3.12 core (voice, brain, policy, agent runner) and a TypeScript/React HUD in an Electron shell over a loopback WebSocket. The HUD in this phase is a light state, transcript and health view around a 2D ASCII network orb (decided 2026-10-14: no plain placeholder orb); Phase 6 upgrades the orb to the full 3D shader version.
- Early dependency, not a blocker: a short spike at the start calls `GET /models` on every configured provider (Experiential Labs, Groq, Google AI Studio, NVIDIA NIM, OpenRouter) to confirm exact model IDs, streaming, tool calling and vision support, and measures Groq `openai/gpt-oss-120b` against `deepseek-v4-flash` to pick the fast-role primary. Tool calling is needed by Phase 2 and vision by Phase 5. Missing keys skip that provider and never block the phase.
- English only and headphones assumed for v1, so barge-in does not need speaker-mode echo cancellation (deferred to v2).
- Research flag: wake-word training on Python 3.12, Groq speech-to-text latency and limits, Pocket TTS mood-clip emotion and speed on this CPU, Chatterbox VRAM, tone-detection accuracy, Cartesia timestamps and credit metering.

### Phase 2: Voice-Driven Claude Code with Safety Gate

**Goal:** As a developer, I want to drive Claude Code by voice behind a safety gate, so that Snow can safely help build Snow.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05, AGNT-09, VOIC-07, SAFE-01, SAFE-02, SAFE-03, SAFE-05, SAFE-06, SAFE-07, SAFE-08, SAFE-11, HUD-07, CORE-06
**Success Criteria** (what must be TRUE):
  1. User says "start Claude Code on <project>", gives it new instructions by voice while it runs, and stops it by voice; Claude Code is connected through Snow's generic adapter contract (start, send, stream events, question, permission, stop)
  2. When Claude Code asks a question, Snow speaks it and sends the user's spoken answer back; when it asks for permission, deterministic risk tiers decide (the LLM can raise a tier, never lower it), routine work proceeds without asking, and anything touching credentials, security settings, payments or irreversible deletion waits for explicit approval shown on the HUD with its context and reason
  3. An approval the user never answers times out to deny and stays pending on the HUD; saying "Snow, stop", pressing the global hotkey, or clicking the HUD stop button halts every agent and action at once, even while the LLM is hung
  4. Only the enrolled user's voice can start, steer or approve anything: a TV or another person is ignored and shown as ignored on the HUD, and when a secret is needed Snow pauses for the user to enter it directly instead of asking for it aloud
  5. Instructions found in files, agent output or tool results never trigger an action without approval, and every action and decision is written to an append-only, redacted audit log kept separate from the display history
  6. Snow runs from a pinned, versioned copy outside any repository it works on; when Claude Code works on Snow's own repo, the running Snow is never modified

**Plans:** TBD
**UI hint**: yes

Notes:
- Build order inside the phase: speaker verification, the deterministic policy gate and the durable approval object come before the Claude Code adapter is wired, so no voice-triggered action ever runs ungated.
- The kill switch runs outside the LLM path (its own listener, hotkey hook and supervisor signal).
- Claude Code only in v1, behind the generic adapter contract. Snow spawns the user's own `claude` and never reads its tokens. Research flag: Claude Agent SDK headless permission and question behaviour, and the terms of the borrowed Claude Code account.
- Research flag: short-utterance speaker verification accuracy, measured as false accepts per hour on real audio.
- CORE-06 (added 2026-10-13 at roadmap approval): stable running copy separate from the dev repository — the first half of safe self-building.
- Dogfooding starts when this phase is verified: Phases 3 to 7 are built by driving Claude Code through Snow.

### Phase 3: Steerable and Reviewable Agent Work

**Goal:** As a developer, I want to steer and review agent work in isolated worktrees, so that only changes I accept reach my code.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** AGNT-06, AGNT-07, AGNT-08, VOIC-10, SPCH-05, SPCH-06, HAND-06, HAND-07, HUD-05, HUD-08, CORE-07
**Success Criteria** (what must be TRUE):
  1. User asks "what's it doing?" mid-task and hears a short status; saying "stop, use Postgres instead" (even phrased as "use Postgres, no wait, SQLite") is cleaned into one intent and the agent continues in the new direction
  2. The HUD shows a live activity stream of what Snow heard, understood and planned, each action, and each result, and every risk notice shows the reason behind it
  3. When the agent finishes, Snow gives a short, outcome-first spoken summary built only from recorded events, never reads code, diffs or logs aloud, and shows the changes on screen
  4. Every coding task runs in its own git worktree, leaving the user's main code untouched; one voice command accepts a task's changes into the main code or discards them entirely
  5. After the user approves, Snow switches its running copy to a newly accepted build of itself; if the new build fails its health check, Snow rolls back to the previous copy automatically

**Plans:** TBD
**UI hint**: yes

Notes:
- CORE-07 (added 2026-10-13 at roadmap approval): approved self-upgrade with automatic rollback — the second half of safe self-building.
- The full set of live panels (terminal output, diffs, drafts, the app being controlled) is completed in Phase 5, when every panel type has something to show; this phase shows changes through the finished-task view.

### Phase 4: Hand-off & Phone

**Goal:** As a developer, I want to hand off a task and walk away, so that Snow keeps working and reaches me on my phone.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** HAND-01, HAND-02, HAND-03, HAND-04, HAND-05, HAND-08, HAND-09, CORE-05, SAFE-04, SAFE-10
**Success Criteria** (what must be TRUE):
  1. User hands off a task and walks away; Snow keeps working in the background, and after a Snow or PC restart in-progress tasks resume or are reported instead of being lost
  2. When a task finishes, fails or needs a decision, the user's phone gets a message from Snow's own Telegram bot whose first line says what, where and why it is risky, with a link to full detail
  3. From the phone, the user approves or denies with one tap, or answers a question in free text, and the work continues; replies are accepted only from the user's authenticated account, and phone-to-PC traffic runs only over Tailscale
  4. Risk notices and approval requests come by voice and HUD while the user is at the PC, and go to the phone when the user is away or the PC is locked
  5. Back at the PC, the HUD task board lists every task as done, in progress or waiting on the user, and asking "what happened?" returns a short brief of everything done while away; Snow never starts the brief on its own

**Plans:** TBD
**UI hint**: yes

Notes:
- Reuses the Phase 2 approval object unchanged; the phone is one more channel that resolves it, and an unanswered request still times out to deny.
- Telegram is not end-to-end encrypted, so messages stay minimal and full detail opens only over Tailscale; replies are bound to the allow-listed numeric Telegram user ID.
- Unknown presence is treated as away.

### Phase 5: PC Control

**Goal:** As a developer, I want to control my apps, settings and files by voice, so that I can run my whole PC without a keyboard.
**Mode:** mvp
**Depends on:** Phase 4
**Requirements:** PCTL-01, PCTL-02, PCTL-03, PCTL-04, PCTL-05, PCTL-06, PCTL-07, PCTL-08, HUD-06
**Success Criteria** (what must be TRUE):
  1. User opens, closes and switches apps and windows, sets volume and brightness, controls media, and opens files and folders by voice, and these commands run on a fast path that does not wait on the LLM
  2. User asks Snow to do something in an app with no API (for example WhatsApp Desktop) and Snow completes it by reading the screen, clicking and typing, trying the app's API or CLI first, then the accessibility tree, and screenshot-and-click last
  3. When screen control gets stuck or reaches its step limit, Snow stops and tells the user what blocked it instead of looping
  4. Before any message is sent on the user's behalf, the draft is shown and read back, and nothing goes out until the user confirms; live panels show terminal output, diffs, drafts and the app being controlled
  5. User sets up dev tools and runs git and GitHub operations by voice, carried out through the coding agent or the shell under the same risk tiers

**Plans:** TBD
**UI hint**: yes

Notes:
- Screen and web content is data, not instructions: the Phase 2 rule that any action originating from such content needs approval applies to every step here.
- Research flag: UIPI and elevated windows, DPI and focus behaviour, the vision fallback chain decided 2026-10-14 (luna, Gemini Flash, qwen3.8-27b; support confirmed in the Phase 1 spike), and injection defence for screen reading.
- WhatsApp Desktop is the requirement's own example, but research flags account-ban risk for WhatsApp automation; confirm the target app during phase discussion.

### Phase 6: Glass-box HUD & Jarvis Body

**Goal:** As a developer, I want to watch Snow's glyph-orb HUD on desktop, corner and phone, so that I see what it is doing at a glance.
**Mode:** mvp
**Depends on:** Phase 4
**Requirements:** HUD-01, HUD-02, HUD-04, HUD-09, HUD-10, HUD-11, HUD-12, SPCH-07, VOIC-09, QUAL-06
**Success Criteria** (what must be TRUE):
  1. Snow's body is a glowing, Age of Ultron style network orb of nodes and lines drawn from ASCII characters and numbers with soft neon accents, and it visibly changes between idle, listening, thinking, acting, speaking and alert
  2. The dashboard starts empty around the body; a space appears only when a task, agent, panel or approval spawns and closes when it is done, all in one design system with consistent motion, type and color
  3. While the orb animates, speech recognition does not slow down: the HUD stays inside a fixed GPU budget and lowers its visual detail first
  4. User can shrink the HUD to an always-on-top corner widget showing Snow's state and current action, open the same live HUD in the Android phone browser over Tailscale, and scroll and search the day's history
  5. In silent mode the user follows everything on the HUD with no voice output, and can type commands into the HUD command bar when speaking is not possible

**Plans:** TBD
**UI hint**: yes

Notes:
- The GPU budget and detail fallback land before any heavy shader work inside this phase, measured on the RTX 4050 with speech recognition running.
- Depends on Phase 4 for Tailscale access to the phone view; it can run alongside Phase 5 if desired. Earlier phases' functional views are restyled, not rebuilt, because the HUD is a client of the event log.
- Time-box the orb art; the orb style is an abstract Jarvis-style network, not a human form.

### Phase 7: Production Release

**Goal:** As a developer, I want to install and update Snow like a real product, so that it runs reliably, privately and explains failures.
**Mode:** mvp
**Depends on:** Phase 6
**Requirements:** QUAL-02, QUAL-04, QUAL-05
**Success Criteria** (what must be TRUE):
  1. User installs a versioned Snow release from an installer on a clean Windows account, and Snow starts at login with voice, brain, agents and HUD working
  2. New releases arrive through auto-update and apply only after the user approves; a release that fails its health check rolls back to the previous version
  3. When anything fails, Snow says plainly what went wrong, by voice and on the HUD, and the exact cause is recorded in the logs
  4. Personal data (audio, transcripts, history, memory, secrets) stays on the PC except where the user approved it; an egress check shows that only what each feature needs leaves the machine (conversation audio to Groq speech-to-text, LLM providers within their privacy-routing limits, Cartesia, minimal Telegram messages)

**Plans:** TBD

Notes:
- Research flag: packaging the CUDA-enabled Python core and signing updates.
- Release gates: soak test across sleep, lock and headphone changes; port scan showing only loopback and Tailscale listeners; prompt-injection red-team suite; canary-secret test.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 (Phase 6 may overlap Phase 5)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Always-On Voice Loop | 30/33 | In Progress | - |
| 2. Voice-Driven Claude Code with Safety Gate | 0/TBD | Not started | - |
| 3. Steerable and Reviewable Agent Work | 0/TBD | Not started | - |
| 4. Hand-off & Phone | 0/TBD | Not started | - |
| 5. PC Control | 0/TBD | Not started | - |
| 6. Glass-box HUD & Jarvis Body | 0/TBD | Not started | - |
| 7. Production Release | 0/TBD | Not started | - |
