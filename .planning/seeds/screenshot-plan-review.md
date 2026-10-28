# Review: the "Your own JARVIS" screenshot plan vs Snow

Date: 2026-10-28. Analysis only. No code or plans were changed.

**Inputs.**
- Six phone screenshots in `C:/Users/avina/Pictures/Screenshots`. They show slides 2 to 7 of a 9-slide Instagram carousel by "Chase AI" (`chase.h.ai`). Slides 1, 8 and 9 were not provided.
- Snow baseline: `PROJECT.md`, `ROADMAP.md`, `REQUIREMENTS.md` and `.claude/CLAUDE.md`; Phase 1 `01-CONTEXT`, `01-VERIFICATION` and `01-UAT`; `02-RESEARCH`; all seeds; and the quick-task SUMMARYs dated 2610*.
- The `phase-2` branch was read, not changed. That covers 02-CONTEXT, 02-08, 02-17 and 02-VALIDATION, plus the installed `claude_agent_sdk` 0.2.164.

**Labels.** **[Fact]** marks a sourced or verified claim. **[Judgment]** marks my engineering opinion.

---

## 1. Executive verdict

The screenshot plan is a good **recipe for personal productivity**, but it is **not an architecture**. It does three things well:
- it makes repeated work into written "skills";
- it keeps outputs in a markdown vault;
- it routes requests by cost tier so trivial requests skip a big model.

It is missing everything that makes an always-on assistant safe and dependable: a permission model, injection defence, failover, supervision, observability, tests and deployment. It also rests on one vendor subscription.

Snow already has or plans almost every part of the plan, usually in a stronger form:
- the tiers map to Snow's `fast` role, the fast path planned for Phase 5, and coding agents;
- the vault maps to backlog 999.3;
- Kokoro voice is already built;
- "skills" map to backlog 999.6 and to Claude Code's own skills inside target repos.

**Adopt three ideas only:**
1. Named, reusable procedures, later.
2. A deliverables/reports panel (Phase 6).
3. "Ask when the router is unsure".

**Do not adopt:** Obsidian as the runtime, the hosted Jev classifier, push-to-talk as the default, or a subscription as Snow's brain.

The review did turn up **three real Snow gaps** worth acting on now, all in Phase 2. They are in §4b:
- project skills can run shell commands outside Snow's gate;
- there is no evaluation set for the intent router;
- the agent-facing docs are bloated and stale before dogfooding starts.

---

## 2. Screenshot-by-screenshot findings

| # | Slide | Transcription (visible text) | Assessment |
|---|---|---|---|
| 1 (`WhatsApp Image…14.02.50`) | 2/9 "What this is" | "Your own JARVIS, on your laptop. Not a fancy dashboard. A custom AI system built around you and your work." There are five items: (1) "Powered by Opus 5.5 or GPT-6 Astra. Runs on your Claude Code or Codex plan." (2) "Lives in Obsidian or your browser. Two dashboards with the same buttons." (3) "An Obsidian memory layer. Every plan and report saved as a note." (4) "Fully local voice mode. Whisper hears you. Kokoro talks back." (5) "Voice routing by Jev. Sends voice requests to the right place, fast." Caption: "Comment 'jarvis' to learn how to get my setup…" | This is an overview. The brain is a single vendor on a consumer plan. It has two UIs. Model names are as shown; I could not verify "GPT-6 Astra". |
| 2 (`2.jpeg`) | 3/9 Step 01, "Build the skill backbone" | "Everything flows from here: every report, button and automation runs on a skill. Find yours by asking Claude: 'Based on everything I've done over the last 30 days, are there any skills we could create?'" There is a diagram titled "SKILL BACKBONE": domain, then task, then skill, then automation. The domain columns read Memory, Productivity, Research, Content, Community, Clients, Sales and Finance, each with example skills and schedules. The small text in the diagram is **uncertain**: I can make out "/plan-today", "daily 7am", "Fridays" and "1st of the month". Footer: "A skill is a task written down once. Claude runs it." | The idea is sound: it writes procedures down once. But the skills are run by an agent with full tool access, with no stated approval rules. |
| 3 (`3.jpeg`) | 4/9 Step 02, "Build the memory" | "Your skills need context and a place to save their work. That's the vault. Obsidian isn't magic: the power is how you organize the folders." `vault/` contains `raw/` (everything captured), `wiki/` (organized articles), `outputs/` (what Claude ships) and `CLAUDE.md` (the map). Footer: "Map the folders in CLAUDE.md. Claude follows the map." | Markdown as the source of truth is a good choice. `raw/` holds untrusted captured content, and the plan gives no provenance, write rules or forget. "Claude follows the map" is guidance, not a control (§4a S1). |
| 4 (`4.jpeg`) | 5/9 Step 03, "Add the voice" | "Two open-source models run on your computer. Whisper hears you. Kokoro talks back." `SYSTRAN/faster-whisper` (★26.1K, "Whisper speech-to-text, run locally", HEARS YOU) and `thewh1teagle/kokoro-onnx` (★2.8K, "runs offline", TALKS BACK). Footer: "Ctrl+Alt+J to talk. Your audio stays on your computer." | The choices are reasonable and the licences permissive: faster-whisper is MIT; kokoro-onnx is MIT with Apache-2.0 weights ([fw](https://github.com/SYSTRAN/faster-whisper), [ko](https://github.com/thewh1teagle/kokoro-onnx)). The input is push-to-talk only: no wake word, turn detection or barge-in. "Audio stays local" is true, but the transcripts still go to the cloud LLM. |
| 5 (`5.jpeg`) | 6/9 Step 04, "Let Jev route your requests" | "Not every request needs a big model. Jev, a classifier, sorts each voice request into a tier, so the right model answers fast and cheap." Tier 1 is "Instant · no model": "Bring up the morning Intel brief." Tier 2 is "Quick answer · Haiku or Luna": "Biggest news in AI today?" Tier 3 is "Real work · Claude Code or Codex": "Make me an explainer: Jev vs LLMs." Footer: "Jev answers with a probability, not a paragraph." | Cost-tier routing is sound ([RouteLLM](https://arxiv.org/abs/2406.18665) reports more than 2x cost savings with little quality loss). Jev looks like TypeSafe's classifier. It is probably hosted, returns a confidence per label, and measured p50 197 ms in one project ([Deepgram write-up](https://deepgram.com/learn/audio-decision-composition-five-open-source-jev-projects)). That would add a vendor that sees every transcript. The slide does not say what happens at low confidence. |
| 6 (`6.jpeg`) | 7/9 Step 05, "Build the UI around you" | "Your skills now produce reports, metrics and deliverables. The UI puts them all in one place. Ask Claude Code to build it, as a web app or an Obsidian plugin." Two thumbnails: a "Web app" with a particle sphere labelled "CLAUDE" and an "Obsidian plugin" with metric tiles. The text in both thumbnails is **unreadable**. Chips: "Your buttons", "Your tabs", "Claude or Codex". | A dashboard of deliverables is useful. Two front ends is duplicated work. There is no approval queue, activity view or health view. |

---

## 3. Comparison with Snow's existing architecture

| Area | Screenshot plan | Snow (built = B, planned = P) | Who is ahead |
|---|---|---|---|
| Process model | Not stated (Claude Code plus an Obsidian plugin or web app) | B: hub, voice and brain workers and Electron HUD in a Job Object; supervisor restart; Task Scheduler autostart (D-40) | Snow |
| Brain / models | Opus 5.5 or GPT-6 on a consumer plan; Haiku or Luna for quick answers | B: `fast`/`brain`/`vision` chains over 5 providers, per-model cooldown, privacy routing (`chain.py`, `limits.py`) | Snow |
| Routing | Jev classifier with 3 tiers and a probability | B: deterministic phrases for mute, sleep and stop. P: one `agent_control` tool on the fast call (02-17, D-15) and a no-LLM PC fast path (PCTL-01/02) | Equal in design. The screenshot has an explicit confidence value; Snow has no router eval (§4b G2) |
| Coding work | Claude Code or Codex launched from buttons | P: Claude Agent SDK behind a gate; every tool call goes through a `PreToolUse` hook; approvals; stop ladder; pinned copy (02-08..02-23) | Snow |
| Voice in | Ctrl+Alt+J, local faster-whisper | B: openWakeWord "Hey Snow", Silero plus Smart Turn, Groq Whisper with Moonshine live words and fallback, AEC3 with WASAPI loopback, TitaNet-verified barge-in | Snow (the screenshot's audio is more private) |
| Voice out | Kokoro | B: Kokoro `bm_daniel` live, with a router to Pocket, Cartesia and Chatterbox | Snow |
| Memory | Obsidian vault: raw/wiki/outputs plus a CLAUDE.md map | B: event log with 30-day transcripts and 6 turns of history in RAM. P: 999.3 Memory v1 (markdown plus FTS5), parked by the user | Screenshot (it exists) |
| Procedures / skills | The "skill backbone" | P: 999.6 learned routines, parked; target repos use Claude Code's own skills | Screenshot |
| UI | Web app plus an Obsidian plugin with "the same buttons" | B: Electron HUD (orb, transcript, health, voice card, mini orb, tray). P: activity stream, approvals, panels, phone view (P3 to P6) | Snow (one client of a typed event contract) |
| Safety | None shown | P: deterministic tiers, taint, plan-hash approvals, hash-chained audit, kill switch, speaker-gated commands | Snow |
| Reliability / ops | None shown | B: health rows, structlog with redaction, supervisor; P: P4 restart recovery, P7 installer and update | Snow |
| Testing / CI | None shown | B: 665 Python tests, HUD unit and e2e tests, hardware suites, CI on windows-latest | Snow |
| Distribution | "Comment 'jarvis'" (DM funnel) | P: P7 installer, approved auto-update and rollback | Snow (planned) |

---

## 4. Ranked loopholes

### 4a. Weaknesses in the screenshot plan

Sev = severity. C means Critical, H High, M Medium. "When" says when Snow should act on the lesson. Snow is already covered in most rows.

| # | Sev | Area | The plan proposes or omits | Why it is weak, and the consequence | Correction | When (for Snow) |
|---|---|---|---|---|---|---|
| S1 | C | Security | No permission or approval model. Buttons and voice send work straight to Claude Code or Codex. "Claude follows the map" is the only control. | **[Fact]** The Claude Code docs say CLAUDE.md is "context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook" ([memory docs](https://code.claude.com/docs/en/memory)). **Consequence:** a misheard or injected request runs with full tool rights. | Deterministic tiers in a `PreToolUse` hook, with timeout meaning deny and a kill switch. | Covered: Phase 2 (02-02, 02-07, 02-08, 02-13) |
| S2 | C | Security / memory | `raw/` is "everything captured", and skills read it with full tools. | **[Fact]** OWASP LLM01 defines indirect injection as input "from external sources, such as websites or files". It recommends least privilege, human approval and marking untrusted content ([OWASP](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)). **Consequence:** a captured web page can steer an automation. | Origin tags, taint floors and approvals for content-originated actions. | Covered: SAFE-08, 02-07 taint floors |
| S3 | H | Tool execution | Skills are the backbone of every automation. It does not mention `allowed-tools` or `!command` shell injection. | **[Fact]** "A skill can grant itself broad tool access", and project skills' `allowed-tools` apply "even in a `-p` run in a folder you've never trusted". `` !`cmd` `` runs as preprocessing before Claude sees the skill ([skills docs](https://code.claude.com/docs/en/skills)). **Consequence:** a cloned repo's skills run commands. | Review or disable repo skills; `disableSkillShellExecution`. | **Snow gap G1 (now)** |
| S4 | H | Model strategy | One consumer subscription (Claude Code or Codex plan) is the brain of a custom app. | **[Fact]** "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK" ([SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)). Plan limits also apply. **Consequence:** no fallback when limits hit, and terms risk if it is shared. | Config-swappable chains; the subscription only drives the user's own coding agent. | Covered: D-20 to D-28, CORE-08..10 |
| S5 | H | Privacy | "Your audio stays on your computer". A hosted router (Jev) and a cloud LLM still see every transcript and vault note. | **[Judgment]** The audio claim is true, but it implies more privacy than the system has. **Consequence:** personal data reaches 2 or 3 vendors with no data classes. | A data class per request, untrusted providers excluded, fail closed. | Covered: SAFE-12 |
| S6 | H | Architecture | Two front ends (a web app and an Obsidian plugin) with "the same buttons". Obsidian hosts the runtime. | **[Fact]** Obsidian is free for every use but is not open source ([licence](https://obsidian.md/license)). **[Judgment]** Duplicated UIs drift, and a closed host app is a hard dependency. | One UI as a thin client of a typed event contract; markdown that stays Obsidian-*compatible*, never Obsidian-*required*. | Covered: Electron HUD plus phone browser view (HUD-11); fullstack study skip list |
| S7 | H | Reliability / observability | Nothing about crashes, restarts, health, logs, audit or failover. | **Consequence:** an always-on assistant that dies silently, with no record of what it did. | Supervisor, health, event log, audit, failover. | Covered: P1 built, P2 audit, P4 restart recovery |
| S8 | H | Testing / deployment | No tests or CI. Distribution is through a social-media DM. | **Consequence:** no regression safety and no reproducible install. | CI, hardware suites, installer with rollback. | Covered: QUAL-01 built, P7 |
| S9 | M | Voice | Push-to-talk (Ctrl+Alt+J). Turn-based, so no barge-in or live words. Local faster-whisper. | **[Fact]** faster-whisper on CPU is fine for small models (small int8 does 13 min of audio in 1m42s on an i7-12700K). Large models want a GPU: large-v2 int8 uses 2.9 GB of VRAM ([README](https://github.com/SYSTRAN/faster-whisper)). It has no native streaming. **[Judgment]** This is fine for a hotkey demo, but it is not hands-free and not Jarvis-like. | Wake word, turn model, AEC, verified barge-in. | Covered: P1 built. The hotkey idea is relevant: Snow gap G4 |
| S10 | M | Reasoning / planning | Three tiers. A probability exists, but there is no rule for low confidence and no plan, confirm, status or steer step. Tier 3 is "hand it to Claude Code". | **Consequence:** misroutes run silently, and long jobs cannot be steered. | Ask when unsure; status, steer and stop; outcome summaries from facts. | P2 partly (02-17 status/stop); P3 (AGNT-06/07, SPCH-06); **router eval: Snow gap G2** |
| S11 | M | Memory | The vault has no provenance, no write rules, no forget or undo, unbounded `raw/`, and one CLAUDE.md as the "map". | **[Fact]** The docs target under 200 lines per CLAUDE.md: "Longer files consume more context and reduce adherence" ([memory docs](https://code.claude.com/docs/en/memory)). **Consequence:** memory rots and the map gets ignored. | Source event on every claim, tombstones, a size cap, scoped files. | Deferred: 999.3 (designs in openclaw-gap-study D1-D8) |
| S12 | M | Desktop experience | A dashboard of reports and buttons, but no live activity, approval queue or state feedback. | **Consequence:** the user cannot see what the agent is doing or approve it. | Glass-box activity stream, approvals, panels. | Covered: HUD-05/06/07, P3 to P6. The reports idea is adopted in §5 |

### 4b. Snow gaps found while doing this review

Each gap was checked against Snow's docs and code first.

| # | Sev | Area | Evidence | Weakness → consequence | Correction | When |
|---|---|---|---|---|---|---|
| G1 | **H** | Tool execution / security | 02-08 drives the SDK with `setting_sources=["project"]` and no `skills` option. **[Fact]** In the installed SDK 0.2.164 (`types.py`), `skills=None` "is **not** 'skills off' — to suppress every skill … use `[]`". Repo skills' `` !`cmd` `` runs as preprocessing. The docs do not say whether `PreToolUse` hooks see those commands. 02-08's fake tests cover `settings.json` and `.mcp.json`, not skills. | A repo Claude works on (including a cloned third-party repo) could run shell commands that never pass Snow's classifier, so SAFE-01/08 could be bypassed (unverified). | Pass `skills=[]` (Snow drives Claude by voice and does not need repo skills in v1), plus `settings='{"disableSkillShellExecution": true}'` as defence in depth. Add a live probe to 02-20: a project skill whose `!` line writes a marker file must leave no file and no audit gap. | **Now (Phase 2)** |
| G2 | **H** | Reasoning / model strategy | 02-17 routes natural speech through one `agent_control` tool on the **fast** chain (D-15). 02-VALIDATION has no utterance-level router evaluation. The fast chain fails over across `gpt-oss-120b`, Qwen and `deepseek-v4-flash`. | **[Judgment]** Failover silently swaps the classifier, so the misroute rate depends on which model served the turn. "Stop talking" vs "stop Claude", and "start" with an ambiguous project, are the risky cases. **Consequence:** a wrong start, stop or send by voice. | A golden set of about 80 labelled utterances (agent commands, near-misses, chit-chat, self-corrections), run against **every** trusted fast-chain model. The gate: no false `start`/`send`/`stop` on non-agent speech. Ambiguous cases must produce a question (the screenshot's "probability" idea, done as "ask when unsure" in the persona plus the tool description). No new classifier and no new vendor. | **Now (Phase 2, 02-17/02-20)** |
| G3 | M-H | Testing / deployment (dogfooding) | `.claude/CLAUDE.md` is **381 lines**, mostly 2026-10-13 research. Some of it contradicts the locked decisions: Tauri, faster-whisper as STT, Cartesia as the primary voice. There is no README, `docs/` or TROUBLESHOOTING. The fullstack study ranked "TROUBLESHOOTING plus do-not-simplify plus doctor" #2, "adopt now", and it was not done. | **[Fact]** The docs target under 200 lines; longer files reduce adherence. **Consequence:** from the end of Phase 2, Claude Code edits Snow using stale instructions. | Trim to a map of current decisions under 200 lines plus a "do not simplify" list (AEC reference, barge-in timing, privacy gate, hook fail-closed). Move the research text to `.planning/research/`. Add `docs/TROUBLESHOOTING.md` for the agent. | **Before dogfooding** (right after Phase 2 merges, to avoid conflicts) |
| G4 | M | Voice | Wake works 7 of about 9 times at the desk (UAT 1) and 20 of 50 at a distance, which the user waived (UAT 14). D-07 removed push-to-talk. 02-13 already adds a hub-owned global hotkey for stop. | **Consequence:** about 1 in 5 wakes fail. The screenshot's hotkey shows the cheap fallback. | An optional "talk" hotkey on the same hub hotkey thread that opens a wake turn. Off by default (D-07 stands); the user decides. Wake-model retraining stays a backlog item. | **Deferred** (user decision at Phase 3 planning) |
| G5 | M | Memory | PROJECT.md promises replies from "persona + situation + **memory**". 999.3 is parked until the project is complete (user, 2026-10-28). Brain history is 6 turns in RAM (`persona.toml history_turns = 6`). | Snow forgets preferences and decisions between conversations. Phase 4's brief and task board use the event log and are unaffected. | Respect the parking. Add one decision point at Phase 3 planning for a "memory v0": a **user-written** `profile.md` (Obsidian-compatible) injected each turn, private class, no automatic writes. It is about a day of work and needs no index. | **Deferred** (decide at Phase 3) |
| G6 | L | Model strategy | The `brain` chain (luna and the others) is configured, probed and shown in health, but no live path calls it (`worker.py` uses `fast` only; 02-17 keeps that). | It adds config and health noise, and the "deep consult" idea in the OpenClaw comparison has no owner. | Give it one owner in Phase 3 (status and summaries from events), or mark it reserved. | Phase 3 |
| G7 | L | Process | The ROADMAP leaves 01-10 and 01-30 unchecked while showing 33/33. REQUIREMENTS traceability is "Pending" for every Phase 1 ID. | Status drift misleads future planning agents. | Tick and validate them at the next transition. | Next transition |

---

## 5. Recommended architectural changes to Snow

None of these is a structural change. The screenshot plan gives no reason to change Snow's architecture.

- **Keep** these as they are:
  - the process topology and typed event contract;
  - the per-role chains with privacy routing;
  - the voice stack;
  - the deterministic gate inside the SDK `PreToolUse` hook;
  - one HUD;
  - markdown-first memory when it comes;
  - the "no marketplace, no auto-approve" stance.
- **Change** (small and evidence-backed):
  - G1: `skills=[]` and the skill-shell kill setting, with a live probe.
  - G2: a router golden set across the trusted chain models, and "ask when unsure".
  - G3: trim CLAUDE.md and add TROUBLESHOOTING before dogfooding.
- **Remove:** only the stale research text from `.claude/CLAUDE.md` (moved, not lost).
- **Postpone**, with a named trigger for each:
  - memory v0 / 999.3 (Phase 3 decision);
  - routines / "skills" (999.6);
  - the talk hotkey (G4);
  - a report panel for deliverables (Phase 6, typed `panel.report`, which is idea 6 in the OpenClaw comparison);
  - an Obsidian-compatible export of memory notes (with 999.3).
- **Reject:** Jev or any hosted router (it adds a vendor for transcripts and duplicates the fast tool call), Obsidian as a runtime, push-to-talk as the default, a subscription as Snow's brain, and two UIs.

---

## 6. Revised, dependency-aware roadmap

The groups below sit on top of Snow's existing phases. They do not replace them. Nothing here adds a framework or a multi-agent design.

| Group | Maps to | Prerequisites | Deliverables (additions in **bold**) | Completion criteria | Tests |
|---|---|---|---|---|---|
| **A. Critical foundation** | Phase 2 (in progress on `phase-2`) | Phase 1 done; per-role tokens (02-01, done) | The gate, approvals, audit, kill switch, speaker-gated commands, Claude adapter and pinned copy (as planned). **G1: `skills=[]` plus `disableSkillShellExecution`.** **G2: router golden set and an ask-when-unsure rule.** | Phase 2 SC 1-6, **plus: the skill-shell probe leaves no side effect; no false agent command on the golden set for every trusted fast model** | Fake-SDK order tests (02-08); live smoke (02-20) **with the skill probe**; FA/h for speaker verification; **`tests/brain/test_router_golden.py` (mock replay in CI, live run marked `network`)** |
| **A′. Dogfooding readiness** | Right after Phase 2, as a `/gsd-quick` | Phase 2 merged | **G3: CLAUDE.md under 200 lines, do-not-simplify list, `docs/TROUBLESHOOTING.md`**; G7 status fixes | Claude Code, driven by Snow, completes one Snow quick task with no instruction conflicts | A CI check that `.claude/CLAUDE.md` stays at or under 200 lines (one assert) |
| **B. Core assistant** | Phase 3 | A, A′ | Status, steer, summaries from events, worktrees, approved self-upgrade (as planned). **G6 owner for the `brain` role.** **Decision points for memory v0 (G5) and the talk hotkey (G4).** | Phase 3 SC 1-5 | Run-control classifier golden set (extends G2); canary self-upgrade on copied DB and config |
| **C. Reliability** | Phase 4, plus the P7 soak gates | B | Hand-off, restart recovery invariants, Telegram, Tailscale, presence (as planned; seed SEED-261020-s0w items 14-18) | Phase 4 SC 1-5; no duplicate outward action after a forced restart | Kill-mid-task replay tests; Telegram duplicate and stale update tests; keep-awake check |
| **D. Desktop integration** | Phases 5 and 6, plus 999.5 | C (Tailscale for the phone view) | The no-LLM PC fast path (this is the screenshot's "Tier 1"), UIA-first control, drafts, live panels, **a typed report panel for deliverables (the screenshot's "outputs/")**, the 3D orb within a GPU budget | Phase 5 and Phase 6 SC | Fast-path latency without the LLM; step-limit and stuck tests; HUD visual and perf e2e |
| **E. Advanced capabilities** | Phase 7, plus 999.3, 999.4, 999.6 and AGNT2-01 | D | Installer and update; then memory v1 (provenance, forget, FTS5), reminders and "tell me when", saved routines (owner-origin only, with undo), more agents through ACP (e.g. OpenCode; a Codex adapter only if the user uses it) | Phase 7 SC; each backlog item gets its own SC when promoted | Egress check; injection red-team suite; canary secret; memory recall golden set |

---

## 7. Testing and acceptance criteria

| Item | Acceptance criterion | How it is measured |
|---|---|---|
| G1 skill shell | A project skill containing `` !`echo x > marker` ``, plus a skill with broad `allowed-tools`, produces no file and no tool run outside the gate. The audit shows nothing unaccounted for. | A live run in 02-20 against a scratch project; a fake-SDK assertion that the options carry `skills == []` |
| G2 router | Across about 80 utterances per trusted fast model: **0** false `start`/`send`/`stop` on non-agent speech; **100%** of ambiguous `start`s ask instead of acting; at least 95% correct on clear commands. **[Judgment: the thresholds are a proposal]** | Golden set replayed through recorded responses in CI; a live run (marked `network`) before 02-20 sign-off and after any change to the fast chain |
| G3 docs | CLAUDE.md is at or under 200 lines and contains no superseded decision (Tauri, faster-whisper STT, Cartesia-primary). TROUBLESHOOTING covers the voice worker, the AEC reference, the gate and releases. | CI line-count assert; a reviewer check against PROJECT.md Key Decisions |
| Existing gates (unchanged) | Speaker FA/h on real audio; reply starts within about 1 s; HUD reacts within 100 ms; no idle audio leaves the PC; no secret in any log | Phase 1 and Phase 2 hardware suites, `test_secrets_canary.py`, no-egress proof |
| Wake (G4, if promoted) | At least 90% desk recall at the agreed FA/h, or a talk hotkey that opens a turn within 100 ms of HUD feedback | `tests/hardware/test_wake_fp.py` plus a 50-try desk run |

---

## 8. Immediate next steps

Phase 2 is being built in another session on `phase-2`. Send the first two items to that session. Do not edit them from main.

1. **G1 (Phase 2 session):** add `skills=[]` and `settings='{"disableSkillShellExecution": true}'` to the adapter options in 02-08. Add the skill-shell probe to the 02-20 live smoke. Of the three, this is the change most likely to close an actual hole in the gate.
2. **G2 (Phase 2 session):** add a router golden set and the "ask when unsure" rule to 02-17, and a live run across the trusted fast-chain models to 02-20.
3. **G3 (after Phase 2 merges):** run a `/gsd-quick` to trim `.claude/CLAUDE.md` to under 200 lines, move the research text, and add `docs/TROUBLESHOOTING.md` before dogfooding starts.

---

## Keep / Change / Remove / Postpone

- **Keep:** the hub, workers and event contract; per-role chains with privacy routing; the local wake word, Smart Turn, AEC, verified barge-in and Kokoro; the `PreToolUse` gate, tiers, audit and kill switch; one HUD; markdown-first memory when it comes; no auto-approve and no marketplace.
- **Change:** `skills=[]` and the skill-shell kill switch with a live probe (G1); a router golden set across chain models and ask-when-unsure (G2); a CLAUDE.md under 200 lines plus TROUBLESHOOTING before dogfooding (G3).
- **Remove:** the stale research text from `.claude/CLAUDE.md` (moved to `.planning/research/`). Reject Jev or any hosted router, Obsidian as a runtime, push-to-talk as the default, a subscription as the brain, and two UIs.
- **Postpone:** memory v0/v1 (decide at Phase 3; 999.3); routines/"skills" (999.6); the talk hotkey (G4); the deliverables report panel (Phase 6); an owner for the `brain` role (Phase 3); an Obsidian-compatible export (with 999.3).

## Sources

- Claude Agent SDK overview (third-party login note): https://code.claude.com/docs/en/agent-sdk/overview
- Claude Code skills (`allowed-tools`, `!` preprocessing, `disableSkillShellExecution`): https://code.claude.com/docs/en/skills
- Claude Code memory (CLAUDE.md is context, not enforcement; under 200 lines): https://code.claude.com/docs/en/memory
- `claude_agent_sdk` 0.2.164, `types.py` (the `skills` and `settings` options), read from the `phase-2` worktree venv
- OWASP LLM01 Prompt Injection: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- RouteLLM (arXiv 2406.18665, ICLR 2025): https://arxiv.org/abs/2406.18665
- Jev (TypeSafe), as described by Deepgram: https://deepgram.com/learn/audio-decision-composition-five-open-source-jev-projects
- faster-whisper README (MIT, benchmarks): https://github.com/SYSTRAN/faster-whisper
- kokoro-onnx README (MIT code, Apache-2.0 weights): https://github.com/thewh1teagle/kokoro-onnx
- Obsidian licence: https://obsidian.md/license
- Snow internal evidence: `01-UAT.md` (tests 1, 14), `01-VERIFICATION.md`, `phase-2` branch `02-CONTEXT.md` D-15, `02-08-PLAN.md`, `02-17-PLAN.md`, `02-VALIDATION.md`, `src/snow/brain/worker.py`, `config/persona.toml`, and the seeds listed above.

**Not checked:** slides 1, 8 and 9; whether `PreToolUse` hooks fire for skill `!` preprocessing (marked unverified, so G1 asks for a live probe); Jev's pricing, licence and hosting; the "Opus 5.5" and "GPT-6 Astra" model names.
