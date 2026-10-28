# Snow vs OpenClaw: broad product comparison

Date: 2026-10-28. Ideas only. No code was copied, and nothing from OpenClaw was installed or run.

**Target.** github.com/openclaw/openclaw. I read it through `gh api` (metadata, releases, commits, security advisories) and a sparse, depth-1 clone of `docs/` and `apps/` at `c94a96b` (2026-10-28) in a temp directory outside the Snow repo. The clone was deleted afterwards.

**Licence.** MIT ("Copyright (c) 2026 OpenClaw Foundation"). Copying would be legal if the notice were kept, but this study takes ideas only.

**Relation to earlier work.** [openclaw-gap-study.md](./openclaw-gap-study.md) (2026-10-19) already covers OpenClaw's agent control, approvals, Telegram, recovery, worktrees, memory mechanics and security incidents. Its items are cited here by id (A1-F4) and are not repeated. This file is the product-level comparison, plus what changed after 2026-10-19.

---

## 1. What OpenClaw is today

| Aspect | Today (2026-10-28) |
|---|---|
| **Purpose** | "Your assistant, on your devices, in your chats." A self-hosted personal (or team) AI agent that you message from chat apps. It is chat-first, not voice-first. Stewarded by the OpenClaw Foundation (a 501(c)(3)), with no paid tier. OpenAI is a donor. (`README.md`) |
| **Architecture** | One **Gateway** (a Node 24.22+/26.12+ TypeScript daemon with a SQLite state DB) is the control plane. Around it sit the Control UI (web), CLI, TUI, **channels**, and **nodes**: companion apps that add voice, screen, camera and `system.run` per device. Models and agent harnesses are plugins. Trust model: "trusted gateway, untrusted execution, policy enforced by code". |
| **Channels** | WhatsApp, Telegram, Slack, Discord, Teams, Signal, iMessage, Matrix, Google Chat and 20+ more, plus phone calls (Voice Call channel), Discord voice and meetings. |
| **Apps** | macOS, iOS, Apple Watch, Android (on Google Play), Linux, and a cross-platform Tauri desktop app. On Windows, **Windows Hub** is a native WinUI app in a separate repo (`openclaw/openclaw-windows-node`, C#, MIT). It provides the tray, chat and diagnostics, and runs the Gateway inside an **app-owned WSL distro** (`docs/platforms/windows.md`). |
| **Voice** | "Talk" mode has two forms. (1) A native loop: platform speech recognition, then the agent, then TTS (ElevenLabs by default, MLX local TTS on Mac, or system voice). Defaults are a 700 ms silence window and `interruptOnSpeech: true`. (2) Realtime speech-to-speech: OpenAI `gpt-realtime-2.1`/GPT-Live over WebRTC, or Google over WebSocket. Realtime hands tool work to the agent through an `agent-consult` call. Wake words are a single global list (defaults `openclaw`, `claude`, `computer`) and work on **macOS 26+, iOS and Android (foreground only)**. **Windows has push-to-talk only** (`talk.ptt.*`), with no wake word. There is no speaker verification. (`docs/nodes/talk.md`, `docs/nodes/voicewake.md`) |
| **Agents, tools, skills** | Built-in tools: exec with approvals, browser, web search (about 15 providers), PDF, image/video/music generation, `computer`, subagents and swarm, goals and progress cards. **Coding agents**: a native Codex runtime, a native Claude CLI runtime (works with saved subscriptions), and ACP harnesses (Claude Code, Cursor, Copilot, OpenCode, Gemini CLI). Managed worktrees, plus **pull-request workflows from chat** (import, prepare, publish; new in October). **Skills**: hand-written ones, the **ClawHub** marketplace, a new **Claws** community catalog, and **Skill Workshop / self-learning**, which is on by default: the agent saves and fixes its own procedures, with undo and a 30-day archive (`docs/tools/self-learning.md`). It works as an MCP client, and `openclaw mcp serve` exposes it as an MCP server. |
| **Memory** | Markdown memory: `USER.md`, `MEMORY.md` and daily notes. Hybrid search, active (trigger) recall, "dreaming" consolidation, provenance and forget. The bundled **Knowledge** plugin (bundled 2026-10-2x, #180139) adds an evidence-backed vault of claims with sources, "scribes" and a UI explorer. LanceDB and Honcho are available as alternatives. |
| **Proactive** | Cron (`at`, `every`, `cron`, `on-exit`, `stream`), heartbeat, standing intents, hooks, background tasks that survive restarts, and completion notifications. |
| **UI** | The web Control UI (sessions, a Details panel, terminal, file browser, remote-desktop panel, mobile layout; about 40 UI feature PRs since 10-19), `show_widget` HTML widgets, pinned native dashboard reports, Canvas, and tray apps. |
| **Models** | Dozens of hosted providers, plus local Ollama, vLLM, SGLang and LM Studio, with failover. "Decision models" are small local classifiers used for routing. Gemini 4 Argon was added in 2026.10.7. |
| **Install** | A one-liner (`iwr -useb https://openclaw.ai/install.ps1 \| iex` on Windows), an onboarding wizard that verifies model access, `--install-daemon`, `doctor`, self-update with recovery, and Docker, Nix and Kubernetes options. |
| **Security posture** | Pairing, operator scopes, exec approvals and an optional sandbox. Host exec is the default for the main session, and the README says to read the security guide before exposing anything. GitHub lists **722 published advisories: 14 critical, 249 high, 390 medium, 69 low**. They peaked in Feb-Mar 2026 (220 and 204 a month) and fell to 45 in June and 75 in September. The newest is dated 2026-09-11, so **none were published after the 2026-10-19 study**. |
| **Known incidents** | Already in the gap study (§2): the one-click RCE CVE-2026-25253, 17.5k-40k exposed gateways, the ClawHavoc malicious skills (341 to about 900), a Docker sandbox escape, the Moltbook key leak, and a 91% prompt-injection success rate in ZeroLeaks. The 14 criticals are mostly pairing/scope escalation to admin and node RCE (Feb-Apr 2026). |
| **Activity** | 393k stars, 82.7k forks, 7.7k open issues, created 2025-11-24. **About 7,450 commits between 2026-10-19 and 10-28.** Stable 2026.10.6, 10.7 and 10.8 shipped (10.6 alone had 293 PRs), plus an LTS line (2026.9.3x) and 2026.10.10 betas. |
| **Self-rated maturity** | `docs/maturity/scorecard.md` rates the whole product **Alpha, 68%**. By surface: Gateway runtime Stable 80/88, Android app Stable 80/80, Telegram Beta 68/78, **Voice and realtime talk Alpha 61/68**, **Native Windows Alpha 58/66**, **Windows App/Node: quality 19, completeness 21**, Windows via WSL2 Beta 69/79, Voice Call Experimental 41/44, ClawHub Alpha 58/62. |

**Changes after 2026-10-19.** These are almost all reliability work.
- **Releases:** 2026.10.6, 10.7 and 10.8 harden replay-safe recovery, update, migration and backup, Windows state and Scheduled Task handling, and Claude CLI and Codex sessions.
- **Security items:**
  - a patched Node runtime is now required, after the "compromised certificate keys" in the October Node.js security releases;
  - Gateway env is kept out of ACP agents (#179899) and hooks tokens out of exec children (#179199). Both confirm the gap study's A6;
  - Gateway-local terminals are restricted (#177855);
  - tool policy can be set per deployment (#174547);
  - `test -v` now needs approval, and API keys no longer leak in TTS error messages.
- **New features:** the Knowledge plugin, the Claws catalog, PR workflows, guest ("visitor") access, compaction at task boundaries (#178021), and anonymous install counting (#186569).
- **Not changed:** still no Windows wake word and still no speaker verification.

---

## 2. Comparison matrix

Phase numbers refer to Snow's ROADMAP. "Snow now" means Phase 1, which has 31 of 33 plans done (the wake-model plan 01-30 and the CI plan 01-10 are still open).

| Parameter | OpenClaw | Snow now | Snow planned | Verdict (Snow vs OC, at plan) |
|---|---|---|---|---|
| **Wake** | Wake word on Mac, iOS and Android; push-to-talk only on Windows | Local openWakeWord "Hey Snow", with no idle audio leaving the PC | Same | **Ahead** on Windows |
| **STT** | Platform recognisers or realtime provider | Groq Whisper final + Moonshine live words and offline fallback | VOIC2-03 vocabulary bias | **Equal** (Snow better on offline; OC more languages) |
| **TTS** | ElevenLabs, MLX (Mac), system voice, realtime voices | Kokoro on CPU everyday; Pocket, Cartesia and Chatterbox routed by mood and power | HUD voice meter | **Ahead** on emotion and cost; **behind** on realtime naturalness |
| **Barge-in** | `interruptOnSpeech`, or native in realtime; no speaker check | AEC3 + speaker-verified barge-in (FxSound breaks it; backlog 999.2) | VOIC2-02 speaker mode | **Ahead** |
| **Conversation and brain** | A full agent loop with tools on every turn | Persona, tone-aware, LLM-written lines, 6 turns in RAM, **no tools** | Tool loop from Phase 2 | **Behind** now, equal-ish later |
| **Memory** | Markdown memory, hybrid recall, dreaming, Knowledge vault, provenance, forget | None | **Not a v1 requirement** (only seeds) | **Behind** |
| **Tools and skills ecosystem** | 50+ tools, ClawHub, Claws, self-learning skills, MCP in and out | None | MCP behind the policy gate (stack doc); AWAR-04 v2 | **Behind** (by design: no marketplace) |
| **Coding-agent control** | Claude CLI, Codex, ACP harnesses, worktrees, steer, progress cards, PRs from chat | None | Claude Code by voice (P2), steer and worktrees (P3), other agents v2 | **Behind** now; **ahead** on voice-driving at P3 |
| **PC, app and browser control** | `computer` tool (Windows CUA plugin is experimental), browser with logins, Windows node screen/notify/run | Media/volume not yet | P5: apps, UIA, screen control, drafts, git | **Behind** now, **equal or ahead** at P5 on Windows (UIA-first) |
| **Phone and messaging** | Native Android app, 20+ chat channels, Telegram approvals, Mini App | None | Telegram over Tailscale (P4), phone HUD in browser (P6) | **Behind** (breadth); **equal** on the one path Snow needs |
| **Proactive and background tasks** | Cron, heartbeat, standing intents, durable background tasks | None | Hand-off tasks (P4); reminders and proactivity deferred (AWAR-02) | **Behind** |
| **HUD/UI** | Functional web dashboard, widgets, Canvas, tray | Electron HUD: 2D ASCII orb, transcript, health, mini indicator, tray | Glass-box 3D orb, activity stream, panels, corner widget, phone (P6) | **Ahead** in identity and glass-box intent; **behind** in panel breadth |
| **Multi-model and provider independence** | Many providers + local models + failover; subscriptions are first-class | 5 free providers, per-role chains, cooldowns, privacy routing | Same | **Equal**; Snow **ahead** on privacy routing, OC on breadth and local models |
| **Privacy and security** | Powerful but permissive defaults, 722 advisories, marketplace incidents | Credential Manager, loopback hub, Snow's own token issue (gap study A1) | Fail-closed tiers, kill switch, audit chain, speaker gate (P2) | **Ahead** in design; unproven until P2 ships |
| **Setup and robustness** | One-liner installer, wizard, doctor, self-update, Windows via WSL | Dev setup; supervisor, autostart, Job Object, health | Doctor (seed), canary self-upgrade (P3), installer (P7) | **Behind** |
| **Extensibility** | Plugin SDK, skills, MCP server, many runtimes | Typed event contract, config-swappable models | Adapter contract (P2), MCP | **Behind** (on purpose) |

**Bottom line.** OpenClaw is a broad, shipping, chat-first agent platform, and its own scorecard puts its Windows and voice surfaces at Alpha. Snow is a narrow, Windows-native, voice-first assistant that today talks but does not act yet. Snow beats OpenClaw only where OpenClaw is weakest: voice on Windows, speaker identity and a safety-first design.

---

## 3. Snow's gaps vs OpenClaw, ranked by user value

| # | Gap | User value | Snow phase | Effort |
|---|---|---|---|---|
| 1 | **Snow cannot act yet**: no tools and no agent control. Everything OpenClaw does starts here. | Very high | P2 (Claude Code + gate) | L (the phase itself) |
| 2 | **No memory** across sessions: preferences, projects, "what did we decide". | High | **Not planned** as a requirement (seeds SEED-261019-mnj item 3, gap study D1-D8) | M |
| 3 | **No reach from the phone**: OpenClaw has a native Android app plus Telegram. | High | P4 (Telegram), P6 (phone HUD) | M |
| 4 | **No reminders or "tell me when X finishes"**: OpenClaw's cron with `on-exit`/`at`. | High (natural voice requests) | `on-exit` fits P4 hand-off; timed reminders **not planned** (AWAR-02 is broader) | M |
| 5 | **No dictation into the focused app**: OpenClaw has a transcription-only Talk mode. For "replace the keyboard", plain dictation into any text box is the most frequent need. | High | **Not planned** explicitly (P5 PCTL types only via screen control) | S-M |
| 6 | **PC, app and browser control.** | High | P5; logged-in web tasks PCTL2-01 (v2) | L |
| 7 | **Only one coding agent** (OpenClaw has Codex, Claude, OpenCode, Gemini and Cursor). | Med-high (the user rotates agents) | AGNT2-01/02 (v2) | M (ACP adapter) |
| 8 | **No PR/GitHub flow after accepting work.** | Med | P5 (PCTL git/GitHub); could be P3 | S |
| 9 | **No learned procedures**: self-learning skills with undo. | Med | **Not planned** | M |
| 10 | **Installer, onboarding, doctor and self-update.** | Med now, high for "others later" | P3 (self-upgrade), P7; doctor in seeds | M |
| 11 | **Panel breadth**: terminal, files, diffs, widgets and pinned reports. | Med | P3 / P5 / P6 | M |
| 12 | **Voice from the phone**: Telegram voice notes, or Talk on Android. | Med | **Not planned** (HAND-04 is text) | S (voice notes through the existing STT) |
| 13 | **Realtime speech-to-speech option.** | Low (cost, provider lock-in, no speaker check) | Not planned; keep it that way | - |
| 14 | **Local LLMs** (Ollama and similar). | Low (6 GB VRAM) | Config-swappable already | S |

---

## 4. What Snow does better or differently (honestly)

- **Voice on Windows is the core, not an add-on.** Snow has a local wake word, Smart Turn, live words, AEC, barge-in and a 1-second reply budget. On Windows, OpenClaw has push-to-talk only, and it rates its own Windows app at quality 19 out of 100.
- **Only the user can command Snow.** OpenClaw has no speaker verification; its Talk mode trusts the microphone, and anyone near a phone or Mac with wake enabled can drive it.
- **Emotion and tone.** Snow detects the user's tone locally, the LLM picks the emotion, and voices are routed by mood. Every spoken word is LLM-written, while OpenClaw speaks fixed English status templates.
- **Free-tier, privacy-routed brain.** Code and personal data never reach untrusted free providers. OpenClaw routes by capability, not by data trust.
- **Safety by construction (planned).** Snow plans fail-closed tiers, timeout-means-deny, a kill switch outside the LLM, a tamper-evident audit log, and no marketplace. OpenClaw's 722 advisories, mostly from breadth and permissive defaults, are the cost Snow avoids by staying narrow.
- **Native Windows.** Snow uses UIA-first PC control (planned), Credential Manager and a Task Scheduler autostart without WSL. OpenClaw's recommended Windows path runs its Gateway inside a WSL distro.
- **Glass-box HUD as an identity**, rather than a generic chat dashboard.
- **Honest caveat.** Most of the points above are plans. Today Snow is a voice loop with no tools, no memory and no phone link. OpenClaw is a real product used at scale.

---

## 5. Recommended adoptions (ideas only)

The gap study's ranked top 8 (A1 per-role tokens first, A2/A3 plan-hash approvals, A7/D1 origin and taint, B1-B3 Telegram, C5/C6 recovery, C7/C8 worktrees and canary, B7/B8 Tailscale and presence, C1/C2 run control) still stand unchanged. The items below are new.

| # | Idea (our own design) | From OpenClaw | Snow phase |
|---|---|---|---|
| 1 | **Fast voice, deep consult.** The fast role answers at once and calls one `consult_brain` tool for tool-heavy work, while an LLM-written acknowledgement plays. This keeps the 1-second budget once tools exist. | Realtime `agent-consult` brain strategy | P2 |
| 2 | **"Tell me when it's done"** as an `on-exit` trigger on any agent task, with the phone or voice chosen by presence. | Cron `on-exit` | P4 |
| 3 | **Dictation mode.** "Snow, type this" streams the final transcript into the focused text field through UIA ValuePattern or SendInput, marked as synthetic input (gap study B8). No LLM involved, and it ends on "Snow, done". | Transcription-only Talk sessions | P5 (new requirement) or backlog |
| 4 | **Voice notes from the phone.** A Telegram voice reply goes through the same Groq/Moonshine router, and speaker verification is applied to the note before it can approve anything. | Android voice notes through transcription | P4 (extend HAND-04) |
| 5 | **"Open a PR for that"** after the user accepts a worktree: the agent writes the PR text, and the user approves it as a send action (typed scope `post`, gap study A5). | PR prepare/publish from chat | P3 or P5 |
| 6 | **Typed report panels, not HTML widgets.** The brain emits a typed `panel.report` (metrics, table, links) that the HUD renders natively. Never agent-supplied HTML: their `show_widget` runs agent HTML. | `show_widget` pinned reports | P6 |
| 7 | **Learned procedures with undo.** After a hard multi-step task, offer "save this as a routine?". Routines are stored as typed steps with a previous version kept, and archived after 30 days unused. Owner-origin only (D1). | Skill Workshop / self-learning | Memory phase / backlog |
| 8 | **Evidence-backed memory.** Every remembered claim keeps its source event `seq`, and "why do you think that?" answers from the source. | Knowledge plugin | Memory phase (deepens D1-D3) |
| 9 | **Compact at task boundaries.** Summarise history when a task ends, not mid-turn. | #178021 | Memory phase |
| 10 | **An evidence-led capability scorecard.** Each Snow capability is rated only from passing hardware or UAT evidence, and is shown in `snow doctor` and the HUD health panel. This is honest status for "others later". | `docs/maturity/scorecard.md` | P7 (seed in P2 doctor) |
| 11 | **Runtime floor check.** `snow doctor` refuses known-vulnerable Electron and Python runtimes, like their Node floor after the October Node.js certificate incident. | 2026.10.6 Node requirement | P7 |
| 12 | **Budget P7 for update and migration robustness.** Most of their October fixes are about updates, migrations, backups and Windows state paths, including 8.3 short names, TEMP aliases and locale-specific Scheduled Task errors. Add these to Snow's soak test. | 10.6-10.8 release notes | P3 (canary) / P7 |

**Do not adopt.** A skills marketplace or a community catalog; in-process plugins; 20+ channels; WSL-hosted core; realtime speech-to-speech as the main path; guest access; HTML widgets from the agent; wake words without speaker verification.

**Backlog candidates for ROADMAP** (each "Optional, only when the user asks", like 999.1 and 999.2):
- **999.3 Memory v1.** Profile, project-scoped notes, evidence and forget, from seeds D1-D8 and idea 8. This is the largest unplanned gap.
- **999.4 Reminders and "tell me when".** Timed reminders plus `on-exit` triggers, using the gap study's E1 scheduler rules.
- **999.5 Voice dictation into any app** (idea 3). Core to replacing the keyboard; could instead become a P5 requirement.
- **999.6 Learned routines** (idea 7).
- *(Already v2:* AGNT2-01 more agents through ACP. Consider moving it up to just after P3, since the user rotates agents.)*

---

## Sources

- **Repository:** https://github.com/openclaw/openclaw (MIT), `README.md`. Docs read at `c94a96b`: `docs/platforms/windows.md`, `docs/platforms/android.md`, `docs/nodes/talk.md`, `docs/nodes/voicewake.md`, `docs/nodes/computer-use.md`, `docs/tools/acp-agents.md`, `docs/tools/self-learning.md`, `docs/tools/skill-workshop.md`, `docs/tools/show-widget.md`, `docs/concepts/memory.md`, `docs/plugins/knowledge.md`, `docs/maturity/scorecard.md`.
- **Releases:** https://github.com/openclaw/openclaw/releases (v2026.10.6, v2026.10.7, v2026.10.8, v2026.10.10-beta.4).
- **Advisories:** `gh api repos/openclaw/openclaw/security-advisories` (all 722 published advisories, counted 2026-10-28).
- **Commits:** `gh api repos/openclaw/openclaw/commits?since=2026-10-19` (about 7,450).
- **Windows Hub:** https://github.com/openclaw/openclaw-windows-node (MIT, C#, 2.2k stars). Its code search shows no wake-word code.
- **Incident press sources:** as listed in [openclaw-gap-study.md](./openclaw-gap-study.md) §Sources.

**Not checked.**
- I did not run any OpenClaw voice path or measure its latency.
- I did not read ClawHub or Claws moderation code.
- Commit and advisory counts come from API pagination at one point in time.
- The Windows App quality score of 19 may reflect missing evidence rather than poor quality.
