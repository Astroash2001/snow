# Feature Research

**Domain:** Always-on voice-first personal AI desktop assistant that drives CLI coding agents and the PC (Windows), with a glass-box HUD, safe autonomy, and hand-off-and-notify to Android. Single power user now, installable by others later.
**Researched:** 2026-10-13
**Confidence:** MEDIUM. Web search results were mostly secondary or vendor sources (classified LOW unless cross-checked). The findings used for requirements are the ones corroborated by two or more sources or by primary docs (Microsoft Learn, Anthropic docs excerpts, LiveKit/Pipecat docs, GitHub README). Items that rest on one source are marked (single source).

## Framing: what Snow actually is

No existing product covers Snow's scope, so features were mined from five adjacent families:

| Family | Examples | What they contribute |
|--------|----------|----------------------|
| Dictation / voice-to-text | Wispr Flow, Claude Code `/voice`, Aqua | Push-to-talk, vocabulary, cleanup, destination-aware output, "press enter" |
| Command-grammar voice coding | Talon, Cursorless, Serenade | Deterministic fast commands, eye/noise input; also the cautionary tale (learning curve, vocal strain) |
| Computer-use / desktop agents | OpenAI Operator, Claude computer use and Cowork, Codex computer use, Windows Copilot Actions, Open Interpreter | Confirmation before critical actions, take-over, plan-before-act, tool-selection order, isolation, prompt-injection defenses |
| Voice-agent frameworks | Pipecat, LiveKit Agents, Vapi/Retell | Barge-in, turn detection, backchannel handling, echo cancellation, latency budgets |
| Agent dashboards and remote approval | Conductor, Claude Squad, Vibe Kanban, claude-remote-approver, claude-control, Claude Code Channels/Remote Control | Task boards, worktree isolation, phone approvals, "waiting on you" problem |

**Key strategic insight:** Snow is a *voice orchestrator*, not a dictation tool and not a command-grammar tool. The coding agents write the syntax, so Snow's voice vocabulary is intent-level ("add retry to the upload service, use Postgres"). That removes the Talon-style learning curve and vocal strain entirely, but it moves the hard problems to (a) entity-accurate recognition of project names, (b) trustworthy approvals, and (c) making unattended work visible. Those are where the table stakes below concentrate.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Missing any of these makes Snow unusable or unsafe for a user who wants to stop typing. Grouped by area.

#### Voice core

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Local wake word "Hey Snow" with audible/visual acknowledgement | Every assistant (Hey Copilot, Alexa, Siri) does this; chime plus HUD flip is the "it heard me" signal | MEDIUM | openWakeWord, custom-trained. Home Assistant users report sensitivity/false-trigger tradeoff, so tuning plus a threshold setting is needed. Ack must hit within 100 ms (HUD) |
| Push-to-talk hotkey and mute toggle alongside wake word | Wispr Flow and Claude `/voice` are hotkey-first; AssemblyAI notes user-set clip boundaries beat silence detectors; wake word fails in noise | LOW | Also the escape hatch when wake word misfires. Visible hard-mute state (mic off must be unmistakable on the HUD) |
| Streaming STT with barge-in (interrupt mid-sentence) | Pipecat interrupts by default; LiveKit treats it as core; ~55% of voice-agent users report interruption frustration (single source) | HIGH | Requires echo cancellation (Snow talks through laptop speakers and will otherwise hear itself). Cancel in-flight TTS and LLM work on interrupt |
| Echo cancellation / self-voice suppression | LiveKit docs: AEC must be handled client-side; without it barge-in self-triggers | MEDIUM | Windows: use OS/WebRTC AEC or headset-first default; test with speakers on |
| End-of-turn detection that does not cut the user off | LiveKit and Pipecat both ship turn detectors beyond plain VAD; naive silence timeouts feel robotic | MEDIUM | Prefer semantic or model-based endpointing, with a tunable delay. Thinking pauses are common when dictating a task |
| Backchannel tolerance ("mm-hm", "okay" must not stop Snow) | LiveKit adaptive interruption exists specifically for this; community threads show over-aggressive interruption on filler words | MEDIUM | Can start as a minimum-duration plus word-count threshold; upgrade later |
| Project-vocabulary biasing for recognition | AssemblyAI: mangled identifiers ("axios" to "axe eos") are *the* reason developers quit; Claude `/voice` has no custom dictionary | MEDIUM | Feed faster-whisper hotwords/initial prompt from active workspace (package names, repo names, file names, agent names). Also LLM-side repair using workspace context |
| Self-correction cleanup before sending to the agent | "use Postgres, no wait, SQLite" arrives as two contradictory instructions with verbatim STT | LOW | LLM normalization step; PROJECT already wants "stop, use Postgres instead" redirection, which is the live-task version of the same thing |
| Always show what was heard (live transcript) with original retained | Wispr and AssemblyAI both recommend a "show original" fallback; misheard input compounds through every later step | LOW | Part of the activity stream: heard, then understood. Lets the user catch STT errors before action |
| Never lose an utterance | Developers report long dictations vanishing; WebSocket dies on network change | LOW | Buffer audio locally; STT is local so mostly free. Cartesia TTS failure must degrade to local voice, not silence |
| Spoken replies start in about 1 s, short, outcome-first | Voice UX guidance: audio cannot be scrolled, so summary first and detail on request; code and diffs on screen only | MEDIUM | Already in PROJECT. Needs streaming LLM to TTS sentence pipelining |
| Typed/text fallback input | Voice fails in meetings, shared spaces, and for secrets; Operator and Copilot both keep text input | LOW | "Replace the keyboard" means keyboard becomes optional, not impossible. Tiny HUD command bar. Also the answer for passwords (see anti-features) |

#### Voice-driven coding

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Start, steer, stop an agent session by voice | The core value statement | HIGH | Adapter per agent (Claude Code, Antigravity, OpenCode). Prefer each agent's structured/headless/SDK interface over scraping a TTY. Scraping a PTY (as claude-control does) is the fallback |
| Relay agent questions and permission prompts to the user, relay the answer back | claude-remote-approver, claude-control and Channels all exist because this loop is *the* pain point | HIGH | Map the agent's permission hook and question tool to spoken or HUD prompts. Must be **fail-closed**: no answer means deny/ask, never auto-allow. claude-remote-approver falls back to the native CLI prompt on timeout, which is the right shape |
| Mid-task status query and redirect | Cowork shows a plan and lets you intervene; Operator offers take-over | MEDIUM | Needs the orchestrator to hold per-task state, not just proxy text |
| Spoken outcome summary; code, diffs, logs on screen | Voice-UX guidance and PROJECT agree; no source found that reads diffs aloud successfully | LOW | Summary first, "want details?" on request |
| Session persistence and resume across Snow restarts | Channels dies when the terminal closes (users work around it with tmux); hand-off breaks without it | MEDIUM | Run agents as supervised background processes owned by Snow, with saved task state |
| Provider/agent failover | PROJECT constraint: agent access comes and goes | MEDIUM | Health check per adapter, voice-announced switch ("Claude's out of quota, continuing with OpenCode") |

#### PC control

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Deterministic fast-path commands (open/close/switch app, volume, brightness, media, "stop", "cancel") | Talon's value is speed and reliability of fixed commands; users will not tolerate a 2 s LLM round trip to change volume | LOW | Route by intent: fast local intent matcher first, LLM planner second. Still generated-speech replies, but the action itself must not wait on the brain |
| Tool-selection order: native API/CLI/connector, then browser DOM/accessibility, then screenshot-and-click last | Anthropic's Cowork uses connector then browser then computer-use as a fallback; pixel clicking is slowest and least safe | HIGH | Windows UI Automation tree before vision. This ordering is what makes "any app" feasible without being flaky |
| Screen-understanding control for apps with no API | Operator, Claude computer use, Codex, Copilot Actions, Open Interpreter OS mode all provide it | HIGH | The sparkly feature but the last resort. Needs per-step screenshot, action, verification loop and a step budget |
| Multi-step workflows chained from one command | Standard in all agent products; Jarvis-style OSS projects chain up to ~15 tool calls (single source) | MEDIUM | Plan-then-act with visible plan (Cowork shows plan first) |
| Files, folders, git/GitHub, dev-environment setup | Open Interpreter and Codex cover shell and files | MEDIUM | Mostly delegated to a coding agent plus a shell tool |

#### Safety and autonomy

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Risk-tiered approvals, with confirmation before irreversible or critical actions | Operator system card: confirmation before significant actions; Copilot Actions: approval for sensitive steps; Open Interpreter: confirm before run | MEDIUM | Tier 0 free, Tier 1 announce, Tier 2 ask, Tier 3 always ask (credentials, payments, security settings, irreversible delete). Tier 3 must be enforced by **deterministic code rules**, not an LLM judgement |
| Instant kill switch / panic stop (voice "Snow, stop" plus global hotkey plus HUD button) | Operator "take control", Copilot "take control at any time"; an always-on agent with full permissions needs a hard brake | LOW | Stop must pre-empt everything, including in-flight GUI actions and child agents. Must work even when the LLM is wedged, so handle it outside the LLM path |
| Take over for secrets (user types or enters credentials themselves) | OpenAI demo had the user enter card details via take-control | MEDIUM | Snow pauses, shows the window, waits, resumes. Never transcribes a spoken password |
| Presence-aware approval routing: voice/HUD at the PC, phone when away | PROJECT requirement; remote approver tools provide phone half only | MEDIUM | Needs presence signal (input idle time, lock state, HUD focus). Default to phone when locked |
| Approval timeout that fails closed and leaves a pending item | claude-remote-approver defaults 120 s then fallback; Auto-mode stops and escalates after 3 consecutive or 20 total denials | LOW | Pending approvals persist on HUD and phone; never silently expire into "allow" |
| Treat screen, web, file and tool-output content as untrusted data | Anthropic docs recommend classifiers on screenshots and "tool content cannot override instructions"; Microsoft names cross-prompt injection (XPIA) as a primary risk | HIGH | Cannot be solved by prompting alone. Pair with: tier-3 hard rules, egress limits, no secrets in agent context, and approval on any action that originated from page content rather than from the user's words |
| Secrets in OS secure store, never in logs/code | Windows agentic security principles; baseline hygiene | LOW | Windows Credential Manager/DPAPI. Redact logs |
| Only the owner's voice can command | Replay/TV/other-voice risk is real for a wake-word-only gate (Göttingen paper on wake-word replay attacks, 17-participant study) | HIGH | Local speaker verification. See Differentiators for the market view; here it is table stakes because the combination is always-on plus full permissions |
| Authenticated, private remote path (Tailscale) | PROJECT; claude-remote-approver warns that public ntfy.sh topics carry approval content, recommends self-hosting | MEDIUM | Phone replies must be authenticated; a guessable topic must never be enough to approve an action |

#### Glass-box HUD

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Live activity stream: heard, understood, plan, each action, result | Copilot Actions "monitor progress, stay informed at every step"; Windows security doc requires user transparency | MEDIUM | Event bus is the spine. Every subsystem emits typed events; HUD is just a consumer |
| Distinct, instant state indicators (idle, listening, thinking, acting, speaking, alert) | Every voice product has listening/thinking states; 100 ms response is a stated constraint | MEDIUM | Drive from local events, not from LLM output, so listening feedback never waits on the network |
| Live panels for what Snow is touching: terminal output, diffs, drafts, target window | Operator shows the browser; Conductor-type tools centre on diff review | HIGH | Per-adapter streaming. Drafts before send is a safety feature (WhatsApp read-back) |
| Pending approvals surface with context | "Two agents waiting on a question you never saw" is the named failure of multi-agent tools | LOW | Shown prominently, including on return from away |
| Task board: done, in progress, waiting on you | Vibe Kanban, Conductor, Claude Squad all converge on this | MEDIUM | Also the return-from-away landing view |
| Persistent, searchable history/audit log of the day | Microsoft security doc calls for tamper-evident logs; Claude Code blocks transcript tampering outright | MEDIUM | Append-only, redacted, hash-chained if cheap. Same data feeds history panel and debugging |
| Silent mode (follow visually with no voice) | Meeting/night use; text fallback pairs with it | LOW | A TTS-off flag plus verbose HUD |

#### Hand-off and notify

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Walk-away background execution with saved state | Core hand-off promise; Channels and Cowork both sell this | MEDIUM | Depends on supervised sessions and the task store |
| Phone push on done, failed, needs-decision | Every remote tool (Pushary, ntfy-based approvers, Channels) provides this | LOW | ntfy or Telegram first, as planned |
| Answer from phone with actionable buttons (approve/deny, pick option) | claude-remote-approver: approve/deny/always-approve buttons, options as buttons split across notifications | MEDIUM | Free-text answers need a reply channel (Telegram handles this better than ntfy actions) |
| Notification content is brief but sufficient to decide, with a deeper view available | claude-remote-approver warns notifications show only a short summary and users must review what they approve | LOW | Include what, where, why-risky in the first line. Link to a Tailscale-served detail page for the diff |

#### Production baseline

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Starts with Windows, auto-recovers, health monitoring | "Always-on" is meaningless otherwise | MEDIUM | Supervisor process separate from the voice process |
| Structured logs, clear errors, spoken error explanation | Product bar per PROJECT | LOW | Errors are also LLM-voiced, but the factual payload is deterministic |

---

### Differentiators (Competitive Advantage)

Aligned with Core Value: real work by voice alone, visibly, with safe autonomy. Rank by how directly they serve that.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| One voice for any coding agent (pluggable adapters, switch by voice or on failure) | Claude `/voice` only works inside Claude Code with a claude.ai account; Wispr Flow only dictates text; nobody offers agent-agnostic voice orchestration | HIGH | Biggest strategic differentiator and fits the "never depend on one provider" constraint. Adapter contract must expose: start, send, stream events, permission request, question, stop |
| Glass-box ASCII HUD as a real audit surface (not decoration) | Competitors either hide the work (voice only) or show a plain log. A live, visual, state-driven HUD makes autonomy trustable | HIGH | Visual identity plus a functional trust layer. Risk: GPU contention with faster-whisper on 6 GB VRAM. Treat HUD GPU budget as a hard constraint (see Pitfalls) |
| Reasons shown for every proactive suggestion/risk notice | Copilot and others act opaquely; "why" display builds trust | LOW | Cheap if the event schema includes a `reason` field from day one |
| Speaker verification (owner-only commands) | Wake-word assistants rely on the wake word alone; Wispr/Copilot do not verify who is speaking | HIGH | Market differentiator, though product-mandatory here. Local model (small) fits VRAM |
| Presence-aware risk routing across PC and phone | Existing tools handle either the terminal prompt or the phone; none route by presence | MEDIUM | Uses same approval object, two renderers |
| Unified approval inbox across all agents and Snow's own actions | Today each agent has its own permission UI; remote approvers are per-agent hooks | MEDIUM | Natural consequence of the adapter contract. One queue, one policy, one history |
| Policy engine for autonomy (allow/announce/ask/deny rules, user-editable, voice-adjustable) | Claude auto mode uses a classifier with hard-deny org rules; Snow can combine deterministic rules (security-critical) with LLM judgement (routine) | MEDIUM | Classifier alone is not a security boundary: a Cloud Security Alliance note (unverified, single source) reports bypass chains against auto mode, and Anthropic's own docs advise isolation for unattended runs. Keep tier 3 deterministic |
| Worktree-per-task isolation for coding agents | Conductor, Claude Squad, Vibe Kanban all use it; makes parallel tasks and review/rollback safe | MEDIUM | Caveat: worktrees share the machine, so they isolate files not environment. Good enough for v1 coding tasks |
| Review-and-undo checkpoints (revert what Snow did) | Codex/Cowork emphasize review; voice-only users cannot easily eyeball and fix | MEDIUM | "Snow, undo that" for git changes is easy via worktree; for GUI actions, mostly not. Say so honestly |
| Hand-off with morning-brief style return summary (voiced on return) | Closes the loop of walking away | LOW | Mostly a prompt over the task board; keep as a quick win |
| LLM-generated speech with chosen vocal emotion (Cartesia) | Competitors use scripted or flat TTS; explicit PROJECT requirement | MEDIUM | Needs a guardrail layer: facts must come from structured events so the persona cannot misreport what happened |
| Destination-aware dictation (when Snow types into an app: commit message vs chat vs doc) | Wispr Flow does this for text; Snow can reuse the idea for the "type into any app" case | MEDIUM | Only if direct text entry into arbitrary apps is built; most coding goes through agents |
| Provider/quota awareness and graceful degradation (gateway credits, TTS credit fallback to local voice) | Unique to a free-credits setup; competitors are single-vendor | MEDIUM | Surface "I'm low on credits" as a HUD alert, not a surprise failure |
| Background (non-focus-stealing) GUI control | Claude Cowork/Code now clicks and types in the background without taking the screen | HIGH | Strong differentiator but Windows makes it hard. Treat as stretch; start with focus-taking control plus a clear "I'm using your screen" banner |

---

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Spoken code syntax and a Talon-style command grammar ("slap", "if colon newline indent") | "Real voice coding" association | Steep learning curve and vocal strain are the consensus drawbacks; AssemblyAI shows spoken syntax produces prose, not code; agents already write the syntax | Intent-level speech to a coding agent; tiny deterministic command set only for non-coding control |
| Reading code, diffs or long logs aloud | "Hands-free means eyes-free" | Audio cannot be scrolled; guidance says code and tables are painful as audio | Short spoken summary plus on-screen diff; offer "read the key line" on request |
| Narrating every action by voice | Feels transparent | Constant chatter makes Snow exhausting and masks real alerts | HUD carries full detail; voice only for outcomes, questions, risk |
| Auto-approve everything / bypass mode for remote sessions | Fewer interruptions | Anthropic itself disables bypass on Remote Control; auto-mode classifier is contested as a boundary; always-on plus voice plus remote magnifies blast radius | Tiered approvals with deterministic tier 3; widen tier 1 as trust accrues |
| LLM-only safety gate | Simple to build | Prompt injection via screen or web content can sway the model; auto-mode designers deliberately keep the classifier blind to tool results | Rule-based hard tiers plus injection-aware context separation |
| Voice entry of passwords, card numbers, 2FA codes | "Fully hands-free" | Secrets end up in transcripts, logs, cloud TTS/LLM context, and the room | Take-over flow: user enters secret, Snow resumes. Use saved sessions/password manager autofill |
| Streaming idle mic audio to the cloud for wake detection | Better accuracy | Violates privacy by default; PROJECT mandates local idle | Local openWakeWord; cloud only after wake and only for what needs it (and STT is local anyway) |
| Hardcoded canned phrases ("Done, sir.") | Fast, cheap, predictable | PROJECT explicitly rejects robotic scripts; also sounds repetitive within a day | LLM-generated lines from persona plus structured facts; a deterministic fallback only when the LLM is down |
| Proactive interruptions and suggestion engine (rule, reasoning, learning) in v1 | The "Jarvis" fantasy | Already out of scope; premature interruptions destroy trust faster than they add value; needs a mature senses/memory layer | Ship "reason shown" plumbing now; build the engine after voice work is solid |
| Public ntfy.sh topic carrying sensitive approval content | Zero-setup phone push | Content traverses a public server; a guessable topic could allow spoofed requests | Self-host ntfy behind Tailscale or use Telegram with an allow-listed chat ID; approvals authenticated, not merely received |
| Full-desktop unattended computer use as the default path | "Any app" promise | Slowest, least reliable, most injection-exposed method; Cowork treats it as the last fallback | API/CLI first, accessibility tree second, pixels last, with step budgets |
| Dependence on a vendor voice product (Claude `/voice`, Wispr Flow) as Snow's voice layer | Faster to ship | Claude `/voice` needs a claude.ai login and does not work for API-key or remote setups; breaks provider independence | Own local STT stack |
| Native Android app, multi-user accounts, smart home, learning coach, job hunt in v1 | Scope enthusiasm | All explicitly deferred in PROJECT | ntfy/Telegram; revisit post-core |
| Heavy cinematic HUD effects that starve STT/wake word of GPU or CPU | Looks great in the reference video | 6 GB VRAM is shared; a stuttering HUD or lagging STT breaks the "feels human" latency bar | Fixed GPU budget for HUD, degrade glyph density adaptively, STT gets priority |

---

## Feature Dependencies

```
Event bus (typed events with reason + source)
    ├──required by──> Activity stream / HUD panels / History + audit log
    ├──required by──> Task board
    └──required by──> Phone notifications (same events, different renderer)

Local wake word + push-to-talk + mute
    └──requires──> Audio pipeline with echo cancellation
                       └──requires──> Streaming STT (local) + turn detection
                                          └──enables──> Barge-in + backchannel tolerance
Speaker verification ──gates──> every voice-originated command (tier-aware)

Agent adapter contract (start/send/stream/permission/question/stop)
    ├──requires──> Supervised session runner (background, resumable)
    │                  └──enables──> Hand-off / walk-away / task board
    ├──enables──> Voice relay of agent questions and permissions
    └──enables──> Agent failover, worktree isolation, unified approval inbox

Policy engine (tiers, deterministic tier 3)
    ├──requires──> Presence detection
    │                  └──enables──> Presence-aware routing (voice/HUD vs phone)
    ├──requires──> Approval object (id, action, risk, reason, expiry, fail-closed default)
    │                  ├──rendered by──> Voice prompt, HUD card, phone push with buttons
    │                  └──requires──> Authenticated reply path (Tailscale)
    └──enhances──> PC control actions and agent permission relay

Kill switch ──must bypass──> LLM path (hooks directly into runner + GUI executor)

PC control
    Fast-path intents ──fallback to──> LLM planner
    API/CLI tools ──fallback to──> Accessibility/DOM ──fallback to──> Screenshot control
    Screenshot control ──requires──> Injection-aware context handling + step budget + take-over flow

Vocabulary biasing ──requires──> Workspace scan (repo, packages, files) ──enhances──> STT + LLM repair

LLM-generated emotional speech ──requires──> Structured facts layer (events) so wording cannot invent outcomes

ASCII HUD ──conflicts (GPU budget)──> Local STT/speaker-ID on 6 GB VRAM

Proactive suggestion engine ──requires──> Memory + senses (deferred)  [only "reason" field is built now]
```

### Dependency Notes

- **Everything visible depends on the event bus:** HUD, history, task board, phone notices, and the audit log are all views over typed events. Building the HUD before the event schema guarantees a rewrite.
- **Barge-in requires echo cancellation:** without it Snow hears its own voice and either cuts itself off or ignores real interruptions. This is a voice-core phase item, not polish.
- **Adapter contract precedes hand-off:** walk-away work only makes sense once sessions are owned and resumable by Snow rather than living in a terminal the user closes.
- **Approval object precedes both phone and voice relay:** define it once (id, action, risk tier, reason, expiry, default-on-timeout=deny), then render it three ways. Otherwise each channel invents its own semantics, the pattern third-party remote approvers fall into.
- **Kill switch conflicts with LLM-mediated everything:** it must be a direct path to the process supervisor and GUI executor. If "stop" has to be understood by the model first, it will fail exactly when it is needed.
- **Speaker verification gates, but must not add latency:** run it in parallel with STT on the first second of audio.
- **HUD vs STT GPU contention:** a design constraint to resolve before the HUD shader work, via an explicit budget or by putting STT on CPU/int8 if needed.

---

## MVP Definition

### Launch With (v1)

Smallest set that delivers the Core Value ("do real work by voice, see it, safely, walk away"). Ordered roughly by build dependency.

- [ ] Event bus with typed events (source, reason, risk) and append-only audit log. Spine for everything else.
- [ ] Always-on service with supervisor, crash recovery, autostart. Without it the product is not "always-on".
- [ ] Wake word + push-to-talk + mute, local streaming STT, vocabulary biasing, turn detection, echo cancellation, barge-in. Voice core.
- [ ] Spoken replies via LLM + Cartesia (local fallback voice), short and outcome-first.
- [ ] Kill switch (voice, hotkey, HUD) wired outside the LLM path.
- [ ] Speaker verification on commands. Mandatory per PROJECT security constraint.
- [ ] Agent adapter contract with at least two real adapters (Claude Code plus one of OpenCode/Antigravity); question and permission relay by voice; status and redirect.
- [ ] Policy engine with four tiers, deterministic tier 3, fail-closed approvals, take-over flow for secrets.
- [ ] Deterministic fast-path PC control (apps, windows, volume, media, files) plus shell/git via agent.
- [ ] HUD v1: state machine, activity stream, approval cards, terminal/diff panel, task board, silent mode. Fully functional first; the full ASCII-3D body can grow into it.
- [ ] Hand-off: supervised background sessions, task board, ntfy/Telegram push, phone approve/deny and option answers, authenticated path.

### Add After Validation (v1.x)

- [ ] Screenshot-and-click control of arbitrary apps (with accessibility-tree first) — trigger: fast-path and API coverage proves insufficient for real daily tasks.
- [ ] Logged-in web tasks via the user's browser sessions — trigger: injection-handling and take-over flows are proven on desktop control.
- [ ] Multi-step cross-app workflows — trigger: single-step reliability above a set success rate.
- [ ] Worktree-per-task isolation and undo checkpoints — trigger: first time two agent tasks run in parallel on one repo.
- [ ] Adaptive interruption (backchannel classifier) — trigger: logs show false barge-ins.
- [ ] Free-text phone replies — trigger: button-only answers prove too limiting.
- [ ] Return-from-away voiced brief — quick win once the task board is stable.
- [ ] Quota and credit awareness alerts.
- [ ] Full ASCII-shader 3D body with glyph-of-your-code effect — can ship in stages behind the same state machine.

### Future Consideration (v2+)

- [ ] Proactive suggestion engine L3–L5 — needs memory and senses; explicitly deferred.
- [ ] Background (non-focus-stealing) GUI control or a separate agent desktop — hard on Windows; revisit when OS support matures (Windows agent workspace is still preview as of the last sources found).
- [ ] Native Android app — after ntfy/Telegram limits are felt.
- [ ] Multi-user install, public distribution — architecture must not block it, but not built.
- [ ] Learning coach, job hunting, smart home — deferred by user.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Event bus + audit log | HIGH | MEDIUM | P1 |
| Wake word, PTT, mute | HIGH | MEDIUM | P1 |
| Streaming STT + turn detection + AEC + barge-in | HIGH | HIGH | P1 |
| Vocabulary biasing + self-correction cleanup | HIGH | MEDIUM | P1 |
| Kill switch outside LLM path | HIGH | LOW | P1 |
| Speaker verification | HIGH | HIGH | P1 |
| Agent adapter contract + 2 adapters | HIGH | HIGH | P1 |
| Voice relay of agent questions/permissions | HIGH | HIGH | P1 |
| Tiered policy engine, fail-closed approvals | HIGH | MEDIUM | P1 |
| Supervised background sessions + resume | HIGH | MEDIUM | P1 |
| Phone push + actionable approve/deny | HIGH | MEDIUM | P1 |
| HUD: states, activity stream, approvals, task board | HIGH | MEDIUM | P1 |
| Fast-path PC control | HIGH | LOW | P1 |
| Take-over flow for secrets | MEDIUM | MEDIUM | P1 |
| Text fallback input, silent mode | MEDIUM | LOW | P1 |
| Presence-aware routing | HIGH | MEDIUM | P1 |
| Agent failover | MEDIUM | MEDIUM | P2 |
| Screen-understanding control | HIGH | HIGH | P2 |
| Logged-in web tasks | MEDIUM | HIGH | P2 |
| Multi-step cross-app workflows | MEDIUM | MEDIUM | P2 |
| Worktree isolation + undo | MEDIUM | MEDIUM | P2 |
| Full ASCII 3D HUD body/effects | MEDIUM | HIGH | P2 |
| Adaptive backchannel handling | MEDIUM | MEDIUM | P2 |
| Return-from-away brief | MEDIUM | LOW | P2 |
| Reason shown on every proactive notice | MEDIUM | LOW | P1 (schema), P3 (engine) |
| Background non-focus-stealing control | MEDIUM | HIGH | P3 |
| Proactive engine | MEDIUM | HIGH | P3 |
| Native Android app | LOW (now) | HIGH | P3 |

**Priority key:** P1 must have for launch; P2 should have, add when possible; P3 future consideration.

---

## Competitor Feature Analysis

| Feature | Wispr Flow | Talon / Cursorless | Claude Code (`/voice`, Remote Control, Channels) | Operator / Cowork / Copilot Actions | Remote approvers (ntfy-based) | Our Approach |
|---------|-----------|--------------------|---------------------------------------------------|--------------------------------------|-------------------------------|--------------|
| Voice input | Hotkey dictation, cleanup, file tagging in Cursor/Windsurf, "press enter" | Command grammar, noise and eye input, local engine | Hold or tap-to-talk dictation; needs claude.ai login; no custom dictionary | Operator: text-first; Copilot: "Hey Copilot" wake | None | Wake word + PTT, local STT with project vocabulary, intent-level speech |
| Agent-agnostic | Yes (dictation only) | Yes (keyboard emulation) | Claude only | Each own agent | Claude hooks only | Pluggable adapters |
| Answers agent questions by voice | No | No | No (dictation only) | Operator asks confirmation in UI | Phone buttons | Voice and phone, same approval object |
| Approvals | n/a | n/a | Permission modes; auto-mode classifier; Remote Control excludes bypass and auto | Confirm critical steps; take-over | Approve/deny/always-approve; timeout falls back to CLI | Tiered, deterministic tier 3, presence-routed, fail-closed |
| Transparency | Transcript | None | Terminal | Operator shows its browser; Copilot shows progress and take-over | Short push summary | Glass-box HUD: heard to result, panels, history |
| Hand-off + notify | n/a | n/a | Remote Control / Channels (session must stay alive) | Cowork background tasks (app must be open) | Push only | Supervised background sessions, task board, own channel |
| Task board | n/a | n/a | n/a | Cowork plan view | n/a | Done / in progress / waiting on you |
| Isolation | n/a | n/a | n/a | Copilot: separate agent account + workspace | n/a | Worktrees for code; GUI isolation deferred |
| Speaker verification | No | No | No | No | No | Yes (local) |
| Barge-in / turn detection | Not applicable | Not applicable | Not applicable | Limited | Not applicable | Pipecat/LiveKit-grade behaviours built into a local stack |

**Takeaway:** the competitive gap Snow fills is *voice as the interface to many agents plus a trust-building visual layer*. No single competitor combines wake word, agent relay, approvals by presence, and a live audit HUD.

---

## Gaps vs PROJECT.md (candidates for new requirements)

Research surfaced items not explicit in the Active list:

1. **Kill switch / panic stop** independent of the LLM (voice + hotkey + HUD button).
2. **Push-to-talk and hard mute** as first-class alongside the wake word.
3. **Echo cancellation** called out as a prerequisite to barge-in.
4. **Project vocabulary biasing** for STT and LLM repair.
5. **Self-correction cleanup** of dictated instructions.
6. **Fail-closed approval semantics** (timeouts, pending persistence, deterministic tier 3).
7. **Take-over flow for secrets** (no spoken credentials).
8. **Prompt-injection posture**: external content treated as data; actions that originate from page or screen content raise approval tier.
9. **Append-only, redacted audit log** (tamper-evident if cheap), separate from the display history.
10. **Typed fallback input** (keyboard optional, not impossible).
11. **Session persistence/resume** and supervised agent processes as an explicit requirement.
12. **Authenticated phone replies** (not just authenticated transport); topic secrecy alone is insufficient.
13. **GPU/CPU budget** between HUD shader and local STT/speaker-ID as an explicit non-functional requirement.
14. **Tool-selection order** (API/CLI, then accessibility/DOM, then pixels) as an architectural rule for PC control.
15. **Structured-facts layer** so LLM-generated speech cannot misreport outcomes.

---

## Sources

Confidence tags: [P] primary or official documentation read directly; [S] secondary or vendor/community, cross-checked where noted; [1] single source, unverified.

- [P] Microsoft Learn, "Windows 11 security book - Agentic security" (Copilot Actions: agent accounts, workspace, user transparency, take-over, approvals; XPIA risk): https://learn.microsoft.com/en-us/windows/security/book/operating-system-agentic-security
- [P] claude-remote-approver README (phone approve/deny, timeouts, CLI fallback, AskUserQuestion buttons, ntfy security notes): https://github.com/yuuichieguchi/claude-remote-approver
- [S] AssemblyAI, voice coding with coding agents (identifier mangling, no custom dictionary, filler/self-correction, push-to-talk, destination-aware output, show-original): https://assemblyai.com/blog/voice-coding-dictate-to-coding-agents
- [S] Claude Code voice dictation docs excerpts (hold/tap modes, claude.ai-only, no remote/SSH): https://code.claude.com/docs/en/voice-dictation
- [S] Claude Code mobile / Remote Control docs excerpt (permission modes exclude Bypass and Auto): https://code.claude.com/docs/en/mobile
- [S] Claude Code auto mode explainers (classifier behaviour, denial thresholds, hooks forcing prompts): https://claudelog.com/faqs/what-is-auto-mode-in-claude-code/ , https://claudefa.st/blog/guide/development/auto-mode
- [1] Cloud Security Alliance research note on auto-mode bypass (contested, single source): https://labs.cloudsecurityalliance.org/research/csa-research-note-claude-code-automode-prompt-injection-2026/
- [S] Anthropic mitigation docs (screenshot injection classifiers, treat tool content as untrusted): https://platform.claude.com/docs/en/docs/mitigating-jailbreaks-prompt-injections
- [S] LiveKit docs/blog (adaptive interruption, turn detection, AEC client-side): https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/ , https://livekit.com/blog/turn-detection-and-interruption-handling
- [S] Pipecat docs, interruptions: https://docs.pipecat.ai/pipecat/fundamentals/interruptions
- [S] Wispr Flow (file tagging in Cursor, Command Mode, Press Enter, vibe-coding settings): https://wisprflow.ai/post/file-tagging-in-cursor , https://docs.wisprflow.ai/articles/5096240724-navigating-the-wispr-flow-app-desktop-ios-and-android
- [S] Talon / voice coding coverage (noise, eye tracking, grammar, strain, learning curve): https://spectrum.ieee.org/programming-by-voice-may-be-the-next-frontier-in-software-development , https://blakewatson.com/journal/speaking-in-code-hands-free-input-with-talon/ , https://voicecontrol.pro/blog/coding-by-voice/
- [S] OpenAI Operator system card and Simon Willison coverage (confirmation prompts, take-over): https://cdn.openai.com/operator_system_card.pdf , https://simonwillison.net/tags/claude/?page=4
- [S] Open Interpreter safety docs (confirm-before-run, safe mode with no guarantees): https://docs.openinterpreter.com/safety/safe-mode
- [S] Claude Cowork/background computer use coverage (plan-before-act, connector then browser then computer-use order, permission before full-screen): https://www.pcworld.com/article/3226763/claude-can-now-click-and-type-in-the-background-while-you-work.html , https://androidauthority.com/claude-background-computer-use-3706684
- [S] Multi-agent dashboards (worktrees, task boards, Vibe Kanban status): https://agentsroom.dev/blog/best-multi-agent-coding-tools (vendor of a competing product, treat with care)
- [S] Claude Code Channels (Telegram/Discord bridge, session must stay alive): https://claudefa.st/blog/guide/development/claude-code-channels
- [S] Voice UX guidance (short turns, confirm high-stakes slots, code painful as audio): https://vapi.ai/playbook/design , https://www.stanza.dev/courses/hermes-voice/push-to-talk/hermes-voice-ptt-flow-design
- [S] Wake-word/speaker verification (Göttingen paper; Home Assistant sensitivity threads): https://uni-goettingen.de/de/document/download/afde83a68eca0eb6ecf4a3f9e41b52c7.pdf/hernandez_acosta_ICCCN2024.pdf
- [1] Open-source Jarvis projects (PanPenek/JarvisAi: openWakeWord, faster-whisper, tool chaining): https://github.com/PanPenek/JarvisAi

---
*Feature research for: always-on voice-first desktop AI assistant (Snow)*
*Researched: 2026-10-13*
