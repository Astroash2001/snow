# Architecture Research

**Domain:** Always-on voice AI desktop assistant ("Snow"): real-time voice agent plus desktop/coding-agent orchestrator, Windows 11 host, Android remote
**Researched:** 2026-10-13
**Confidence:** MEDIUM overall (see per-claim tags)

Confidence tags used below, taken from the classify-confidence seam: **[M]** = web search cross-checked against a fetched official doc page (MEDIUM). **[L]** = single web-search source, or reasoning from established practice that was not re-verified this session (LOW). Nothing here is tagged HIGH, because no Context7 or first-party SDK source was reachable this session. Items tagged [L] are explicit validation-spike candidates, not facts.

---

## Standard Architecture

Real-time voice agents and desktop agents have converged on one shape. A **fast, latency-critical audio plane** is kept separate from a **slower, durable control plane** (the brain, tools, tasks, policy). Every client (HUD, phone, notifications) is a thin subscriber to a single **event stream**. Pipecat, LiveKit Agents and OpenAI-style realtime stacks all follow the same split [M: Pipecat docs describe frame-based pipelines with a system-priority interruption frame that bypasses normal queues; VAD runs locally on CPU].

Snow recommendation: **a TypeScript daemon (`snowd`) is the control plane and the single source of truth. A Python voice sidecar owns the audio plane. The HUD is a separate, crash-isolated web client. PC control is an out-of-process MCP server.** Four process types, one wire protocol.

### System Overview

```
 CLIENTS (thin, swappable, all speak the same WS protocol)
┌───────────────────┐ ┌────────────────────┐ ┌─────────────────────────┐
│ HUD web app       │ │ Phone (PWA over    │ │ Notification actions    │
│ (Electron shell   │ │ Tailscale, same    │ │ (Telegram / ntfy reply  │
│  now; Tauri later)│ │ HUD, small layout) │ │  buttons -> signed URL) │
└─────────┬─────────┘ └─────────┬──────────┘ └────────────┬────────────┘
          │  WS: snapshot + deltas (events) / JSON-RPC commands
══════════╧═════════════════════╧════════════════════════╧═══════════════
 snowd  (Node/TS daemon, one per user session, composition root)
┌────────────────────────────────────────────────────────────────────────┐
│ Remote Gateway  (WS server, auth, artifact HTTP, per-client scopes)    │
├────────────────────────────────────────────────────────────────────────┤
│ EVENT BUS (typed, in-process)  ──append──>  EVENT LOG (SQLite, WAL)    │
│    │  ephemeral signals (audio level, partials, token deltas)          │
│    │  durable facts (heard, plan, action, result, approval)            │
│    └─> PROJECTIONS: presence/mode FSM, task board, pending approvals,  │
│                     day history, HUD view-state snapshot               │
├──────────────┬───────────────┬──────────────┬──────────────────────────┤
│ Orchestrator │ Task Runner   │ Policy /     │ Notification Gateway     │
│ (turn mgr,   │ (durable      │ Approval     │ (sinks: Telegram, ntfy,  │
│ brain loop,  │ queue, leases,│ Engine       │  later native app;       │
│ persona,     │ hand-off,     │ (deterministic│ presence-based routing) │
│ routing)     │ resume)       │ tiers)       │                          │
├──────────────┴───────┬───────┴──────────────┴──────────────────────────┤
│ Tool Registry (risk-tagged)         │ Agent Adapter Layer               │
│  built-in | MCP client | agent.run  │  ACP client | OpenCode HTTP/SSE   │
│                                     │  Claude SDK | PTY fallback        │
├─────────────────────────────────────┴───────────────────────────────────┤
│ Memory Store (SQLite + FTS5 + vectors)  | Secrets (Credential Manager)  │
│ Presence sources (idle time, lock state)| Config + provider Registry    │
└──────┬──────────────────────┬───────────────────────────┬───────────────┘
       │ WS (localhost+token) │ child process (stdio)     │ child procs
       ▼                      ▼                           ▼
┌───────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ snow-voice        │  │ snow-pc (MCP server) │  │ Coding agents        │
│ (Python sidecar)  │  │ UIA tree, SendInput, │  │ claude / opencode /  │
│ mic -> AEC -> wake│  │ screenshots, windows,│  │ gemini / agy ...     │
│ -> VAD -> speaker │  │ volume, files        │  │ (Job Object, resume  │
│ verify -> STT     │  └──────────────────────┘  │  by session id)      │
│ TTS -> playout    │                            └──────────────────────┘
│ (local barge-in)  │          External: LLM gateway (OpenAI-compat),
└───────────────────┘          Cartesia TTS, MCP servers, Tailscale
```

### Component Responsibilities

| Component | Responsibility | Recommended Implementation |
|-----------|----------------|----------------------------|
| **Audio I/O + AEC** | Capture mic, play TTS, echo cancellation, own the playout buffer so barge-in cuts audio locally | Python sidecar (sounddevice/WASAPI), WebRTC-style AEC; **[L] needs a spike on laptop speakers** |
| **Wake word** | Local "Hey Snow" gate, no audio leaves the machine while idle | openWakeWord in sidecar; it bundles an optional Silero-VAD gate on its score and prefers 80 ms-multiple frames [M] |
| **VAD** | Speech start/stop at frame level (barge-in trigger, end-of-turn input) | Silero VAD in sidecar; ~1 ms per 30 ms chunk on one CPU thread (secondary source, verify on-device) [L] |
| **Turn-taking** | Decide the user is *done* (not merely silent) | VAD hangover plus a small end-of-turn model (Pipecat's Smart Turn is the reference design). Turn detection is separate from VAD [M] |
| **Speaker verification** | Only the owner's voice commands Snow | Embedding model in sidecar, run **concurrently** with STT, result gates the transcript commit |
| **STT** | Utterance to text (+ partials for HUD) | faster-whisper (GPU) on VAD-segmented audio. **Not natively streaming**; partials via rolling re-decode, or a streaming model (sherpa-onnx) if partials must be real [L] |
| **TTS** | Streamed text to audio with emotion, word timings | Cartesia WS client **inside the sidecar** so audio never crosses IPC; local fallback voice behind same port |
| **Event bus** | In-process pub/sub, typed, backpressure-aware | Plain typed emitter in `snowd`. No Redis/NATS/Kafka |
| **Event log** | Append-only record of durable facts; feeds HUD, history, audit, task recovery | SQLite WAL (`better-sqlite3` or `node:sqlite`); monotonic `seq` |
| **Projections** | Read models derived from the log (task board, approvals, HUD snapshot, mode FSM) | In-process reducers, written in the same transaction as the event |
| **Orchestrator** | Turn manager + brain loop: context assembly, streaming LLM, tool calls, cancellation | TS; two-tier brain (fast "front" model + stronger "worker" models) |
| **LLM provider port** | Swappable models by *role*, not by name | OpenAI-compatible chat-completions streaming as the lingua franca; config maps role to endpoint/model |
| **Tool registry / MCP layer** | One catalogue of callable things, each with risk metadata | Built-in tools + MCP client (stdio/HTTP) + `agent.run`; per-turn filtered subset exposed to the LLM |
| **Agent adapters** | Normalize coding agents to one event model | ACP client first; native adapters where better; PTY last resort |
| **Task runner** | Durable background work, hand-off, resume after restart | SQLite job table with leases and heartbeats, in-process worker pool |
| **Policy / approval engine** | Deterministic risk tiers, presence-routed approvals, audit | Pure TS rules-as-data; LLM can raise a tier, never lower it |
| **Memory store** | Facts, episodic summaries, task history, retrieval under 50 ms | SQLite + FTS5 + sqlite-vec; async write path via background job |
| **Notification gateway** | Presence-routed push, two-way answers | Sink interface: Telegram (outbound long-poll, no inbound port), ntfy |
| **Remote gateway** | Authenticated WS and artifact HTTP for HUD/phone | Fastify/ws in `snowd`; exposed to phone only via Tailscale |
| **HUD client** | Render state + activity, send commands | Vite + three.js ASCII shader; pure function of (snapshot + deltas) |
| **UI shell** | Tray, window management, transparency, click-through, auto-update | Electron now (see Decision D3); HUD web app is shell-agnostic |
| **PC executor** | UI Automation, input injection, screenshots, system controls | Out-of-process MCP server (Python: uiautomation/pywinauto + mss), user-session, same integrity as target apps |
| **Supervisor** | Spawn, health-check, restart sidecars and agents | Inside `snowd`; Windows Job Objects so children die with the parent |

---

## Key Architectural Decisions (opinionated)

### D1. Process model: Task Scheduler daemon, NOT a Windows Service  [L: standard Windows behaviour, not re-verified]
Windows Services run in Session 0, isolated from the interactive desktop, with no access to the user's audio endpoints, UI Automation tree or SendInput targets. Snow needs all three. Run `snowd` as a **per-user process launched by a Task Scheduler "At log on" task** (restart-on-failure, no time limit) or an HKCU Run entry. `snowd` stays alive when the HUD is closed or crashes; voice keeps working headless. `snowd` supervises children.

### D2. Language split: TypeScript control plane, Python audio/ML plane
- The control plane is long-lived, I/O-bound, and talks to JS-first SDKs (ACP, MCP, Claude Agent SDK, ntfy/Telegram clients) and the TS/JS HUD. Shared zod schemas become the single contract.
- Python is confined to the GPU/ML hot path (openWakeWord, Silero, faster-whisper, speaker model) and UI automation libraries. A native CUDA/ONNX crash kills the sidecar only; the supervisor restarts it in seconds.
- Alternative considered: all-Python (Pipecat as the whole app). Rejected: HUD, agent SDKs and MCP still force a second runtime, and a monolith couples ML crashes to task state. Pipecat is still the best *design reference* for the sidecar, and a spike should decide whether to adopt it as the sidecar's internal framework or hand-roll a small asyncio pipeline. Default: hand-roll the small pipeline, copy its ideas (typed frames, system-priority interrupt, upstream/downstream).
- **Python 3.10 is at/near end of life as of Oct 2026 [L].** Pin the sidecar to a uv-managed 3.12 environment, not the system 3.10.

### D3. UI shell: Electron now, HUD built shell-agnostic  [L]
The HUD must be a plain web app that talks only to the WS protocol. Then the shell is replaceable: Electron today (bundled Chromium gives identical WebGL behaviour, transparent/click-through/always-on-top windows, mature auto-updater, same language as `snowd`), Tauri later if idle memory matters (Tauri 2 uses WebView2 on Windows, i.e. Chromium, so the same WebGL code should port; reported idle footprints of ~30-50 MB vs ~150-300 MB are rough and unverified [L]). The same web bundle is served to the phone as a PWA. **Do not make Electron's main process the daemon**: a HUD crash must not take Snow down.
GPU note: the laptop is hybrid (Intel iGPU + RTX 4050). Pin the HUD shell to the iGPU in Windows Graphics settings so the ASCII shader never competes with faster-whisper for the 6 GB NVIDIA card.

### D4. IPC: one WebSocket protocol everywhere, JSON-RPC 2.0 framing
- `snowd <-> sidecar`, `snowd <-> HUD`, `snowd <-> phone` all use **WebSocket on loopback (or tailnet) with JSON-RPC 2.0** for commands and server-pushed event notifications. Same shape as MCP and ACP, which both use JSON-RPC 2.0 [M].
- Why not gRPC: protobuf codegen across TS/Python/browser plus grpc-web adds toolchain weight for a low-bandwidth link (the sidecar sends transcripts and VAD flags, not raw audio). Why not named pipes: Windows-only and unreachable from the browser HUD, so you would maintain two transports.
- Raw audio **never** crosses IPC in the normal path (capture, VAD, STT, TTS and playout all live in the sidecar). That is what keeps barge-in under ~50 ms and the wire protocol small. A binary side-channel exists only for the "sidecar-less" debug mode and for streaming TTS audio to a remote client later.
- Loopback is not trusted: any local process can connect. Every connection needs a per-launch random token (file ACL'd to the user) delivered to children via env var.
- One schema source: define events/commands in zod in `packages/protocol`, generate JSON Schema, generate pydantic models for the sidecar in CI. Never hand-sync types.

### D5. Event-sourced *activity log*, not an event-sourced domain model  [L: judgement]
Full event sourcing of every aggregate is overkill for one user. What the HUD, the day history, the task board and the audit trail need is an append-only, replayable record of what Snow heard, decided and did. So:
- **Two event classes.** *Durable facts* (`heard.final`, `intent`, `plan`, `action.started`, `action.result`, `approval.requested`, `approval.resolved`, `task.state_changed`, `agent.tool_call`, `speech.spoken`) are written to SQLite and given a `seq`. *Ephemeral signals* (audio level, VAD flags, STT partials, LLM token deltas, terminal chunks) are only broadcast, never stored; the *coalesced final* (full utterance, full message, final terminal blob) is the durable fact.
- Projections are SQLite tables updated in the **same transaction** as the event append. Restart recovery is "load tables", not "replay the world". Replay exists for debugging, rebuilding a projection, and client catch-up.
- Event envelope: `{ seq?, ts, type, source, correlation_id (turn/task), causation_id, actor, user_id, payload }`. `user_id` from day one costs nothing and keeps "others later" possible.
- Large payloads (screenshots, diffs, terminal blobs, page captures) are **artifacts** stored on disk by content hash; events carry `artifact_id`. The HUD fetches `/artifacts/:id` over the same authenticated HTTP. Keeps the log small and the stream fast.
- A **secret scrubber** sits at bus ingress, before the log. Screenshots/OCR of password fields and clipboard contents are the realistic leak path; add retention limits on artifacts.

### D6. Streaming everywhere, with cancellation as a first-class citizen
Every turn gets a `turn_id` and one `AbortController` that fans out to: LLM stream, tool calls that are cancellable, TTS stream, and sidecar playout. Barge-in = abort that turn. No stage waits for the previous stage to *finish*, only to produce its first unit (token to sentence to TTS chunk to audio).

### D7. Single input funnel
Voice, HUD clicks, typed text, phone taps and notification action buttons all become `Command`/`Intent` events entering the same orchestrator/policy path. "Silent mode" is just an output-sink switch (speech sink muted, HUD sink on). This is what lets approvals resolve from any channel with identical audit.

---

## Recommended Project Structure

```
snow/
├── packages/
│   ├── protocol/        # zod schemas: events, commands, envelope; emits JSON Schema + pydantic
│   ├── core/            # event bus, event log, projections, config loader, provider registry, logging
│   ├── brain/           # orchestrator, turn manager, sentence chunker, persona/context assembly, LLM port
│   ├── voice-client/    # TS side of the sidecar link (VoicePort), plus a FAKE voice port for tests
│   ├── agents/          # AgentAdapter port; acp/, opencode/, claude-sdk/, pty/ implementations; router+health
│   ├── tools/           # tool registry, risk metadata, MCP client manager, built-in tools
│   ├── policy/          # tier classifier, approval objects, presence routing, taint rules
│   ├── tasks/           # durable queue, leases, hand-off envelope, resume/reconcile
│   ├── memory/          # stores, retrieval, background extraction, Embedder port
│   ├── notify/          # NotificationSink port; telegram/, ntfy/; signed action tokens
│   ├── presence/        # PresenceSource port; idle time, session lock, device-on-tailnet
│   └── remote/          # WS server, auth/pairing, client scopes, artifact HTTP
├── apps/
│   ├── snowd/           # composition root: wires ports to adapters from config, supervisor
│   ├── hud/             # Vite + three.js app: store (reducer over events), scene, panels, design system
│   └── shell/           # Electron: tray, windows, auto-update, GPU pinning
├── sidecars/
│   ├── voice/           # Python: audio, AEC, wake, VAD, speaker, STT, TTS, playout (uv project)
│   └── pc/              # Python MCP server: UIA, SendInput, screenshots, system controls
├── tests/
│   ├── harness/         # headless scripted-voice + scripted-LLM end-to-end driver
│   └── contract/        # one suite per port; every adapter must pass it
└── installer/           # packaging, Task Scheduler registration, bundled runtimes
```

### Structure Rationale
- **`packages/*` are ports + pure logic; `apps/snowd` is the only place that picks implementations from config.** This is how every component becomes swappable: nothing imports a concrete adapter except the composition root.
- **`protocol` is a leaf package** every other package and both sidecars depend on; it is the single source of truth for the wire.
- **`tests/contract`** is the swappability guarantee in code: Cartesia and the local fallback voice, or Claude-via-ACP and OpenCode-native, pass the same suite, so "auto-switch when unavailable" is testable.
- **`tests/harness`** matters for the production-quality bar: CI cannot talk into a microphone, so the voice port has a fake (WAV fixtures in, transcripts and timings out) and the LLM port has a scripted provider.

---

## Architectural Patterns

### Pattern 1: Ports and adapters with role-based config
**What:** Every external capability is a TS (or Python) interface selected by a config key. Ports: `Stt`, `Tts`, `WakeWord`, `Vad`, `SpeakerVerifier`, `LlmProvider`, `Embedder`, `AgentAdapter`, `ToolProvider`, `NotificationSink`, `PresenceSource`.
**When to use:** Always; it is the answer to "free credits now, paid API later" and "agents come and go".
**Trade-offs:** Slight indirection; needs contract tests or the abstraction rots.

```typescript
// config selects by ROLE; code never names a model
interface LlmProvider {
  stream(req: ChatRequest, signal: AbortSignal): AsyncIterable<LlmDelta>; // text, tool_call, usage
}
// snow.config.yaml
// llm: { front: deepseek-v4-flash@gateway, worker: gpt-5.6-luna@gateway, vision: qwen3.8-27b@gateway }
// tts: { primary: cartesia, fallback: local-piper }
// agents: { order: [claude-acp, opencode, antigravity], failover: auto }
```

### Pattern 2: Two-tier brain (fast front, strong supervisor)
**What:** A low-latency "front" model owns the conversation (acknowledgements, clarifying questions, spoken summaries) and delegates substantive work to a stronger model or an agent via tools (`start_task`, `agent.run`, `computer_use`). Same idea as OpenAI's "chat + supervisor" realtime pattern [L].
**When to use:** Needed to hit ~1 s to first audio while the main model has a 300-800 ms time-to-first-token and the gateway latency is unconfirmed.
**Trade-offs:** Two prompts to keep coherent; the front must see a compact state snapshot (running tasks, pending approvals) to stay honest. Wording is still LLM-generated: no canned filler lines, per the project requirement.

### Pattern 3: Normalized agent events, adapter per protocol
**What:** One `AgentAdapter` port; normalized `AgentEvent` union: `message.delta | thought | plan | tool.call | tool.update | diff | terminal.output | permission.request | question | status | done | error`. The orchestrator and HUD never see a vendor format.
**When to use:** Always for coding agents.
**Trade-offs:** Lowest-common-denominator risk; keep an `extra` passthrough field for adapter-specific data.

```typescript
interface AgentAdapter {
  readonly id: string;
  capabilities(): { resume: boolean; steer: boolean; permissions: boolean; questions: boolean };
  health(): Promise<{ ok: boolean; reason?: "auth" | "quota" | "missing" | "crash" }>;
  start(spec: { cwd: string; prompt: string; resumeId?: string }): AgentSession;
}
interface AgentSession {
  events: AsyncIterable<AgentEvent>;
  send(text: string): Promise<void>;          // steer ("stop, use Postgres")
  cancel(): Promise<void>;
  answer(requestId: string, decision: Decision | string): Promise<void>;
  sessionId: string;                           // persisted by the task runner for resume
}
```

Adapter strategy, in priority order (verified facts marked):
1. **ACP client (one implementation, many agents).** ACP is JSON-RPC 2.0 between a client and an agent subprocess; agents implement `initialize`, `session/new`, `session/prompt`, `session/cancel`, optional `session/load`, and stream `session/update` notifications (message/thought chunks, tool calls and updates, plans, mode changes). The agent calls back into the client with `session/request_permission`, plus optional `fs/*` and `terminal/*` and `elicitation/create` [M, agentclientprotocol.com protocol overview]. The ACP agent directory lists Claude (via Zed's `claude-agent-acp` adapter), Gemini CLI, OpenCode, Codex CLI (via `codex-acp`), Qwen Code, Goose, Kimi CLI and many more [M]. This covers most of the user's rotation with one adapter.
   - Design insight [L]: if Snow advertises the `fs` and `terminal` client capabilities, the agent routes file writes and shell through Snow. That makes Snow's policy engine a real choke point and gives the HUD live terminal output for free.
2. **OpenCode native HTTP + SSE.** `opencode serve` (default 127.0.0.1:4096, basic auth via `OPENCODE_SERVER_PASSWORD`), `POST /session`, `POST /session/:id/prompt_async` (204, fire and forget), `GET /event` SSE (first event `server.connected`), `POST /session/:id/permissions/:permissionID` with `response` and `remember` [M, opencode.ai/docs/server]. A Rust SDK README advises treating SSE as best-effort and reconciling via `GET /session/:id/message` [L]: do the same. Use if ACP proves lossy.
3. **Claude Agent SDK direct.** `canUseTool` fires only for requests not already resolved by hooks, deny rules or the permission mode; it may stay pending indefinitely; `AskUserQuestion` also routes through it; modes can change mid-stream [M, code.claude.com/docs/en/agent-sdk/permissions]. Prefer ACP unless a feature is missing. **Verify the terms for using a subscription login through any SDK/adapter before depending on it** [L].
4. **PTY adapter (`node-pty`) fallback** for CLIs with no protocol (Antigravity's headless story is **unverified** [L]; research in the agents phase). Parse minimal state (idle/working/asking); lowest fidelity, HUD shows raw terminal.

**Agent lifetime:** spawn under a Windows Job Object so they die with `snowd`; durability comes from **session resume ids**, not process immortality. The task runner stores `(adapter, agent_session_id, cwd, last_seq)` and calls `resume`/`session/load` after a restart.

### Pattern 4: Deterministic policy gate between "decide" and "do"
**What:** Every tool call and every agent `permission.request` passes through the policy engine. Tiers: T0 read-only (silent), T1 routine mutation (auto, visible on HUD), T2 risky (announce, then ask or timed-proceed depending on presence), T3 always-ask (credentials, security settings, payments, irreversible deletion). Classification = static tool metadata + argument inspection (path globs, `rm -rf`, `git push --force`, registry, installer commands) + **taint escalation** (an action suggested by content from web pages, emails or MCP output is bumped a tier).
**When to use:** Always; it is a stated hard requirement.
**Trade-offs:** Rules need upkeep; start strict and relax from the audit log. The LLM may propose a higher tier but can never lower one. Timeouts default to deny.

Approval = durable object `{id, action_hash, tier, requested_via[], expires_at, state}`. Resolved by the first valid response from any channel (voice, HUD click, phone, notification button); idempotent; written to the event log. Routing by presence: at PC means voice plus HUD, away means phone push, locked or idle means phone. **T3 approvals must not be satisfiable by voice alone** (replayed or synthesized audio defeats speaker verification); require a HUD click or phone tap as a second factor [L: security reasoning].

### Pattern 5: Durable task runner with hand-off envelope
**What:** A task is `{id, goal, adapter, cwd, constraints, approval_policy_snapshot, notify_policy, state, agent_session_id, heartbeat_at, lease_owner}` in SQLite. States: `queued, running, waiting_user, paused, succeeded, failed, cancelled, interrupted`. Workers take a lease and heartbeat. On `snowd` start a reconciler finds `running` tasks with stale heartbeats and resumes or marks `interrupted`. "Hand off and walk away" = freeze the policy snapshot for the *away* presence mode and set notification routing.
**When to use:** Anything lasting beyond one conversational turn.
**Trade-offs:** Use plain SQLite; BullMQ/Redis is wrong for a Windows single-user app (extra service, no gain).

### Pattern 6: Snapshot-plus-delta event streaming to clients
**What:** On connect the client sends `subscribe{topics, since_seq?}`. Server replies with a **projection snapshot at seq N**, then streams deltas `> N`. Durable events carry `seq` (client detects gaps and re-syncs); ephemeral events carry a monotonic `eph` counter and are droppable.
**Backpressure:** ephemeral streams are coalesced (latest-wins per key for audio level at ~30 Hz; token deltas batched per animation frame, ~16 ms); slow clients lose ephemeral frames, never durable ones.
**HUD derivation rule:** the HUD state (`idle | listening | thinking | acting | speaking | alert`) is computed **once in `snowd`** by a mode FSM and broadcast; clients do not each re-derive it, so desktop, corner widget and phone never disagree.

### Pattern 7: Local barge-in with spoken-offset truncation
**What:** The sidecar owns playout. On verified user speech during playback (VAD above a short minimum duration, so backchannels like "mm-hm" don't cut Snow off) it stops audio locally, then emits `playback.interrupted{spoken_ms, spoken_text}`. `snowd` aborts the turn and **truncates the assistant message in history to what was actually heard** (using Cartesia word timestamps [L: confirm availability]). Without truncation, the model believes it said things the user never heard.

---

## Data Flow

### Key Data Flows

**1. Voice turn (hot path; latency budget targets)**
```
mic ─> AEC ─> wake (idle only) ─> [HUD: listening <100ms via mode FSM]
     ─> VAD+turn model ─> segment ─┬─> STT (GPU) ──────────────┐
                                   └─> speaker verify (parallel)┴─> gate ─> heard.final
heard.final ─> Orchestrator ─> context (persona + memory<50ms + state snapshot)
            ─> front LLM stream ─> sentence chunker (+ emotion header parse)
            ─> TTS stream (sidecar) ─> playout        [HUD: speaking]
tool call mid-stream ─> policy ─> tool/agent ─> events ─> HUD, result back to LLM
```
Rough budget for the ~1 s target (**[L] estimates to validate with per-stage timing events from day one**): end-of-speech hangover 200-400 ms, STT final 100-300 ms (GPU, short utterance), LLM TTFT 300-500 ms, TTS first audio ~100-200 ms. It only fits if stages overlap: start the LLM call speculatively on a stable end-of-turn and cancel it if the user resumes (preemptive generation); keep the speaker check off the critical path. An end-of-turn hangover of 500-800 ms is common default advice [L] and would blow the budget: tune it down and lean on the turn model.

**2. Voice-driven coding with questions back**
```
"Hey Snow, add auth to the API"
 ─> front LLM calls start_task(goal, adapter=auto) ─> Task Runner ─> AgentAdapter.start
 ─> AgentEvent stream ─> normalize ─> bus ─> (durable: tool.call, diff, plan; ephemeral: deltas)
        ├─> HUD panels (diff, terminal, plan)
        └─> Orchestrator watches for permission.request / question / done
permission.request ─> Policy ─(T0/T1)─> auto-allow + log
                                 (T2/T3)─> Approval object ─> present:
                                     at PC: LLM-worded spoken question + HUD card
                                     away : Notification Gateway push
user answers (voice/HUD/phone) ─> Approval resolved ─> adapter.answer ─> agent continues
done ─> LLM writes 1-2 sentence spoken summary; code/diffs stay on HUD only
```

**3. Hand-off and return**
```
"Take this, I'm leaving" ─> task envelope frozen (away policy) ─> presence = away
 ... needs decision ─> Approval ─> Notification Gateway ─> Telegram/ntfy (minimal text)
 phone tap ─> signed single-use action token OR authenticated PWA over Tailscale
          ─> Remote Gateway ─> Approval resolved ─> task resumes
 return ─> presence = at-PC ─> HUD shows task board projection (done / running / waiting)
```

**4. Barge-in** (see Pattern 7): sidecar playout stop (<~50 ms, local) then `playback.interrupted` then `snowd` aborts LLM/TTS/cancellable tools, truncates history, opens a new turn.

**5. HUD live view:** bus to Remote Gateway to WS fan-out; artifacts via HTTP; commands (approve, interrupt, silent mode, typed input) return as JSON-RPC calls into the same funnel as voice (D7).

### State Management

```
Event Log (truth for activity)  ──projections──>  SQLite read tables
        │ live fan-out                                   │ snapshot on connect
        ▼                                                ▼
  ephemeral signals ───────────>  HUD store (reducer: snapshot + deltas)
                                         │ pure render
                                         ▼
                                three.js ASCII scene + panels
```

---

## Scaling Considerations

Single user now; the realistic scaling axes are *data volume*, *concurrent agents* and *GPU memory*, not users.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 user, this laptop | Everything above. SQLite, in-process bus, one daemon. Budget GPU: STT plus speaker model within 6 GB VRAM; no local LLM. |
| "Others later" (few installs) | Already free: `user_id` on events/tasks/memory, per-user data dir, no global singletons, config-driven providers. Add auth/pairing per device. Still no server. |
| Hosted/multi-tenant (not planned) | Would require splitting `snowd` per user behind a gateway and replacing loopback trust. Explicitly out of scope; do not build for it. |

### Scaling Priorities
1. **First bottleneck: event-log growth** (screenshots, terminal output). Fix: artifact store with retention, coalesced durable events, periodic compaction of old ephemeral-derived rows.
2. **Second bottleneck: GPU/CPU contention** (whisper plus HUD shader plus agents building code on 12 cores). Fix: HUD on iGPU, render loop paused when hidden or occluded, sidecar process priority above agents, cap concurrent agent sessions.

---

## Anti-Patterns

### Anti-Pattern 1: Raw audio through the orchestrator
**What people do:** Stream mic audio to the main process over a socket, VAD/STT there, send TTS audio back.
**Why it's wrong:** Adds hops to barge-in and ties audio glitches to orchestrator load.
**Do this instead:** Audio plane lives wholly in the sidecar; only text, flags and timings cross the wire.

### Anti-Pattern 2: Windows Service for the daemon
**What people do:** Install as a service for "always-on".
**Why it's wrong:** Session 0 isolation breaks audio devices, UI Automation and input injection.
**Do this instead:** Per-user Task Scheduler logon task with restart-on-failure; supervisor inside.

### Anti-Pattern 3: LLM decides what needs approval
**What people do:** Ask the model "is this dangerous?".
**Why it's wrong:** Non-deterministic, injectable via web or MCP content, unauditable.
**Do this instead:** Rules-as-data policy; model can only escalate.

### Anti-Pattern 4: Vendor message formats leak upward
**What people do:** Orchestrator parses Claude-specific or OpenCode-specific events.
**Why it's wrong:** "Switch agents by voice or automatically" becomes a rewrite.
**Do this instead:** Normalized `AgentEvent` plus adapter contract tests.

### Anti-Pattern 5: Electron main process = the daemon
**What people do:** Put the brain in the UI process because it is already Node.
**Why it's wrong:** HUD crash, GPU reset or renderer hang kills voice and background tasks; headless mode impossible.
**Do this instead:** `snowd` independent; shell is a client that can be killed freely.

### Anti-Pattern 6: Persist every token and rebuild state by replaying everything
**What people do:** Full event sourcing with all deltas stored.
**Why it's wrong:** Log bloat, slow startup, slow HUD connect.
**Do this instead:** Durable facts plus coalesced finals; projections in-transaction; snapshot-plus-delta for clients.

### Anti-Pattern 7: Exposing all tools to the model every turn
**What people do:** Register every MCP tool in one prompt.
**Why it's wrong:** Accuracy drops, latency rises, attack surface grows (tool descriptions are untrusted text).
**Do this instead:** Registry returns a per-turn subset (by task state/intent, with the front model getting only delegation tools); treat tool descriptions and outputs as data, not instructions.

### Anti-Pattern 8: Trusting loopback and a public push topic
**What people do:** Unauthenticated localhost WS; secrets in ntfy topic messages.
**Why it's wrong:** Any local process or topic-guesser can command Snow or read details.
**Do this instead:** Per-launch token, device pairing, Tailscale-only remote, minimal push text ("Task needs a decision") with details behind authenticated remote HUD; Telegram chat-id allowlist; single-use signed approval tokens bound to the `action_hash`.

### Anti-Pattern 9: Hand-synced types between TS and Python
**Do this instead:** Generate pydantic from the zod-derived JSON Schema in CI; fail the build on drift.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| LLM gateway (GPT-5.6 Luna, DeepSeek V4 Flash, Qwen3.8 27B) | OpenAI-compatible streaming via `LlmProvider` | Compatibility and tool-calling support are **unconfirmed** in PROJECT.md; first-phase spike. Model fallbacks per role. |
| Cartesia TTS | WS streaming client inside the sidecar | Emotion + word timestamps support to confirm in docs; credits exhausted triggers local fallback voice. |
| Telegram Bot API | Outbound long-polling only (no open port); inline keyboard for approve/deny | Not end-to-end encrypted: keep content minimal; allowlist chat id. |
| ntfy | HTTP publish; action buttons call back to an authenticated URL | Public server sees content: minimal text, secret topic, or self-host. |
| Tailscale | Phone reaches `snowd` Remote Gateway; prefer `tailscale serve` TLS proxy in front of loopback [L] | Still require device pairing token at app layer. |
| MCP servers | Stdio/HTTP clients supervised by tool layer | Namespace tool names; per-server risk defaults; outputs untrusted. |
| Coding agents | See Pattern 3 | Version-pin adapters (`claude-agent-acp`, `codex-acp`); they change fast. |
| Windows | Credential Manager (secrets), Task Scheduler (autostart), Job Objects (child lifetime), WTS session notifications + `GetLastInputInfo` (presence), UI Automation + SendInput (control) | UIPI: a non-elevated process cannot drive elevated windows; decide how elevated apps are handled (announce limitation vs. elevated helper) [L]. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Remote Gateway <-> Bus | Subscribe/command calls | Only door for clients; applies per-client scopes (phone cannot trigger local mic or T3 approvals without second factor) |
| Orchestrator <-> Voice port | `VoicePort` interface (events in, `speak(stream)`/`stop()` out) | Fake implementation for tests |
| Orchestrator <-> Policy | Synchronous `decide(action)` returning allow / ask / deny | Policy never calls the LLM |
| Orchestrator <-> Task Runner | `startTask`, `steer`, `cancel`, events | Runner is the only caller of AgentAdapter |
| Agent Adapters <-> Policy | `permission.request` events flow up; decisions flow down | Also covers `fs/*`/`terminal/*` if advertised in ACP |
| Tools <-> snow-pc | MCP over stdio | Process isolation; reusable by coding agents later |
| Anything <-> Memory | Read: sync, <50 ms, no LLM. Write: async job after the turn | Extraction by the fast model in background |
| Snowd <-> Supervisor children | WS heartbeat + Job Object | Backoff restart, crash events surface on the HUD |

---

## Suggested Build Order (dependencies drive the phases)

```
0 Foundations ─> 1 Glass-box skeleton ─> 2 Voice plane ─> 3 Brain
                                                    │          │
                                          (speaker verify)     ▼
                                                    └──> 4 Policy + Tools ─> 5 Agent adapters
                                                                                  │
                                                  6 Tasks/presence/notify/remote <┘
                                                                  │
                                                       7 PC control + computer use
 8 ASCII 3D HUD art/motion   (spike in 1, full build parallel from 3 onward)
 9 Packaging / auto-update   (spike in 2, full after 6; CI from 0)
```

1. **Phase 0, Foundations.** Monorepo, CI, lint/type/test, `protocol` schemas (envelope, commands), bus, SQLite log + projections, provider registry/config, structured logging, secrets, headless test harness. *Everything else depends on the envelope and registry; retrofitting them is the most expensive rework.*
2. **Phase 1, Glass-box skeleton.** `snowd` + Remote Gateway + a bare HUD event viewer in the Electron shell + supervisor + Task Scheduler autostart. Observability first means every later component is visible as built. Include a **WebGL/ASCII-shader perf spike on the iGPU** here to de-risk the HUD identity early.
3. **Phase 2, Voice plane.** Sidecar: audio I/O, AEC, wake, VAD, turn model, STT, TTS (Cartesia plus local fallback), playout, local barge-in, **speaker verification** (must exist before any action-capable tool), per-stage latency events. Echo-brain only (no LLM yet). Gate: measured latency budget on the real laptop.
4. **Phase 3, Brain.** LLM port with role config and gateway spike, orchestrator turn manager, streaming sentence chunker, emotion header, persona, cancellation + spoken-offset truncation, minimal memory (facts, summaries), two-tier routing.
5. **Phase 4, Policy engine + tool registry + MCP client.** *Before* any tool that acts. Tiers, approval objects, presence service (initially at-PC only), built-in safe tools (open app, volume).
6. **Phase 5, Agent adapters.** ACP client first (Claude via adapter, OpenCode, Gemini), permission/question relay by voice, normalized events into HUD panels, router/failover. OpenCode-native and PTY adapters only if ACP gaps appear. Research flag: Antigravity.
7. **Phase 6, Task runner, hand-off, presence, notifications, phone.** Durable queue, resume, away policy, Telegram/ntfy sinks, signed approval tokens, Tailscale remote with pairing, phone layout of the same HUD.
8. **Phase 7, PC control.** `snow-pc` MCP server: UIA-tree-first control (fast, deterministic), screenshot-plus-vision fallback loop with step budget and per-step events, browser tasks with existing sessions, dev-environment tools. Highest-risk actions, hence last and fully behind policy.
9. **Phase 8, HUD art and motion** (spans phases): states, activity stream, panels, design system, adaptive layouts, silent mode, "reason shown" chips.
10. **Phase 9, Packaging and operations:** installer bundling Node + uv-managed Python + CUDA runtime DLLs for faster-whisper (large), auto-update, health dashboard, log rotation.

Research flags for the roadmap: Phase 2 (AEC on laptop speakers, true-streaming STT vs faster-whisper chunking, speaker-verification robustness on short utterances, Cartesia emotion/timestamp API), Phase 3 (gateway tool-calling and latency), Phase 5 (Antigravity headless interface, ToS of subscription auth via SDK/adapters), Phase 7 (UIPI/elevated windows, vision-model cost/latency). Phases 0, 1, 4, 6 use standard patterns.

---

## Sources

- Agent Client Protocol overview and agent list (fetched): https://agentclientprotocol.com/protocol/overview ; https://agentclientprotocol.com/overview/agents  [M]
- OpenCode server docs (fetched): https://opencode.ai/docs/server/  [M]; Rust SDK README on SSE reconciliation (via search): https://docs.rs/crate/opencode-codes/1.18.5/source/README.md  [L]
- Claude Agent SDK permissions and canUseTool (search results, official domain): https://code.claude.com/docs/en/agent-sdk/permissions ; https://platform.claude.com/docs/en/agent-sdk/user-input  [M]
- Pipecat docs on speech input / VAD / interruption frames (search results, official domain; one fetch 404'd): https://docs.pipecat.ai/learn/speech-input ; https://docs.pipecat.ai/api-reference/server/frames/system-frames.md  [M]. Note a third-party guide reports `allow_interruptions` semantics changed between versions: check the installed version.
- LiveKit Agents overview (fetched; sparse, confirms STT-LLM-TTS pipeline and a LiveKit-server-centric connection model): https://docs.livekit.io/agents/  [L for specifics]
- openWakeWord PyPI page (Silero VAD gating, 80 ms frames): https://pypi.org/project/openwakeword  [M]
- Tauri vs Electron comparisons (mixed-quality blogs, footprint numbers unverified): https://blog.openreplay.com/comparing-electron-tauri-desktop-applications/  [L]
- Not verified this session and carried as [L]: Windows Session 0 isolation specifics, Python 3.10 EOL date, Tailscale Serve identity headers, Cartesia emotion/word-timestamp API, Antigravity CLI headless mode, speaker-verification model cost, AEC options on Windows.

---
*Architecture research for: always-on voice AI desktop assistant (Snow)*
*Researched: 2026-10-13*
