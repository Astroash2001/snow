# Gap study: Codync and OpenMausBot vs Snow

Date: 2026-10-19. Method: shallow clones, read only, never built, run or imported. Instruction files inside the repos were treated as data. Two readers went through the code in parallel (Codync `host/src`, `relay/`, `cloud/`, tests; OpenMausBot `server/`, `shared/`, `companion/`, `electron/`, `evals/`, docs and specs). I then spot-checked the load-bearing claims against the source (constants, comments and invariants quoted below were grepped). On the Snow side: `.claude/CLAUDE.md`, `.planning/PROJECT.md`, `ROADMAP.md`, `REQUIREMENTS.md`, `research/ARCHITECTURE.md`, both fullstack-agent seed files, and `src/snow/hub/{server,supervisor}.py`.

**This study does not repeat the fullstack-agent seed.** Where a finding deepens a seed item, it says so (for example "deepens seed B6").

## 0. Repos and licences

| Project | Repo | How sure | Licence |
|---|---|---|---|
| Codync | https://github.com/leepokai/Codync | High. The Product Hunt and launch posts name it, and the code matches the description: host daemon, phone apps, relay, "persistent named bots". | Apache-2.0 (`LICENSE`, `NOTICE`). The press said MIT; the repo says Apache-2.0. |
| OpenMausBot | https://github.com/milind-soni/OpenMausBot | High. The listings name it, and the README and code match "a team of AI bots in a chat app". | Apache-2.0 except `enterprise/`, which is source-available (`LICENSING.md`, `enterprise/LICENSE`). I did not study `enterprise/`. |

Neither licence is copyleft. Even so, everything below is an idea in Snow's own design and copies no code. The trademarks (Codync, OpenMausBot, MausBot) are not to be reused.

## 1. What they are, in one paragraph each

**Codync** is a Rust daemon, `codync-host`, that drives coding agents **over ACP only**. It knows 27 curated harnesses (Claude, Codex, Cursor, OpenCode, Gemini, Antigravity `agy` and more) plus the official ACP registry. Clients are iPhone and Android apps, an Electron desktop app and a TUI. They reach the host directly (LAN or Tailscale) or through a Cloudflare Durable Object relay, over the host's own end-to-end encrypted channel (X25519, Ed25519, ChaCha20-Poly1305). Each "bot" is a persistent named agent with its own cwd, model, permission mode, memory and routines (cron, webhook, event). Bots can call each other through an injected `team` MCP. Windows is supported but second class.

**OpenMausBot (OMB)** is a TypeScript harness on 127.0.0.1:8799 with an Electron and React chat UI. Each bot is a chat contact with an engine (Claude through the raw CLI with stream-json, Codex app-server, about 15 ACP CLIs, OpenAI-compatible APIs), a persona ("soul"), memory, Composio app connectors, an approval level and optionally its "own computer" (a Docker or Podman Cua XFCE VM, a cloud box, a per-bot Chrome profile). A "Chief of Staff" bot delegates through a durable assignment tree. Its phone access is a default-deny companion sidecar over a Cloudflare Tunnel or Tailscale, with APNs push only. It also has a voice mode and a delegating "live call".

**Neither one attaches to agent sessions the user started by hand.** That stays seed F4 (hooks mirror).

## 2. Gaps by area

Format for each gap:
- **They:** what they do, with paths in their repo.
- **Snow:** what Snow has, with Snow paths, or "planned Phase N", or "missing".
- **Value / Effort / Phase.**
- **Idea:** a one-line idea in Snow's own design.

### A. Driving coding agents (Phases 2 and 3)

**A1. Steering a running turn needs a three-state result, and ACP cannot steer at all**
- **They:** OMB `docs/specs/steer-vs-queue.md` and `docs/specs/aside-injection-seams.md`, `server/steer-queue.ts`, and `ProviderAdapter.steer` in `server/contracts.ts`.
  - `steer()` returns one of three results:
    - `steered`: accepted into the live turn.
    - `refused`: provably not delivered, so it is safe to queue.
    - `indeterminate`: delivered, but the outcome is unknown. **Never re-queue it**, because "running them twice is the one mistake this lane must never make".
  - Claude takes mid-turn input as a stdin user message in stream-json. Codex has `turn/steer`.
  - **ACP has no mid-turn input by protocol.** The only mid-turn call is `session/cancel`. So an ACP driver must not fake steering by interrupting and re-prompting. It queues instead, and the UI says so honestly.
  - Codync (`agent/bot/queue.rs next_in_queue`) folds every message sent while busy into one next turn.
- **Snow:** AGNT-07 ("stop, use Postgres instead") is planned for Phase 3. The adapter contract in AGNT-09 (start, send, stream, question, permission, stop) has no steer semantics. Research `ARCHITECTURE.md` Pattern 3 assumes ACP covers most agents.
- **Value:** High. **Effort:** S (contract) to M. **Phase:** 2 (contract), 3 (behaviour).
- **Idea:** add `steer(text) -> steered | refused | indeterminate` and `capabilities.mid_turn_input` to the adapter contract.
  - The voice router decides between "redirect now" (steer if capable, else cancel and re-prompt, which Snow *announces* as an interrupt) and "after this" (queue and fold).
  - An indeterminate steer is logged once and never replayed.

**A2. Isolate the agent you spawn from the user's own setup, and keep the subscription login intact**
- **They:** OMB `server/drivers/claude.ts`:
  - `--setting-sources project` and `--strict-mcp-config`, so the user's `~/.claude` settings and MCP servers do not leak in.
  - `--mcp-config` is written to a 0600 temp file, because "argv is readable via `ps`".
  - It deletes `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT`. Their comment: "an inherited ANTHROPIC_API_KEY would flip a subscription login to pay-as-you-go".
  - Named accounts are separate `CLAUDE_CONFIG_DIR`s (`server/claude-accounts.ts`), and tokens are never stored.
  - On Windows, an argv length guard (`assertSafeCliArgv`, ENAMETOOLONG) moves prompts and config off argv.
  - Codync (`agent/own_memory.rs`, `bot/launch.rs claude_meta`) sets `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `autoMemoryEnabled:false` and `autoDreamEnabled:false`, and uses `systemPrompt.append` with `excludeDynamicSections:true` so the prompt cache survives.
- **Snow:** `hub/supervisor.py scrub_env` drops every variable whose name contains KEY, TOKEN, SECRET or PASSWORD, and *adds* `SNOW_HUB_URL` and `SNOW_TOKEN`. That suits Snow's own workers, but it is wrong for an agent child (see A9). The agent spawn spec is not designed yet; that is planned for Phase 2.
- **Value:** High. **Effort:** S. **Phase:** 2.
- **Idea:** give agents a separate `agent_env()` built from an allowlist, not a denylist:
  - no `SNOW_*`, no `ANTHROPIC_API_KEY` unless the profile says API mode, no `CLAUDECODE*`;
  - the prompt goes over stdin or a 0600 file;
  - project-only setting sources;
  - Claude auto-memory off when Snow memory is on (deepens seed A7).

**A3. Stopping has a ladder: interrupt, then grace, then kill, with quiet attribution**
- **They:**
  - Codync `agent/acp.rs`: `EXIT_GRACE` is 10 s after stdin closes, then a `taskkill /T /F` tree kill. The comment explains: "Claude Code killed during an OAuth refresh loses the new refresh token, and the user's login with it." Stop cancels pending cards, then `session/cancel`, then `CANCEL_GRACE` 15 s (`bot/turn.rs`). `session/new|load|fork` time out at 180 s.
  - OMB `docs/specs/steer-sigterm-audit.md`: a protocol interrupt with a 750 ms grace, then the kill. `stopRequested` is set *synchronously* before the first await, so an intentional stop never shows up as a crash error. Exactly one kill funnel exists, with a static proof that steer and queue never kill.
- **Snow:** SAFE-06 (an instant kill outside the LLM) is planned for Phase 2. `hub/jobobject.py` exists, and a Job Object kill is the bluntest tool.
- **Value:** High. The account is borrowed, so losing its login is a real cost. **Effort:** S. **Phase:** 2.
- **Idea:** "Snow, stop" does three things in order:
  1. At once (under 100 ms): deny every pending approval, block new tool calls at the gate, and send the protocol interrupt.
  2. Close stdin and wait up to 10 s for the process to exit.
  3. Only then use the Job Object kill.

  The adapter records `stop_requested` before the first await, so the HUD shows "stopped", not "crashed".

**A4. Recover a turn cut by a restart, but never redo outward actions**
- **They:**
  - Codync `agent/bot/mod.rs`: a `turn.inflight.<bot>` marker. On boot, if the marker is younger than `STALE_RESUME_MS` (1 h), the host resumes with a hidden `RESUME_PROMPT`: "...If your previous step already completed an action, do NOT repeat it."
  - OMB `docs/runtime-contract.md` §5: a cut turn reruns once only if nothing is known to have gone outward. If it already sent, posted, pushed or paid, it ends `failed(interrupted)` and is never rerun. "Outward" comes from activity rows, never from model text.
  - OMB `server/resume-recovery.ts`: a resume failure is classified "from the driver's protocol state, never from provider error text", then rebuilt once from `recoveryText`.
- **Snow:** CORE-05 is planned for Phase 4. Seed B6 only stores the session id.
- **Value:** High. **Effort:** M. **Phase:** marker in 2, recovery in 4.
- **Idea:** the task row stores `inflight_since` and an `outward_actions[]` list. Snow fills that list from tool events it classifies as outward (git push, send, network POST).
  - On restart: no outward actions means resume with a "check before repeating" note.
  - Outward actions mean mark the task interrupted and ask the user.

**A5. A turn can report "done" while actions that timed out never ran**
- **They:**
  - OMB `server/waiting-on-person.ts`: "Every engine denies an unanswered approval on its own timer and the turn carries on, so its result can read as done while those actions never ran". It shows "Nobody answered ...'s approval in time — that step did not run".
  - Codync `bot/turn.rs finish_turn` marks leftover cards `expired`.
- **Snow:** SAFE-05 (timeout to deny, stays pending) is planned for Phase 2. SPCH-06 and AGNT-08 (summaries from events) are planned for Phase 3. Nothing links the two.
- **Value:** High (an honest summary). **Effort:** S. **Phase:** 2-3.
- **Idea:** the summary fact set always carries `skipped_by_timeout: [...]`. The no-scripts summariser must mention it, and the check fails if it does not.

**A6. Approvals fail closed at the protocol edge**
- **They:**
  - OMB `server/drivers/acp/core.ts`: "only an `allow`-kind option approves, and option order is never a security contract". In the Claude permission broker, a late ask, an ask after close or a duplicate id is answered *deny*, because "a drop hangs the tool".
  - Questions differ from permissions on timeout: a question gets "Use your best judgment and continue", a permission gets a deny.
  - Codync's `Auto` mode is the anti-pattern: it picks `allow_once`, else `allow_always`, else **the first option**. Its default is `Auto`.
- **Snow:** planned for Phase 2 (SAFE-01..05). The resolver rules are not written down.
- **Value:** High. **Effort:** S. **Phase:** 2.
- **Idea:** keep a table of resolver contract tests:
  - Select by option *kind*, never by position.
  - An unknown kind means deny.
  - A duplicate, late or post-close request means deny.
  - A question that times out means "user unavailable, choose the safest option and say so". It never means approval.

**A7. A safety floor that sits under every mode, and "could not parse" is not "clear"**
- **They:**
  - OMB `server/safety-floor.ts`: a never-list (delete root, home or system directories, including Windows `%USERPROFILE%` forms; format disk; fork bomb) that applies even at Full access. Its invariant: "a line not read to its end is 'could not read', never 'clear'".
  - `shared/outbound.ts`: send verbs (SEND, POST, PAY) are gated per bot with `outbound{policy, dailyCap}` (default 25).
- **Snow:** SAFE-01 and SAFE-03 (deterministic tiers) are planned for Phase 2. There is no outbound rate cap.
- **Value:** High. **Effort:** S-M. **Phase:** 2.
- **Idea:** the tier classifier returns `unparsed`, which maps to `ask`, never to `free`. Add a hard never-list that no approval can override. Add a per-day cap on outward sends per task: going over it raises the tier.

**A8. A shadow mode for the approval log**
- **They:** OMB `server/decision-log.ts`: append-only monthly NDJSON, 0600, redacted, kept 180 days. Kinds include `review-would-*`, which logs what a stricter policy *would* have done. Rows carry `unattended` and `via:"call"`.
- **Snow:** SAFE-11 audit log is planned for Phase 2.
- **Value:** Med. **Effort:** S. **Phase:** 2.
- **Idea:** audit rows get `presence` (at PC or away), `channel` (voice, HUD or phone), and `would_tier` from a candidate rule set. Tier rules can then be tuned from real data before they are enforced.

**A9. An agent's shell is a loopback caller too (a live risk in Snow's hub design)**
- **They:** OMB `server/request-auth.ts` records it as an open risk: "a bot's shell is a loopback caller too ... can ... decline a card". Mitigations:
  - the respond endpoint can only decline;
  - approval-mode changes go over a private Electron IPC channel (`electron/approval-trusted-mode.cjs`);
  - the phone sidecar is a separate process with a default-deny route list.
- **Snow:** `hub/server.py` writes `{port, token, pid}` to `run_dir()/hub.json`, which any same-user process can read. The client role is **self-declared** in `hello` (`_Client(ws, role=hello.role)`). So once Phase 2 adds approval commands, a Claude Code shell that Snow spawns could read `hub.json`, connect as role `hud` and approve its own request.
- **Value:** High. **Effort:** S-M. **Phase:** 2, before the first approval command exists.
- **Idea:**
  - Bind roles to credentials: one token per role, handed to each child through its own stdin or pipe and never written to a shared file.
  - Approve-type commands are accepted only from the HUD connection, which proves itself with the Electron main process's private channel, and from voice (speaker-verified) and phone.
  - Agent children never receive any Snow token (A2).

**A10. Give the agent a deliberate line back to Snow through an injected MCP server**
- **They:**
  - Codync `bot/session.rs mcp_servers` and `host/src/mcp.rs` inject stdio MCP servers that are the host binary itself (`chat`, `team`, `memory`, `routines`, `connectors`) and call back over loopback. The chat shows only the agent's `send_message` calls; everything else is "trace".
  - OMB `server/drivers/agents-proxy.ts` uses `OMB_TURN_DEPTH` against recursion. Its rule: "never tell a bot about tools its driver cannot mount".
- **Snow:** missing. Snow plans to infer what to say from the raw stream. AGNT-04 relays only the agent's native questions.
- **Value:** High. It gives a clean spoken channel, and speech stays LLM-written from facts. **Effort:** M. **Phase:** 2 (`notify_user`), 3 (the rest).
- **Idea:** a `snow` MCP server injected per session with a per-session capability token.
  - Tools: `notify_user(summary, importance)`, `ask_user(question, options)`, `show_on_hud(artifact)`, `report_progress(step)`.
  - Every call passes through the policy gate and lands as typed events.
  - The brain voices them. This is the agent-side half of seed F2 and D10.

**A11. Practical facts for spawning agents on Windows**
- **They:**
  - Codync `docs/investigations/windows-npm-agents-2026-10-14.md`: every npm-based agent (Claude, Codex, Antigravity) failed on Windows until 2.16.1 because of `npm exec -c true` under cmd.exe. `backends.rs` resolves `%APPDATA%\npm` and `.cmd`/`.bat` shims. On Windows agents are never idle-released, because there are no process groups to tell a dev server from an MCP server (`bot/lifecycle.rs`).
  - OMB: named pipes `\\.\pipe\...` for its broker, `windowsHide`, a kill-tree test, and hooks run through `%OMB_HOOK_NODE%`.
- **Snow:** a Job Object exists, which beats taskkill. Agent spawning is not built.
- **Value:** Med-High. **Effort:** S. **Phase:** 2.
- **Idea:**
  - Resolve agent binaries to the real `.exe` or `node <entry.js>` instead of going through `.cmd` shims.
  - Spawn each agent in its own nested Job Object, so "stop this agent" kills its dev servers too.
  - Add a Windows spawn test for each adapter in the hardware suite.

**A12. Silent compaction, prompt-cache economics and proactive rollover**
- **They:**
  - OMB `server/drivers/acp/core.ts`: `ACP_PROMPT_RE_ANCHOR_TURNS = 8`. It re-sends the full instructions every 8 bare turns, because agents may compact silently.
  - OMB `server/cache-keepwarm.ts`: `PING_AFTER_MS = 50 min`, which keeps the 1-hour prompt cache warm on long contexts (at least 50k tokens).
  - Codync `bot/compaction.rs`: compacts at the end of a turn once usage reaches 3/4 of the window, at most 3 times a day, otherwise rolls over to a new session with an editable handoff card (`chat/handoff.rs`: last summary, last 4 user messages, last reply, open plan).
- **Snow:** missing. Long voice-driven sessions on a borrowed plan will hit this.
- **Value:** Med. **Effort:** M. **Phase:** 3.
- **Idea:** the adapter reports `context_used`.
  - At 75%, Snow compacts between tasks, never mid-instruction.
  - On rollover, Snow builds the handoff brief from its own event log, then re-anchors the project instructions.
  - Cache keep-warm stays off by default: it spends the user's plan.

**A13. Failing over on usage limits, within the terms**
- **They:**
  - OMB `server/limit-failover.ts`: switch to a backup engine and return after the reset. Never another account on the same subscription; their comment: "rotating accounts to get past a provider's usage limit breaks its terms".
  - `automatic-recovery.ts` refuses a backup that lacks the same tools. `quota-switch.ts` offers the switch as a card. `routine-recovery.ts` waits out a known reset.
  - Codync `host/src/usage.rs` gets usage from `claude -p /usage --output-format json` (every 5 min), the ACP `usage_update._meta["_claude/rateLimit"]` and the statusline JSON.
  - Codync's background memory "dreaming" is skipped above 75% plan usage (`chat/memory/dream.rs HEADROOM_PERCENT`).
- **Snow:** AGNT2-02 is v2. Seed B4 adds a usage readout only. CORE-08 covers Snow's own LLMs, not agents.
- **Value:** Med-High. **Effort:** M. **Phase:** 3-4. This deepens seed B4.
- **Idea:**
  - Read usage from the ACP `usage_update` meta first, `/usage` second.
  - At the limit, offer (never auto-switch while the user is away) "continue on OpenCode with <model>", only if the backup has the same tool classes.
  - Never rotate Claude accounts.
  - Background Snow work that would spend the agent plan yields above 75%.

**A14. Stall guards for agent and delegated work**
- **They:** OMB `docs/runtime-contract.md`: two continuations in a row with no successful tool call, or the same error three times, end a node as `failed(stalled)`. `server/turn-watchdog.ts` adds that "waiting on a person or a computer is not a stall".
- **Snow:** PCTL-06 sets a step limit for screen control only (Phase 5). Agent tasks have none.
- **Value:** Med-High. **Effort:** S. **Phase:** 3.
- **Idea:** one shared `ProgressGuard` with those two rules, used by agent tasks (Phase 3) and screen control (Phase 5). It pauses while an approval is pending, and on firing it emits a `task.stalled` fact that the brain voices.

**A15. Per-turn undo inside the worktree**
- **They:** OMB `server/checkpoints.ts` keeps per-turn shadow-git checkpoints: "the user's own .git is never read, written or locked". Codync has no worktrees ("automatic Git worktrees are not implemented", `docs/features/bot-workspaces.md`).
- **Snow:** HAND-06 and HAND-07 (per-task worktree, accept or discard) are planned for Phase 3.
- **Value:** Med. **Effort:** S-M. **Phase:** 3.
- **Idea:** inside each task worktree, Snow commits a checkpoint ref after every agent turn, so "undo the last step" works by voice alongside whole-task accept or discard.

### B. Remote link and phone (Phase 4)

**B1. Notification hygiene: suppress, throttle, collapse, and send nothing sensitive**
- **They:** Codync `remote/push.rs`:
  - Push is suppressed while a phone is connected (`hub.phone_connected()`).
  - Throttled to one per bot per kind per 5 s.
  - APNs sees only generic text ("Your task is complete...") plus `threadId=computerId:botId`. The real content is sealed to a per-device key.
  - A "done" alert is skipped if the next message is already queued.
  - "Done" or "failed" comes from the ACP `stopReason`: `end_turn` means done; `max_tokens`, `max_turn_requests` and `refusal` mean failed.
- **Snow:** HAND-02, HAND-05 and SAFE-04 are planned for Phase 4. Telegram is not end-to-end encrypted, and the plan already says "minimal text".
- **Value:** Med. **Effort:** S. **Phase:** 4.
- **Idea:** Telegram messages carry an outcome word and a short task label only. Detail opens over Tailscale. Messages are coalesced per task within 5 s and suppressed while the HUD has a live, present user. Done or failed maps from `stopReason`, plus A5 skipped steps.

**B2. Pairing with a short code, the host as the only authority, a default-deny phone surface**
- **They:**
  - Codync `docs/reference/remote-relay.md`: QR pairing with a single-use 10-minute code, or account pairing with a 6-digit SAS confirmed on the computer. The host signs the ACL. Per-device scopes are `control` and `screen`. Account devices hold a 15-minute lease.
  - OMB `companion/src/routes.ts` is a separate sidecar on its own port: "Default deny: a route the harness adds later stays closed to phones until it is listed here." Each device has a revocable bearer.
- **Snow:** SAFE-10 (Tailscale, Telegram user-id allowlist) is planned for Phase 4, and HUD-11 phone HUD for Phase 6. Research suggests signed single-use action tokens.
- **Value:** High. **Effort:** M. **Phase:** 4 (gateway), 6 (phone HUD).
- **Idea:** a separate `snow-remote` listener bound only to the Tailscale interface. It has an explicit allowlist of read and resolve routes, device pairing by a 6-digit code shown on the HUD, revocable per-device tokens with scopes (`view`, `approve`, `approve_t3`), and Tailscale identity checked as well.

**B3. Typing a secret on the phone, sealed to the PC**
- **They:** OMB `server/phone-secret.ts`: credentials typed on the phone are HPKE-encrypted to the harness.
- **Snow:** SAFE-07 (pause for the user to type it directly) is planned for Phase 2, at-PC only. There is no path while the user is away.
- **Value:** Med. **Effort:** M. **Phase:** 4.
- **Idea:** an away-mode secret request opens a one-time page over Tailscale (never Telegram text). The value goes straight into Credential Manager or the waiting prompt and never reaches the event log, the LLM or the agent transcript.

**B4. An offline mailbox from the phone to the PC**
- **They:** Codync has a Durable Object mailbox (24 h TTL, 64 KiB, deduplicated by `clientNonce`, acked) so the phone can send while the PC sleeps. In the PC-to-phone direction, the phone replays from `since: rev`.
- **Snow:** Telegram long polling already holds pending updates server-side for about 24 h, which covers it. The phone HUD has no catch-up design yet.
- **Value:** Low-Med. **Effort:** S. **Phase:** 4/6.
- **Idea:** take the `since: seq` catch-up for the phone HUD from the event log (the hub already has seq). On reconnect, process Telegram replies in update order, deduplicated by `update_id`.

**B5. Talking to Snow from the phone**
- **They:**
  - Codync `docs/features/voice-call.md`: a phone call with a bot. Speech-to-text runs on the phone, and only text goes to the host. "An approval request is announced, answered in the chat."
  - OMB `server/live-call.ts`: a realtime voice model with `delegation:{type:"client"}` that hands every real request to the bot. The API key stays in the harness. Nothing said on a call is logged.
- **Snow:** a native app is out of scope. AWAR-05 and HUD-11 are browser only.
- **Value:** Low-Med now. **Effort:** M. **Phase:** v2 (after Phase 6).
- **Idea:** the phone HUD page over Tailscale gets a hold-to-talk button that uploads one utterance into the normal turn pipeline (Groq speech-to-text), and the reply plays back as audio. T3 approvals still need a tap.

### C. Hand-off, routines and long-running work (Phase 4)

**C1. Keep the laptop awake while work is handed off**
- **They:** Codync `service::KeepAwake` keeps the computer awake while enabled schedules exist, on Windows via `SetThreadExecutionState`.
- **Snow:** missing. HAND-01 ("walk away, Snow keeps working") fails silently if the laptop sleeps. The supervisor only forgives sleep gaps.
- **Value:** High. **Effort:** S. **Phase:** 4.
- **Idea:** while any task is `running` or `waiting_user` in away mode, the hub holds `ES_SYSTEM_REQUIRED` (never the display flag), shows it on the HUD, and releases it at the end. It is off on battery below a threshold, and the user is told.

**C2. Routines: scheduled and triggered tasks**
- **They:**
  - Codync `host/src/routines/`: interval, once, cron (with time zone), webhook and event triggers. Each run gets its own thread and a 1 h default timeout. After a crash a run is `recovering` or `interrupted`, never blindly replayed. `(pass)` means a silent completion.
  - OMB `docs/routine-schedules.md`: creating a routine shows a confirmation card with the next three run dates. A failed run retries once, waits out a usage reset and tells the owner once per cause.
- **Snow:** missing. No requirement covers it; it is closest to the morning-brief scenario in PROJECT.
- **Value:** Med-High. **Effort:** M. **Phase:** 4 (add a HAND requirement) or v2.
- **Idea:** "every weekday at 9, check CI on Snow and tell me if it's red" becomes a routine row whose task runs under the away policy snapshot.
  - The confirmation reads back the next run dates by voice.
  - A run that has nothing to report ends silently.

**C3. A durable delegation tree with one wake per result**
- **They:** OMB `docs/runtime-contract.md` and `server/runtime/*`:
  - An `Assignment{rootId, parentId, depth, origin, mode: work|consult|notify, reply: resume|poll|none}` lives in `runtime.db`.
  - The requester is woken once, with all settled child results together.
  - Envelopes written by the harness mark other bots' text as data: "no bot's message approves a permission".
  - Invariants I1-I10 are tested.
- **Snow:** research `ARCHITECTURE.md` has a flat task table with leases. PARA-01 (parallel tasks) is v2.
- **Value:** Med. **Effort:** M. **Phase:** 4 (schema), v2 (behaviour).
- **Idea:** give the Phase 4 task table `parent_id` and `reply_mode` now, even though v1 uses depth 1, so parallel and sub-tasks later need no migration. Wrap agent-to-agent text as data (SAFE-08).

### D. The multi-agent team model

**D1. Named agent profiles instead of a bot roster**
- **They:**
  - Codync `store/model.rs BotConfig`: name, backend, command, cwd, permission, model, connectors, skills, memory, members for groups.
  - OMB `WireBot` in `shared/wire.ts` adds a soul (SOUL.md with drift detection), `approvalMode`, `computer`, `fallback[]`, `peers[]` and `chiefOfStaff`.
  - Bots ask each other through a `team` MCP (Codync `chat/team.rs`: `ask_bot` with a 10-minute wait, `MAX_REQUEST_HOPS = 8`, cycle detection). OMB's Chief of Staff delegates and "ends its turn".
- **Snow:** Snow is one persona driving agents. Adapter config is planned for Phase 2.
- **Value:** Med. **Effort:** S. **Phase:** 2-3.
- **Idea:** keep Snow as the only "person". Add saved **agent profiles** in config (`[agents.backend] adapter="claude", project=..., model=..., tier_cap="announce", fallback=["opencode"]`), so "start the backend agent" or "ask OpenCode to review it" work by voice.
  - Skip bot-to-bot chat and rooms for v1.
  - One rule is worth keeping now: a delegated approval level can only *tighten* (OMB `delegatedApprovalMode`).

### E. Sandboxes and "their own computers" (Phase 5 and v2)

**E1. One shared UI-control driver for Windows**
- **They:** both drive the screen through **cua-driver** (`trycua/cua`, MIT).
  - Codync's `computer` MCP (`host/src/screen/cua.rs`, sha256-pinned in `packaging/cua-driver/driver.json`) works accessibility-element first, delivers input in the background, allows one bot at a time, and goes look-only while a human has taken over. On Windows it runs `cua-driver.exe` and `cua-driver-uia.exe`.
  - OMB spawns it only from the Electron main process (`docs/computer-use-integration.md`).
- **Snow:** STACK picks `uiautomation` plus Windows-MCP for Phase 5. PCTL2-03 (background GUI control) is v2.
- **Value:** Med. **Effort:** S to evaluate. **Phase:** 5 research.
- **Idea:** add cua-driver's Windows UIA build to the Phase 5 spike next to Windows-MCP. Adopt the rules "look-only while the user is typing or moving the mouse" and "one controller at a time" whichever driver wins.

**E2. A per-agent VM and a browser with an egress policy**
- **They:**
  - OMB `server/container-computer.ts` runs a digest-pinned XFCE VM: `--memory 4g --cpus 2 --pids-limit 512 --cap-drop ALL`, noVNC on 127.0.0.1, Podman on Windows.
  - Per-bot Chrome profiles live under `<data>/browser`.
  - `server/browser/egress/policy.ts` blocks loopback, LAN and cloud-metadata addresses.
  - Saved-password fill keeps secrets away from the model (`server/browser/cdp/secrets.ts`).
- **Snow:** PCTL2-01 is v2. The STACK plans a dedicated Snow Chrome profile. With 16 GB RAM, a 4 GB VM is costly.
- **Value:** Med for egress, Low for the VM. **Effort:** M. **Phase:** 5 (egress, password fill), skip the VM.
- **Idea:** Snow's automation browser blocks `127.0.0.1` and LAN by default, so a malicious page cannot reach the hub (pairs with A9). Login fill goes through a take-over or a vault so the LLM never sees the password.

### F. App integrations (v2)

**F1. Per-connector verb scopes and an argument-shape verdict**
- **They:**
  - OMB `server/connector-verdict.ts`: "Unrecognized argument shapes are denied". Composio multi-execute arguments are inspected. Grants are per service with `connectorScopes` read or write. The managed Composio key lives in a Cloudflare broker, stored only as a SHA-256 of a per-install bearer.
  - User MCP servers are wrapped by `server/mcp-gate.ts` for tool scope and result budgets.
- **Snow:** AWAR-03 (Gmail and Calendar) and AWAR-04 are v2. In Phase 2 MCP goes through the policy gate.
- **Value:** Med. **Effort:** M. **Phase:** v2. (The MCP result budget is S, in Phase 2.)
- **Idea:** every MCP tool gets a declared verb class (read, write or send) and a result size budget at registration. An unknown argument shape means ask. Prefer local MCP servers over a hosted token broker for privacy (QUAL-05).

### G. Memory (deepens the seed only)

**G1. Memory write hygiene and cache-friendly delivery**
- **They:**
  - Codync `host/crates/memory` `check.rs` rejects memory writes that contain planted instructions, secrets, ID numbers or hidden characters.
  - Memory updates reach the agent as a `<memory_update>` block on the *next message*, while the system snapshot stays frozen for the cache (`chat/context.rs`).
  - Each "dreaming" change must quote what the user typed, with at most 10 changes per run, all undoable (`chat/memory/dream.rs`).
  - Evals use keyword grading, not an LLM judge (`tools/memory-eval/`).
  - OMB `docs/memory.md` puts recall into the message, not the system prompt.
- **Snow:** seeds A1-A8 plan memory with no write checks.
- **Value:** Med. **Effort:** S. **Phase:** with seed A1.
- **Idea:**
  - A memory writer rejects anything instruction-shaped or secret-shaped, and each fact must cite the turn_id and quote the user.
  - Recall goes into the user message so Snow's own prompt prefix stays stable for provider caching.

### H. Testing and quality

**H1. Fake agents and harness evals**
- **They:**
  - Codync `host/tests/fake_agent.py` and `fixtures/*_agent.py`: Python fake ACP agents of about 20-180 lines (`stubborn_agent` ignores cancel; `ended_session_agent` mimics Claude's "session has ended").
  - Codync end-to-end tests restart a real host on the same data dir.
  - Codync's `tests/fixtures/wire-shape.json` snapshot tells breaking API changes from additive ones.
  - OMB `server/testing/fake-claude-cli.ts`, `fake-acp-cli.ts`, `fake-codex-app-server.ts` and `hostile-site.mjs`.
  - OMB `evals/README.md`: "evaluate the harness, never the models":
    - Tier 1: scripted fake-engine scenarios with pure scorers.
    - Tier 2: redacted golden traces.
    - Tier 3: opt-in live runs with a sha-pinned judge.
- **Snow:** Phase 1 has contract samples, fake and hardware suites, and CI. Seed B1 proposes one fake-SDK test.
- **Value:** High. **Effort:** M. **Phase:** 2.
- **Idea:** `tests/fakes/` gets a fake ACP agent and a fake Claude stream-json CLI. Each has scripted misbehaviours: ignores cancel, permission spam, duplicate request id, dies mid-turn, session ended, slow handshake, OAuth-refresh-in-progress.
  - Every adapter must pass one contract suite against them.
  - Add scenario evals ("voice turn, then agent, then approval timeout, then honest summary") scored by assertions on events.

## 3. What Snow already does better (do not regress)

| Area | Snow | Them |
|---|---|---|
| Default permissions | No auto-approve; deterministic tiers; timeout means deny (out-of-scope list) | OMB defaults to **Full access** (`DEFAULT_APPROVAL_MODE`). Codync defaults to `Auto` and falls back to the *first option* |
| Approval timeout | Deny, and the request stays pending on the HUD and phone (SAFE-05) | Codync has none: cards wait until the turn ends. OMB gives 15 min, then deny |
| Speaker identity | Speaker verification planned (VOIC-07); a second factor for T3 | Codync: approvals are only "announced" on a call. OMB: strict spoken consent, but nothing checks who spoke |
| Voice stack | Wake word, AEC barge-in, Smart Turn, Groq plus Moonshine, mood TTS router | OMB is half-duplex "take turns" with no AEC and no Windows speech-to-text. Codync uses platform recognisers |
| Provider independence for Snow's brain | Five-provider fallback chains and privacy routing | OMB has a model catalog, but no privacy routing by data class |
| Secrets | Credential Manager, a canary test, redaction | Comparable: OMB uses `safeStorage` and an fd handoff; Codync keeps `identity.json` as a file |
| Windows | Windows first: Job Object, Task Scheduler, WASAPI | Both are macOS first. Windows is unsigned, lacks features and is tested by hand |

## 4. Skip list

- **Codync's own E2E relay crypto and Cloudflare relay.** Tailscale already gives Snow an authenticated encrypted path, and rolling custom crypto is not worth it. Only the push hygiene and pairing ideas are kept (B1, B2).
- **Bot rosters, group rooms, the decider classifier and bot-to-bot chat.** Snow is one persona. Agent profiles (D1) cover the useful part.
- **A per-agent XFCE VM and cloud "Boat" computers.** Too heavy for 16 GB RAM and 6 GB VRAM, and off-mission for v1.
- **A hosted Composio broker.** It puts third-party OAuth tokens in someone else's cloud. If connectors arrive, prefer local MCP.
- **OMB's realtime speech-to-speech "live call" and Codync's platform recognisers.** Snow's own pipeline is stronger.
- **Auto, Full and bypass modes in any form.**

## 5. Ranked top 8 (across both projects)

| # | Item | Why | Value / Effort / Phase |
|---|---|---|---|
| 1 | **A9: Lock the hub before approvals exist.** One token per role, never in a shared file; approve commands only from the HUD's private channel, voice and phone; no Snow token in agent children | Today `hub.json` plus a self-declared role means a spawned Claude Code shell could approve its own requests | High / S-M / 2 |
| 2 | **A1: Three-state `steer()` plus `mid_turn_input` in the adapter contract.** ACP is queue or cancel only; never replay an indeterminate steer | AGNT-07 is impossible to do honestly over ACP without this, and a replay runs work twice | High / S-M / 2-3 |
| 3 | **A2 + A11: Agent spawn hygiene.** Allowlist env (no `ANTHROPIC_API_KEY` flipping the plan to paid, no `CLAUDECODE`), project-only settings, prompt off argv, real `.exe` not `.cmd` shims, nested Job Object | Protects the borrowed subscription and fixes Windows spawn bugs others hit | High / S / 2 |
| 4 | **A3: Graceful stop ladder.** Instant gate-level halt, then a protocol interrupt, stdin close and 10 s grace, then a Job Object kill; `stop_requested` set before the first await | SAFE-06 stays instant without killing Claude mid-OAuth-refresh and losing the login | High / S / 2 |
| 5 | **A4 + A5: Honest restart and summary.** An in-flight marker with a "don't repeat" resume, no rerun after outward actions, and timed-out approvals always named in the summary | Prevents double pushes and sends, and stops "done" when steps never ran | High / M / 2-4 |
| 6 | **A6 + A7: Fail-closed resolver and safety floor.** Choose by option kind, never position; late or duplicate requests mean deny; `unparsed` means ask; a never-list; a per-task outward send cap | Hardens SAFE-01..05 at the exact spots both projects had to patch | High / S-M / 2 |
| 7 | **A10: An injected `snow` MCP server** (`notify_user`, `ask_user`, `show_on_hud`, `report_progress`) behind the policy gate | Gives agents a deliberate voice channel to Snow instead of Snow guessing from the stream | High / M / 2-3 |
| 8 | **C1 + C2: Keep-awake during hand-off, then routines.** `SetThreadExecutionState(ES_SYSTEM_REQUIRED)` while away tasks run; a cron routine with a next-dates read-back | HAND-01 silently fails when the laptop sleeps; routines are the natural next step | High (C1) / S, Med-High (C2) / M / 4 |

**Next in line:**
- H1: fake agents and scenario evals (High, M, Phase 2). Build it with #2-#6.
- A14: stall guard.
- B2: default-deny remote gateway with pairing.
- A13: limit failover within the terms.
- A12: compaction and rollover.
- A15: per-turn checkpoints in the worktree.
- B1: notification hygiene.

## Sources

- Codync: https://github.com/leepokai/Codync (Product Hunt listing https://www.producthunt.com/p/codync/codync-2)
- OpenMausBot: https://github.com/milind-soni/OpenMausBot (listing https://osrepos.com/repo/milind-soni-openmausbot)
