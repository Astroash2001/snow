# Gap study: OpenClaw vs Snow

Date: 2026-10-19.

**Target.** github.com/openclaw/openclaw. I made a shallow clone of the default branch (about 58k files) and only read it; nothing was run, installed or imported. Earlier names: Warelay, then Clawdbot, then Moltbot.

**Licence.** MIT (`LICENSE`, "Copyright (c) 2026 OpenClaw Foundation"). MIT is not copyleft, so copying code would be legal if the notice is kept. Even so, this study takes only ideas, constants and invariants. OpenClaw is TypeScript and Snow is Python, so every idea below is written as our own design for Snow's stack.

**Method.** Four parallel deep reads covered memory, the gateway and channels, security and tools, and sessions and automation. Each read the docs *and* the code. I spot-checked every cited OpenClaw file path in the clone. On the Snow side I read:
- `.claude/CLAUDE.md`, `.planning/PROJECT.md`, `ROADMAP.md`, `REQUIREMENTS.md` and `research/ARCHITECTURE.md`;
- both earlier seeds (`SEED-261019-mnj…` and `fullstack-agent-gap-study.md`);
- the relevant code in `src/snow/hub/`, `src/snow/brain/`, `src/snow/contracts/` and `hud/src/`.

Findings already captured in the fullstack study are **not repeated**. That covers: a memory requirement plus profile, daily summaries, procedures and markdown+FTS5; `snow doctor` and TROUBLESHOOTING.md; the SDK interrupt guard; spoken approval UX (code-built summary, exact yes, answers timed after the question); voice console verbs; date and speakable-text prompt rules; ducking; and device recovery. Where OpenClaw adds detail to one of those, the item says "deepens".

**Paths.** OpenClaw paths are relative to the clone root. Snow paths are relative to `C:\Users\avina\Desktop\asssistant`.

---

## 0. TL;DR

- **OpenClaw is the closest real product to Snow's Phases 2 to 4.** It has one always-on daemon, chat-channel approvals (Telegram inline keyboards), Tailscale Serve, background jobs that survive restarts, managed git worktrees, self-update with rollback, Windows Scheduled Task autostart and a voice ("Talk") mode. It has also been attacked in public, so its changelog doubles as a list of what to defend against.
- **A live Snow issue found by comparison (fix before Phase 2 adds an approve command).** The hub has **one shared per-launch token**, and the **client declares its own role** in `Hello`:
  - `src/snow/hub/server.py:86` creates the token, and `_authenticate` at about line 170 accepts the role from `Hello`.
  - `src/snow/hub/supervisor.py:99` gives `SNOW_TOKEN` to every worker.
  - `COMMAND_ROLES` in `src/snow/contracts/wire.py` then trusts that self-declared role.
  - So any process holding the token, including a future Claude Code child that inherits the brain's environment, can claim `hud` or `dev`. Claiming `dev` lets it inject a fake `TranscriptFinal` (bypassing wake and speaker checks). Claiming `hud` will let it approve its own permission requests once Phase 2 adds that command.
  - OpenClaw shipped exactly this bug ("self-declared scopes on shared-token connects", GHSA-rqpp-rjj8-7wv8, `CHANGELOG/2026.3.12.md`).
- **The biggest lesson from their security history:** their command-parsing allowlist was bypassed about 30 times in 8 months (wrappers, heredocs, `$()` inside quotes, env injection, `cmd.exe` quirks, Unicode tricks). Snow must not treat parsing shell text as a security boundary. Any shell, interpreter or wrapper call is high tier, and an approval is bound to a hash of the exact plan that was approved.
- **Best new design material for Snow:**
  - **Telegram durable ingress, plus approval cards whose first answer wins** (Phase 4).
  - **Restart-recovery invariants:** claim the work before calling the model, a charged retry budget then a tombstone, read-only tools when an outcome is unknown, and never replay uncertain side effects (Phase 4).
  - **Worktree lifecycle:** snapshot-on-discard and lossless removal (Phase 3).
  - **Self-upgrade canary** against copied config and database, with rollback only when the schema is unchanged (Phase 3).
  - **Memory provenance and turn taint**, which deepens the memory seed.
  - **A deterministic voice run-control classifier** (status, steer, cancel, follow-up) (Phase 3).
- **Presence trap Snow would hit:** OpenClaw ignores *synthetic* input when it computes user presence. Snow will drive the PC with SendInput (Phase 5), and SendInput resets `GetLastInputInfo`. Without this rule, Snow's own clicks make it think the user is at the desk, so approvals go to the empty PC instead of the phone.

---

## 1. Gaps by area

Each gap below gives: **They** (what OpenClaw does and where) · **Snow** (what Snow has now or plans) · **Value** · **Effort** · **Phase** · **Idea** (our own design).

### A. Security, approvals and tools (Phase 2 unless noted)

#### A1. Per-client credentials: the role comes from the token, not from the client
- **They:**
  - Every WebSocket client proves its identity with a device key that signs a server challenge (`connect.challenge` nonce).
  - It receives a token per device and role with a closed set of scopes (`operator.read/.write/.admin/.approvals/.questions/.pairing/.talk`).
  - Resolving approvals needs the dedicated `operator.approvals` scope; `.write` is not enough.
  - The mobile bootstrap gets a bounded token: approvals, read and write, but no admin.
  - Files: `docs/gateway/operator-scopes.md`, `docs/gateway/protocol/handshake.md`, `src/gateway/operator-scopes.ts`, `src/gateway/auth*.ts`. Fix history: GHSA-rqpp-rjj8-7wv8 (`CHANGELOG/2026.3.12.md`) and GHSA-5wcw-8jjv-m286, a cross-site WebSocket hijack that granted admin (`CHANGELOG/2026.3.11.md`).
- **Snow:** one shared token; the role is taken from `Hello` (`src/snow/hub/server.py` `_authenticate`). `SNOW_TOKEN` goes into every worker's environment (`src/snow/hub/supervisor.py:99`, `scrub_env`). The role matrix is `COMMAND_ROLES` (`src/snow/contracts/wire.py:74`). Host and Origin checks already exist (`_check_request`), which is good against cross-site hijacking.
- **Value:** high · **Effort:** S · **Phase:** 2, before any approve or agent command exists.
- **Idea:**
  - The hub mints one random token per worker role at launch and maps token to role internally. `Hello.role` becomes a claim the hub checks, never trusts.
  - Add an `approvals` capability held only by the HUD and the phone channel.
  - Strip every `SNOW_*` variable from any agent or tool subprocess environment.
  - Add a test: a `brain`-role token sending `cmd.approval.resolve` is closed with 4403.

#### A2. An approval is bound to the exact plan, and that binding is re-checked just before launch
- **They:** an approval binds argv, cwd and env. Just before spawning, every executable in the dispatch chain is re-resolved:
  - protected binaries are checked by real-path identity;
  - writable ones are also checked by content hash;
  - a new executable appearing earlier on PATH means deny;
  - a symlinked cwd is rejected;
  - a script run binds one concrete file snapshot, and if exactly one file cannot be identified (npx, package scripts, eval forms), approval-backed execution is refused;
  - caller edits made after the request are discarded.

  Files: `src/infra/exec-authorization-plan.ts`, `src/infra/exec-approvals-authorization*.ts`, `docs/tools/exec-approvals-advanced.md`. Fixes: GHSA-57jw-9722-6rf2, GHSA-jvqh-rfmh-jh27, GHSA-x7pp-23xv-mmr4, GHSA-jc5j-vg4r-j5jx (`CHANGELOG/2026.3.12.md`).
- **Snow:** a durable approval object is planned for Phase 2. `research/ARCHITECTURE.md` mentions "single-use signed approval tokens bound to the `action_hash`". Nothing yet says the binding is re-checked right before execution.
- **Value:** high · **Effort:** S-M · **Phase:** 2.
- **Idea:**
  - `ApprovalRequest.plan_hash = sha256(canonical JSON of {tool, argv, cwd_realpath, env_keys, exe_realpath, exe_sha256_if_user_writable})`.
  - The executor recomputes the hash right before spawning and denies on any mismatch.
  - The spoken and HUD summary is generated *from* that plan, so the user approves exactly what will run.

#### A3. Shell text is never a safety boundary
- **They:**
  - A rich parser: chains, wrapper unwrapping (`env`, `timeout`, `nice`, `busybox`), carrier recursion (`sudo`, `exec`), NFKC folding, and invisible-character stripping.
  - A Windows rule set: any unquoted `& | < > ; ^ ( ) % !`, a backtick or newline, or `$name` is rejected; `%`, the backtick and newline are unsafe even inside double quotes; single quotes are not treated as quoting; and the approved command is **re-rendered from the parsed argv**, refused if the segment count differs.
  - Even so, the changelog shows about 30 allowlist bypasses fixed between 2026.1 and 2026.4. Their own threat model rates T-EXEC-004 (approval bypass) as High: "normalization narrows but does not eliminate obfuscation bypass".
  - Files: `src/infra/windows-shell-command.ts`, `src/infra/command-analysis/*.ts`, `src/infra/command-carriers.ts`, `docs/security/THREAT-MODEL-ATLAS.md`.
- **Snow:** SAFE-01 promises deterministic tiers, but how shell and interpreter calls are tiered is not specified yet.
- **Value:** high · **Effort:** M · **Phase:** 2.
- **Idea:**
  - In a single tier table (one constants module), the classes "runs arbitrary code" (cmd, PowerShell, bash, python, node, `-c`/`-e` inline eval, npx, wrappers) and "can write outside the worktree" are **ask** by default.
  - Parsing may only *raise* a tier (for example, it spots `Remove-Item -Recurse` and moves the call to always-ask), never lower one.
  - Use the Windows metacharacter list as a raise-to-ask hint, and re-render from argv for anything Snow runs itself.

#### A4. "Always allow" grants are narrow and expire
- **They:**
  - Since 2026.8.1, `allow-always` entries are bound to an exact-argv hash *and the cwd*. Older, broader entries are deactivated by `doctor --fix`.
  - Grants made for automations also bind a hash of the job definition: any edit voids the grant, and editing back does not restore it.
  - `grantExpiryDays`, plus a grants ledger with list and revoke.
  - Inline-eval commands are never persisted as grants.
  - Anti-pattern to avoid: MCP "Allow Always" grants cover *any arguments*.
  - Files: `docs/tools/exec-approvals.md` (sections "Allowlist", "Standing grants", "MCP tool grants"), `src/infra/exec-approvals-allow-always.ts`.
- **Snow:** missing. SAFE-02 ("routine work runs without asking") will create pressure for "always allow this".
- **Value:** med · **Effort:** S · **Phase:** 2, with the ledger shown in the HUD in Phase 4.
- **Idea:**
  - A spoken "always allow that here" creates a grant row `{plan_hash_without_volatile, cwd, created_by=voice, expires_at}` in a table the agent process cannot write.
  - "What have I allowed?" lists the grants, and "revoke" removes them.
  - No grants for code-evaluating commands, and no grants for MCP tools that cover any arguments.

#### A5. Approval display hardening and typed scope summaries
- **They:**
  - Invisible, format and bidi characters are shown as `\u{…}` escapes, because zero-width characters were used to spoof approval prompts (GHSA-pcqg-f7rg-xfvv) and to suppress obfuscation detection (GHSA-9r3v-37xh-2cf6).
  - Display is capped at 16 KB, and anything over 256 KB becomes a marker.
  - On macOS, Return alone does not approve; Cmd+Return does.
  - The request lists which decisions are offered, and the Gateway rejects any other.
  - Changing permissions **cancels** pending approvals.
  - A cancelled turn invalidates them, so "a late approval cannot restart it".
  - Optional typed **scope summaries**: message-send recipients (internal or external), payment amount and payee, external post (public or restricted).
  - Files: `src/infra/exec-approval-text-sanitize.ts`, `docs/tools/exec-approvals.md` ("Approval scope summaries").
- **Snow:** HUD-07 and the spoken approval UX are planned (fullstack C1-C4). Character escaping, offered-decision sets, cancel-on-turn-end and typed scopes are missing.
- **Value:** med-high · **Effort:** S · **Phase:** 2.
- **Idea:**
  - Every approval surface (HUD, Telegram card, spoken summary) renders the request through one sanitiser that escapes invisible and bidi characters.
  - `ApprovalRequest` carries `scope: {kind: send|payment|post|delete|credential, who, amount?, public?}` so the LLM-written spoken line has typed facts to use.
  - Resolving an approval for a cancelled turn is a no-op, recorded as "expired".

#### A6. Child environment: an allowlist, with their blocklist as a test oracle
- **They:**
  - `src/infra/host-env-security-policy.json` blocks 110 keys everywhere (`NODE_OPTIONS`, `PYTHONPATH`, `BASH_ENV`, `GIT_*` hooks and editors, `SSLKEYLOGFILE`, `DOTNET_STARTUP_HOOKS`, `JAVA_TOOL_OPTIONS`…) and 156 more as overrides.
  - Prefixes `LD_`, `DYLD_` and `BASH_FUNC_` are blocked; PATH overrides are rejected.
  - Workspace `.env` files may not set provider keys, `COMSPEC` or `PROGRAMFILES` (the `COMSPEC` fix is in `CHANGELOG/2026.4.29.md`; inherited `GIT_EXEC_PATH` is GHSA-jf5v-pqgw-gm5m).
  - Their weakness: child processes still inherit the Gateway environment *minus* the blocklist.
- **Snow:** `scrub_env` removes variables whose names contain secret-like words and keeps everything else (`src/snow/hub/supervisor.py:93`). That is fine for Snow's own workers, but it is a blocklist. CLAUDE.md promises "minimal, scrubbed environments" for agents.
- **Value:** high · **Effort:** S · **Phase:** 2.
- **Idea:**
  - Agent and tool children get an **allowlisted** environment: `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, a fixed `PATH` and `PATHEXT`, `COMSPEC` set to the real cmd.exe path, plus the specific keys the adapter needs.
  - A unit test asserts that none of OpenClaw's listed dangerous names (re-typed as our own list), and nothing matching `SNOW_*`, survives.

#### A7. Provenance on every piece of content, plus random-id untrusted wrappers
- **They:**
  - External content (web, email, webhooks, browser, attachments, PDFs) is wrapped in `<<<EXTERNAL_UNTRUSTED_CONTENT id="<16 random hex>">>> … <<<END… id=…>>>` with source metadata.
  - Spoofed markers are neutralised after folding fullwidth and homoglyph brackets and removing zero-width characters.
  - Chat-template special tokens (ChatML, Llama, Mistral, Gemma, harmony) become `[REMOVED_SPECIAL_TOKEN]`.
  - They removed "do not do X" lists from the wrapper because those caused over-refusal.
  - Gap they admit: exec, MCP and agent output is **not** wrapped. The threat model calls wrappers "soft guidance an adaptive attacker can erode" (T-EVADE-002: "novel escapes discovered regularly").
  - Files: `src/security/external-content.ts`, `docs/gateway/security/prompt-injection.md`.
- **Snow:** SAFE-08 says that content is data and that actions originating from it need approval. The event contract has no origin or provenance field yet (`src/snow/contracts/events.py`).
- **Value:** high · **Effort:** M (the contract field is S now) · **Phase:** 2.
- **Idea:**
  - Add `origin: owner_voice | owner_typed | agent | external | system` to every content-carrying event, set by the code that produces it, never by the model.
  - The brain keeps a per-turn `tainted` bit: once any `agent` or `external` content enters the turn, every tool call in that turn is raised to at least **ask**. This is the structural SAFE-08.
  - Wrap Claude Code output, screen text and web text with random-id markers, and strip chat-template tokens before any LLM call.

#### A8. Loop detection, on by default
- **They:**
  - Always on: the turn stops after 3 consecutive identical (tool, arguments, error) results.
  - Optional rolling detectors over 30 calls: warn at 10, critical at 20, no-progress breaker at 30, unknown tool at 10, plus ping-pong and argument-churn detection.
  - Progress is measured by hashing exec status, exit code and output, ignoring PIDs and durations.
  - Files: `src/agents/tool-loop-detection.ts`, `src/agents/tool-loop-thresholds.ts`, `docs/tools/loop-detection.md`.
- **Snow:** PCTL-06 adds a step limit for screen control in Phase 5. The brain's tool loop has none for Phase 2.
- **Value:** med · **Effort:** S · **Phase:** 2, reused in Phase 5.
- **Idea:**
  - A `LoopGuard` in the brain's tool loop: 3 identical failures means stop.
  - Stop with a spoken cause at 20 calls with no change in outcome hashes.
  - Emit a `loop.stopped` event so the HUD shows why.

#### A9. A security self-audit for dangerous configuration, and fail-closed tool installs
- **They:**
  - `openclaw security audit [--deep] [--fix]` has about 120 check IDs for dangerous *combinations*, for example `sandbox.dangerous_bind_mount` and `security.exposure.open_groups_with_elevated` (`src/security/audit*.ts`, `docs/gateway/security/audit-checks.md`).
  - Telegram checks flag non-numeric allowlist entries and wildcard groups (`extensions/telegram/src/security-audit.ts`).
  - Install policy: an operator hook returns allow, warn or block, and **no valid answer means blocked**. npm installs use `--ignore-scripts`, and `--pin` records integrity hashes.
  - Workspace plugin auto-load was removed after GHSA-99qw-6mr3-36qr, where a cloned repository could run code.
- **Snow:** `snow doctor` is planned (fullstack G) as a health and repair tool, not a security audit. MCP servers are planned "behind the policy gate". There is no pin or install policy yet.
- **Value:** med · **Effort:** S · **Phase:** 2, extended in Phase 4.
- **Idea:** `snow doctor --security` checks that:
  - the hub is bound to 127.0.0.1;
  - Tailscale Funnel is off;
  - the Telegram allowlist is numeric and non-empty;
  - no private role chain includes an untrusted provider;
  - every MCP server has an exact version and hash;
  - no tool or MCP config is loaded from a repository Snow is working on.

  Snow refuses to start a high-risk feature while a critical check fails.

#### A10. The audit log must be the opposite of theirs
- **They:** the audit ledger records metadata only, writes asynchronously and is **best-effort**: "Absence of a row proves nothing", it has no hash chain, keeps 30 days and caps at 100k rows. Approvals live in a separate store where the first answer wins. Files: `docs/gateway/audit.md`, `src/audit/*`.
- **Snow:** SAFE-11 plans an append-only, redacted audit log.
- **Value:** med · **Effort:** S · **Phase:** 2.
- **Idea:** make each audit row hold `prev_hash`, and write it synchronously before the action starts. `snow doctor` verifies the hash chain. Never trade durability for speed here.

#### A11. Secrets bound to one destination host
- **They:**
  - Model credentials travel as opaque sentinels (`oc-sent-v2.…`) that are swapped for the real value only at the guarded fetch.
  - An optional loopback egress proxy substitutes a secret only for **exact HTTPS hostnames bound to that secret**, with a grant per process that is revoked on exit.
  - A `secrets` tool takes the value through a masked prompt, so it never enters the transcript.
  - Weaknesses: the store is plaintext SQLite, and transcripts and tool results keep any credentials verbatim.
  - Files: `src/secrets/sentinel.ts`, `src/secrets/egress-proxy/`, `docs/gateway/secrets/secret-store-and-egress.md`.
- **Snow:** keys live in Credential Manager (better at rest). SAFE-07 covers the "user types the secret" flow. Redaction is in logs only.
- **Value:** med-low · **Effort:** L · **Phase:** 7 or later.
- **Idea:** later, when Snow injects keys into agents, give each key an allowed host list and inject it through a small loopback proxy, never as plain environment variables. Also run the existing redactor over transcripts and tool results before they are stored in the event log.

### B. The phone link: Telegram, Tailscale and presence (Phase 4 unless noted)

#### B1. Durable Telegram ingress: store first, then advance the offset
- **They:**
  - Each `getUpdates` batch is written in one transaction to SQLite (`channel_ingress_events`) *before* the restart offset moves; a failed write rejects the acknowledgement.
  - A drain processes updates in per-chat lanes, so a slow turn never blocks the acknowledgement.
  - Two dedupe layers: by update_id (tombstones for 30 days or 1,000 entries), and by `(bot, chat, message_id)` for 7 days.
  - Queued updates older than 24 h are tombstoned, not run, "to avoid executing stale instructions".
  - They say outright that this is not exactly-once.
  - Files: `docs/channels/telegram/transports.md`, `extensions/telegram/src/ingress.ts`, `telegram-ingress-drain.ts`, `message-dispatch-dedupe.ts`.
- **Snow:** Phase 4 plans python-telegram-bot long polling, which by default keeps the offset in memory.
- **Value:** high · **Effort:** S-M · **Phase:** 4.
- **Idea:**
  - Each update is appended as a `phone.update.received` event keyed by update_id (UNIQUE) before the offset is confirmed.
  - On startup, updates older than a short window, for example 10 minutes, are recorded as `expired` and never executed.
  - An approval tap from yesterday must never fire after a reboot.

#### B2. One poller per bot token, plus a stall watchdog
- **They:**
  - A process-wide lease keyed by a fingerprint of the token (`extensions/telegram/src/polling-lease.ts`).
  - A 409 from `getUpdates` is reported as "another gateway or script is using this token".
  - Polling restarts if no `getUpdates` completes for 120 s (`polling-liveness.ts`).
  - Repeated 401s suspend the typing indicator.
- **Snow:** CORE-06 means a pinned running copy *and* a development copy, and both could poll the same token. Laptop sleep is the classic way a long poll hangs silently.
- **Value:** high · **Effort:** S · **Phase:** 4.
- **Idea:**
  - A named Windows mutex keyed by `sha256(token)[:12]`. A dev-copy hub never starts polling while the pinned copy holds it, and the HUD says which copy owns the phone link.
  - A liveness check restarts the poller after 120 s, or right away on a resume-from-sleep event (the supervisor already detects sleep gaps).

#### B3. Approval cards: versioned callback data, re-check the sender, first answer wins everywhere
- **They:**
  - Callback data is `tga1:<kind>:<decision>:<id>`, fits Telegram's 64-byte limit (a digest reference when the id is long) and is parsed strictly. Malformed data with that prefix is consumed and shown as "unavailable".
  - On a click:
    1. answer the callback query at once;
    2. re-check `callback.from.id` against the *approver* list (an allow-listed chat user is not automatically an approver);
    3. resolve through the Gateway, where the first committed answer wins;
    4. edit the card into a receipt ("Approval resolved here / Recorded result …") and remove the keyboard; other surfaces clear their stale buttons.
  - Expiry edits the card to "expired".
  - Files: `extensions/telegram/src/approval-callback-data.ts`, `approval-handler.runtime.ts`, `approval-terminal.ts`, `bot-handlers.callback-router.ts`, `src/gateway/approval-channel-custody.ts`.
- **Snow:** one-tap approve and deny is planned (HAND-03); the approval object is reused from Phase 2.
- **Value:** high · **Effort:** S · **Phase:** 4, with an atomic resolve in the Phase 2 approval object.
- **Idea:**
  - Callback data is `snw1:<a|d>:<approval_id>:<nonce8>`. It is only a pointer: the approval is looked up by id, and `from.id` is re-checked against the allow-listed user id.
  - The resolve is an atomic `UPDATE … WHERE state='pending'`, and the outcome is published as an event.
  - The HUD, the voice turn and every Telegram card react to that one event: they edit into a receipt, and voice stops waiting.

#### B4. Answering questions from the phone: buttons plus "Other…" free text
- **They:** an `ask_user` question shows one button per choice plus **Other…**, which opens Telegram's reply input. Question callbacks use their own prefix. The answer time is the click's receipt time, not the time the card was sent. Files: `extensions/telegram/src/question-callback-data.ts`, `question-finalization.ts`.
- **Snow:** HAND-04 (free-text answers) is planned.
- **Value:** med · **Effort:** S · **Phase:** 4.
- **Idea:** relay an AskUserQuestion's 2-4 options as buttons, and make the last one "Other…" using ForceReply. Accept the reply only if it answers that exact card's `message_id` and comes from the allow-listed user. This reuses the fullstack C4 rule that an answer counts only if it comes after the question.

#### B5. Outbound flood control: some messages may be replaced, others must arrive
- **They:**
  - A Telegram 429 `retry_after` pauses the *whole token*, and a shorter concurrent 429 never shortens an active pause.
  - Messages that must arrive (final replies, deletes) retry within a 5-minute budget.
  - Replaceable calls (progress edits, typing) give up instead of queueing.
  - Sends that went through an authorization check are re-checked after each wait.
  - Files: `extensions/telegram/src/account-throttler.ts`, `request-authority.ts`.
- **Snow:** missing.
- **Value:** med · **Effort:** S · **Phase:** 4.
- **Idea:**
  - One token-wide gate. Each send is tagged `must_deliver`, for approval cards and final outcomes, or `replaceable`, for progress edits.
  - Replaceable sends are dropped while the gate is closed.
  - An approval card waiting behind a pause is re-checked against the approval state before sending, so a card for an already-resolved approval is never sent.

#### B6. One self-editing progress message, with a privacy dial
- **They:**
  - "Progress draft" mode creates one status message and edits it with `editMessageText`, for example "✅ Read the docs / ▸ Run tests / ▢ Summarize", throttled to one edit per second.
  - The final answer is sent as a new message and the draft is cleared.
  - `commandText: status` (the default) shows only tool labels; `raw` shows the commands.
  - Files: `docs/concepts/progress-drafts.md`, `src/channels/progress-draft-compositor.ts`, `extensions/telegram/src/draft-stream.ts`.
- **Snow:** Phase 4 says "minimal text"; how progress is shown is not designed.
- **Value:** med · **Effort:** S · **Phase:** 4.
- **Idea:** each handed-off task gets one Telegram message that is edited, at most once every 2 s, from the task's progress-card events (C4). Labels only, never commands or paths, because Telegram is not end-to-end encrypted.

#### B7. Tailscale identity: cross-check the header with `whois` on a listener only Serve can reach
- **They:**
  - `tailscale-user-login` is trusted only when all of these hold:
    - the request arrived on a dedicated loopback listener that only the managed Serve route points at;
    - the `x-forwarded-for`, `x-forwarded-proto` and `x-forwarded-host` headers are present;
    - there is no Funnel marker;
    - `tailscale whois <forwarded IP>` returns the same login.
  - The header bypass covers only the dashboard WebSocket; HTTP APIs still need the token.
  - Funnel refuses to start without password auth.
  - Files: `src/gateway/ingress-attribution.ts`, `src/infra/tailscale.ts`, `docs/gateway/tailscale.md`.
- **Snow:** SAFE-10 and the stack doc plan "verify the header AND a token".
- **Value:** high · **Effort:** S · **Phase:** 4.
- **Idea:**
  - The phone-facing listener is a *separate* `127.0.0.1` port from the HUD hub, and only `tailscale serve` targets it.
  - On each new connection, Snow runs `tailscale whois --json` on the forwarded IP, compares it to the allow-listed login, and also requires the device token.
  - `snow doctor --security` fails if `tailscale funnel status` shows Snow's port.

#### B8. Presence: ignore synthetic input and trust only server time
- **They:**
  - A node reports `idleSeconds`. The Gateway computes `last_active = its own now − idleSeconds` and never trusts a client clock.
  - **Synthetic (automation) input does not count** as presence.
  - Missing data means `unknown`, not "away".
  - Alerts go to the freshest device first and fan out after 5 s.
  - Files: `docs/concepts/presence.md`, `docs/nodes/presence.md`.
- **Snow:** SAFE-04 says "unknown means away". `research/ARCHITECTURE.md` plans to use `GetLastInputInfo` plus WTS session notifications. Nothing accounts for Snow's own SendInput, which resets `GetLastInputInfo`.
- **Value:** high · **Effort:** S · **Phase:** 4, needed before Phase 5 drives input.
- **Idea:**
  - Snow's input driver records `synthetic_until = now + 2 s` whenever it injects input.
  - The presence monitor ignores idle-clock resets that fall inside those windows, with a low-level hook check on `LLKHF_INJECTED` / `LLMHF_INJECTED` as a second source.
  - The PC being locked always means away.

#### B9. Notification text that stays private on the lock screen
- **They:** the web-push approval in "private" mode reads only "approval requested / Open OpenClaw to review". It is tagged per approval id, so the final update replaces the alert, and delivery re-checks the subscriber's access. File: `src/gateway/approval-web-push.ts`. Counter-example in their own code: the Telegram exec card shows the full command (`src/infra/exec-approval-reply.ts`).
- **Snow:** HAND-05 says the first line states what, where and why it is risky. That line appears in the Android lock-screen preview.
- **Value:** med · **Effort:** S · **Phase:** 4.
- **Idea:**
  - A `notify.detail` setting: `private`, the default, sends "Snow needs a decision (risk: high)" plus buttons; `summary` adds HAND-05's line.
  - Full detail is always fetched over Tailscale.
  - When the approval resolves, the same message is edited to the outcome, so stale alerts never sit there looking pending.

#### B10. Hub protocol hardening before any remote client
- **They:**
  - The first frame must be `connect` with a signed device block, or the socket closes.
  - Frames before auth are capped at 64 KiB, with at most 128 unauthenticated connections per IP and a 30 s deadline.
  - Side-effecting methods need **idempotency keys**, kept for 5 minutes, up to 1,000.
  - Events are not replayed: a client that sees a **sequence gap must re-snapshot**.
  - Errors carry `details.code` and `recommendedNextStep`.
  - Files: `docs/gateway/protocol/handshake.md`, `transport.md`, `src/gateway/server-constants.ts`.
- **Snow:**
  - Snow already has a hello deadline, Host and Origin checks, and a snapshot followed by a live stream (`src/snow/hub/server.py`).
  - The HUD stores `last_seq` but does not detect gaps (`hud/src/renderer/src/store.ts:91`).
  - Commands have no idempotency key.
- **Value:** med · **Effort:** S · **Phase:** 4, before the phone HUD in Phase 6.
- **Idea:**
  - Each event carries `seq`. A client that sees `seq != last+1` sends `cmd.snapshot`.
  - Every side-effecting command (approve, stop, mute, send) carries `idem_key`. The hub ignores repeats within 5 minutes, which matters for flaky mobile links.
  - Cap the size of the hello frame.

#### B11. Telegram Mini App as the phone dashboard (option for HUD-11)
- **They:**
  - `/controlui` (direct messages only) sends a WebApp button pointing at the Serve HTTPS URL.
  - The server verifies Telegram `initData` with an HMAC (secret = HMAC-SHA256("WebAppData", botToken)) and requires `auth_date` to be no older than 5 minutes.
  - A replay cache rejects reused hashes.
  - A one-time 32-byte launch ticket (5-minute lifetime, bound to the user id, used once) must also match.
  - Files: `extensions/telegram/src/miniapp/init-data.ts`, `launch-ticket.ts`, `routes.ts`, `docs/channels/telegram/mini-app.md`.
- **Snow:** HUD-11 plans the phone browser over Tailscale with separate pairing.
- **Value:** med · **Effort:** M · **Phase:** 6.
- **Idea:** offer the phone HUD as a Telegram Mini App that is still served only over Tailscale Serve. Telegram identity proves *who* the user is (HMAC plus a one-time ticket), and Tailscale proves *which network* the request came from. That removes a separate login, keeps both checks, and takes one tap from a notification.

#### B12. QR pairing with a single-use bootstrap token (phone HUD)
- **They:**
  - The setup code is base64 JSON `{url, bootstrapToken}` shown as a QR.
  - The token is single-use and lasts 10 minutes, then a device key is paired and a durable per-device token is issued.
  - Loopback connections are auto-approved, but tailnet connections, even from the same host, need explicit approval.
  - Revoking the code does not revoke the paired device.
  - Files: `src/pairing/setup-code.ts`, `docs/gateway/pairing.md`.
- **Snow:** `research/ARCHITECTURE.md` mentions "device pairing" without detail.
- **Value:** low-med · **Effort:** M · **Phase:** 6.
- **Idea:** `snow pair phone` shows a QR on the HUD containing a 10-minute single-use token. The phone exchanges it for a device token that can only read and approve, recorded in the audit log and revocable by voice.

### C. Agent work, tasks and sessions (Phases 2 to 4)

#### C1. A deterministic voice run-control classifier
- **They:**
  - While a voice-launched run is active, spoken input is classified by ordered regex rules into `status | steer | cancel | followup`.
  - Negated cancels ("don't stop") are excluded, and "stop using X" counts as a **steer**, not an abort.
  - Anything unmatched defaults to `status` with `shouldAutoControl: false`, so ambiguous speech never auto-cancels.
  - Follow-ups are wrapped as "incorporate after the current step".
  - Rejections have typed reasons (`no_active_run`, `compacting`…).
  - Spoken "yes" never grants approval.
  - Files: `src/talk/agent-run-control-shared.ts` (about lines 99-184), `docs/nodes/talk/realtime-sessions.md`.
  - Footgun: their status replies are fixed English templates.
- **Snow:** AGNT-06/07 and VOIC-10 are planned for Phase 3, through the LLM. "Snow, stop" is SAFE-06, outside the LLM.
- **Value:** high · **Effort:** S · **Phase:** 2 for cancel, 3 for steer and status.
- **Idea:**
  - A `RunControlClassifier` runs on `transcript.final` before the brain sees it, only while an agent run is active. It does cancel, steer, status, follow-up or none, and is tested on WAV-fixture transcripts.
  - The classifier only *routes*. Every spoken reply stays LLM-written from events.
  - Add Hinglish patterns later for VOIC2-01.

#### C2. Steering rules: never cut a running tool, and confirm the redirect before saying so
- **They:**
  - Steering text is injected after the current tool results and before the next LLM call. A running tool is never interrupted.
  - The unstarted sequential tail of a tool batch is skipped, each with a synthetic "Skipped to process an incoming message" result, so the transcript stays valid. Parallel batches are never skipped.
  - Claude Code is steered through its persistent stream-JSON stdin, and OpenClaw **waits for Claude's input-lifecycle acknowledgement** before recording the steer as accepted.
  - ACP harnesses cannot be steered mid-turn, so the steer is queued.
  - If an answer may have been committed but the confirmation was lost, it is never re-sent.
  - Files: `docs/concepts/queue-steering.md`, `docs/tools/steer.md`, `src/sessions/session-controller.*.ts`.
- **Snow:** AGNT-07 is planned. The fullstack B1 study covers the interrupt and desync guard, but not "acknowledge before claiming".
- **Value:** med · **Effort:** S · **Phase:** 3.
- **Idea:** a `steer.sent` event is followed by `steer.accepted` only after the SDK acknowledges the input. Snow's spoken "okay, switching to SQLite" is generated only from `steer.accepted`, which follows SPCH-06's facts-only rule. For ACP adapters, the event says `steer.queued`.

#### C3. "What's it doing?" as a side question that never touches the agent's history
- **They:** `/btw` snapshots the session, runs a separate one-shot query that answers only the side question, and never writes it to history or steers the main run. File: `docs/tools/btw.md`.
- **Snow:** AGNT-06 says status comes from events. It does not say that status questions must stay out of the Claude Code session.
- **Value:** med · **Effort:** S · **Phase:** 3.
- **Idea:** status is answered by Snow's fast role from recent agent events plus the progress card (C4). Write it down as a rule: a status question is **never** sent into the agent session, because that costs agent tokens and can derail the run.

#### C4. Progress card and a goal-blocked heuristic
- **They:**
  - `progress_card` is a durable status object that is replaced whole: at most 50 steps, at most one `in_progress`, plus a note. Reconnecting clients read the card, not the transcript.
  - A durable goal may be marked `blocked` only after the **same blocker repeats for 3 consecutive turns**.
  - Files: `docs/tools/progress-card.md`, `docs/tools/goal.md`.
- **Snow:** the HUD task board (HAND-09) and the activity stream (HUD-05) are planned, but there is no per-task status object.
- **Value:** med · **Effort:** S · **Phase:** 3, reused in 4.
- **Idea:**
  - A `task.progress` projection built from agent events (for example TodoWrite), replaced whole and capped at 50 steps.
  - It feeds the HUD panel, the Telegram progress message (B6) and spoken status (C3).
  - Notify the user that a task is "stuck" only when the same blocker appears 3 times in a row.

#### C5. Restart recovery invariants for hand-off tasks
- **They:**
  - **Claim before the model call:** the user message, a cleared outcome and a recovery claim are written in one SQLite transaction *before* calling the model. Active runs are stamped at shutdown, and a scan at startup catches hard crashes.
  - **Resume:** a synthetic "you were interrupted, continue from the transcript" turn, and an undelivered final reply is delivered rather than redone.
  - **Charged retry budget:** 3 attempts per interrupted cycle, persisted across restarts, then the session is **tombstoned** until the user resumes or resets it.
  - **Restart-safe tools:** if the transcript tail shows an unknown side effect, the continuation runs with **read-only tools**.
  - **Crash-loop breaker:** 3 unclean boots in 5 minutes enters safe mode, where recovery and side services pause.
  - **Lost background process:** exactly one "outcome unknown, verify before re-running" notice, and nothing is replayed.
  - Files: `docs/gateway/restart-recovery.md` (lines 1-110, 285-330, 849-1170), `docs/gateway/background-process.md`, `src/cron/service/run-recovery.ts`.
- **Snow:** CORE-05 and HAND-01 are in Phase 4. `research/ARCHITECTURE.md` plans a task table with leases and heartbeats, and a reconciler that resumes a task or marks it `interrupted`. The supervisor has capped exponential backoff but no crash-loop safe mode (`src/snow/hub/supervisor.py:40`).
- **Value:** high · **Effort:** M · **Phase:** 4. The crash-loop breaker is S and fits Phase 2.
- **Idea:** add to the planned task table:
  - `attempts_charged` (max 3, then `needs_user`);
  - an `outcome_uncertain` flag set when the last recorded agent action has no result event. Resuming then runs Claude Code in plan or read-only permission mode, with a prompt to verify before acting again.
  - In the supervisor: 3 hub crashes in 5 minutes means start in safe mode (voice and HUD only, no agents, no phone actions), shown on the HUD.

#### C6. Execution status vs delivery status, and alerts that skip the model
- **They:**
  - Run history keeps `status` (did it run) separate from `completionStatus` (was the result delivered).
  - Failure alerts fire after 2 consecutive failures, with a 1-hour cooldown. The same cause counts as one incident, even across restarts.
  - Transient provider errors get grace re-runs at 30 s, 1 min and 5 min before any alert.
  - Auto-disable after 10 failures sends its notice **without a model call**, because the model may be what is failing.
  - Files: `src/cron/service/failure-alerts.ts`, `auto-disable.ts`, `docs/automation/cron-jobs/delivery.md`.
- **Snow:** missing for background tasks. SPCH-01 allows a plain fallback "only when the LLM is down".
- **Value:** med · **Effort:** S · **Phase:** 4.
- **Idea:**
  - Tasks get `exec_state` and `notify_state`.
  - When every provider is down, a task failure reaches the phone as a fixed, non-spoken Telegram text built from event fields (a template of facts, not speech). That is allowed under SPCH-01's LLM-down exception.
  - Group repeated failures with the same cause into one incident.

#### C7. Worktree lifecycle: discard means snapshot, removal must lose nothing
- **They:**
  - **Layout:** worktrees live at `<root>/<sha256(commondir+origin)[:16]>/<name>` on branch `openclaw/<name>`. The base is the **fetched remote default branch**, never a silent fall-back to local HEAD.
  - **Removal is archival:** a synthetic commit of tracked plus non-ignored untracked files is pinned at `refs/openclaw/snapshots/<id>` and can be restored for 30 days.
  - **When a run ends**, the checkout is removed only if `git status --porcelain` is empty **and** `git log HEAD --not --remotes` is empty; otherwise it is kept with a recorded reason.
  - **Clean-up:** idle worktrees are removed after 7 days; when over capacity, merged ones go first, then squash-landed ones, then the oldest. Leases protect live runs.
  - **Checkout:** a 5-minute timeout that resets while git keeps making progress, with repo hooks and file monitors disabled.
  - Weakness: capacity eviction can purge a dirty worktree if the snapshot fails.
  - File: `docs/concepts/managed-worktrees.md` (lines 128-160, 253-275, 344-560).
- **Snow:** HAND-06 and HAND-07 are in Phase 3: a worktree per task and one-command accept or discard.
- **Value:** high · **Effort:** S-M · **Phase:** 3.
- **Idea:**
  - "Discard" first commits a snapshot to `refs/snow/snapshots/<task_id>`, kept 30 days, so "undo that discard" works by voice.
  - Accepting or removing checks for an empty porcelain status and no unpushed commits.
  - Never evict a dirty worktree.
  - Pass `core.hooksPath` pointing to an empty directory for Snow's own git calls inside agent worktrees, so a cloned repo's hooks never run under Snow.

#### C8. Self-upgrade: a canary on copies, and rollback only when the schema is unchanged
- **They:**
  - **Before switching:** the candidate build passes doctor lint plus an **isolated canary boot against copied config and DB snapshots** while the old process keeps serving.
  - **After switching:** verify the service owns its port, the hello handshake reports the expected version, and the readiness checks pass.
  - **Rollback rule:** automatic rollback only if every SQLite `user_version` and the config are unchanged. Otherwise rollback is refused (`state-migrated-no-rollback`) and a bounded repair runs.
  - **On Windows,** Scheduled Task autostart is suspended until verification passes.
  - **Restart sentinel:** a row written before the restart posts "I'm back, here's the outcome" to the originating chat.
  - **Triage:** a failed update hands the captured failure to an available coding agent.
  - File: `docs/gateway/restart-recovery.md` (lines 698-848, 1272-1312).
- **Snow:** CORE-07 (approved upgrade with automatic rollback) is in Phase 3. The SQLite migrations live in `src/snow/hub/migrations/`.
- **Value:** high · **Effort:** M · **Phase:** 3.
- **Idea:**
  - `snow upgrade` copies `snow.db` and `config/` to a temp directory, boots the candidate hub headless against the copies with `--canary`, waits for every worker heartbeat, then kills it.
  - Only after that does Snow ask the user to approve.
  - Back up the DB before any migration. Roll back automatically only when `user_version` is unchanged; otherwise restore the backup together with the old build.
  - Disable the logon task during the swap.
  - Write an `upgrade.sentinel` event so the next boot generates the "I'm back on version X" line.

#### C9. Model failover details Snow lacks
- **They:**
  - **Cooldowns:** **model-scoped** where possible, so a sibling model on the same provider stays usable; they escalate 30 s, then 1 min, then 5 min.
  - **Retry-After:** honoured as a minimum, but SDK-internal sleeps are capped at 60 s so failover can proceed.
  - **Hard failures:** billing or auth failures disable the profile for 10 minutes.
  - **Terminal errors:** a Groq `413 … tokens per minute (TPM)` is treated as terminal (no compaction retry).
  - **Weakness:** their skip cache is in memory only.
  - File: `docs/concepts/model-failover.md` (lines 1-130, 233-520).
- **Snow:**
  - `src/snow/brain/limits.py` has header-driven cooldowns per *provider*, in memory only. Line 98 says: "shortcut: counters restart at zero when the brain restarts".
  - `chain.py` `classify` treats 413 as `service_error`, so it falls over to the next provider, which is probably right for Snow.
- **Value:** med · **Effort:** S · **Phase:** Phase 1 polish or Phase 2.
- **Idea:**
  - Persist `cooldown_until` per provider (and per model) through the hub's `set_state` (`src/snow/hub/eventlog.py:117`). Then a crash-looping brain cannot hammer a provider that is still cooling down and earn a longer ban.
  - Key cooldowns on `(provider, model)` when the error names a model-level limit.

### D. Memory (deepens SEED-261019-mnj item 3; needs the memory requirement first)

#### D1. Trust stored in columns set by code, plus a taint flag per turn
- **They:**
  - Every memory chunk has a provenance row with a STRICT CHECK `origin_class ∈ {owner, agent, untrusted, system}`, plus `session_kind` (`interactive`, `cron`, `heartbeat`, `subagent`), `observed_at` and `supersedes_key`.
  - These values come from classification code, never from memory text. Unknown provenance is never treated as owner.
  - At file level, a hash chain makes quarantine sticky: a write counts as `agent` only if the previous record was `agent` and its hash matches the file.
  - After any tool result marked `resultContentSource: "network"`, every memory write in the rest of that turn is `untrusted`.
  - Only `owner` or `agent` content from interactive sessions can be promoted.
  - Gap: local file reads do not taint the turn.
  - Files: `src/state/openclaw-agent-schema.sql` (about lines 680-704), `src/memory/memory-artifact-provenance.ts`, `src/agents/embedded-agent-runner/run/turn-taint-state.ts`, `src/agents/agent-tools.ts`.
- **Snow:** the memory requirement is not filed yet. The seed plans a profile with audit and undo, but no trust model.
- **Value:** high · **Effort:** S-M · **Phase:** the memory phase (the slice proposed for Phase 2).
- **Idea:**
  - A `memory_entry` row with `origin` CHECK `('owner_voice','owner_typed','agent','external','system')`, set from the A7 turn-taint bit.
  - Only `owner_*` entries may change the profile.
  - Anything learned in a turn that saw Claude Code output, a web page or screen text is stored as `external` and never injected automatically.

#### D2. Consolidation as operations, with guards, and undo through the stored previous version
- **They:**
  - The model returns add, merge or supersede *operations*, and code builds the file.
  - A rewrite is rejected if it loses more than 25% of entries, drops a `Source:` citation, exceeds the budget or fails to parse; the fallback is append-only.
  - The content hash is re-checked before an atomic rename, the previous version is stored in SQLite, and a diff summary is written.
  - A contamination filter stops the system from learning from its own artefacts.
  - Promotion needs a score of at least 0.75, at least 3 recalls and at least 3 distinct queries, at most 10 per sweep, with a 14-day half-life.
  - Files: `docs/concepts/dreaming.md`, `src/memory-host-sdk/dreaming.ts`, `extensions/memory-core/src/dreaming-consolidation*.ts`.
- **Snow:** the seed plans that Snow edits the profile itself with an audit trail and undo, but gives no mechanics.
- **Value:** high · **Effort:** S · **Phase:** memory phase.
- **Idea:**
  - Profile edits are typed ops: `{op: add|supersede|remove, entry_id, text, source_event_seq}`.
  - Code applies them, refuses any batch that removes more than 25% of entries, stores the pre-image row, and publishes `memory.changed` with a diff.
  - "Snow, undo that" restores the pre-image.

#### D3. Recall with no model call, within the one-second voice budget
- **They:**
  - Curated entries carry inline tags such as `<!-- trigger: gateway setup --> <!-- importance: 9 -->`.
  - On each inbound message, up to 24 candidates are scored: phrase score × 0.8 + hybrid relevance × 0.2, against a threshold of 0.65.
  - At most 3 entries and 1,800 characters are injected, XML-escaped and cited.
  - Only promoted, trusted entries qualify; daily notes never auto-inject.
  - Hybrid search: BM25 plus vectors, then MMR (λ 0.7), with a 30-day decay applied only to dated notes. `minScore` 0.35 is applied *before* decay, so old notes stay eligible but rank lower.
  - Files: `extensions/active-memory/trigger-recall.ts`, `extensions/memory-core/src/memory/{hybrid,temporal-decay,mmr}.ts`.
- **Snow:** the plan has FTS5 with a target under 50 ms (`research/ARCHITECTURE.md`), but no injection rule.
- **Value:** high · **Effort:** M · **Phase:** memory phase.
- **Idea:**
  - Before each brain call, an FTS5 match on the final transcript against `memory_entry.triggers` for trusted entries only.
  - Inject at most 3 entries and at most 1,500 characters, with a 50 ms deadline; if the deadline passes, inject nothing.
  - Calibrate on Snow's own STT spelling variants, because Groq Whisper spellings differ.

#### D4. The profile as directives that are superseded in place, under a hard cap
- **They:**
  - Each entry in USER.md is `<!-- observed: YYYY-MM-DD | status: active|superseded -->` followed by one "Always / Never / Prefer" line.
  - A changed preference supersedes the old entry *in place*, because models answer from stale preferences when the correction is appended elsewhere (the docs cite PrefEval and HorizonBench).
  - The USER file is capped at 4,000 characters, and config can only lower that.
  - When `AGENTS.md` is truncated, lines containing must, never, security or secret are kept from the cut middle as a "policy digest".
  - Files: `docs/concepts/user-model.md` (lines 370-440), `src/agents/embedded-agent-helpers/bootstrap.ts:90`.
- **Snow:** the seed plans a short profile.
- **Value:** med · **Effort:** S · **Phase:** memory phase.
- **Idea:**
  - Profile entries are `{text, observed, status}`, and supersede marks the old row.
  - The prompt includes only `active` rows, under a hard cap.
  - Snow's own safety lines in `config/persona.toml` are never subject to truncation.

#### D5. Forget means tombstones, plus an admission policy
- **They:**
  - `memory forget --session|--participant [--dry-run]` removes promoted entries, index chunks and vectors, previous versions, and lines that quote the session.
  - Forgotten sessions are tombstoned, and indexing re-checks the tombstones, so a re-index cannot resurrect them.
  - Admission policy keeps sources such as email out of ingestion entirely.
  - Weaknesses: paraphrases survive, and the command runs immediately with no confirmation unless `--dry-run` is passed.
  - Files: `docs/concepts/memory-provenance.md`, `extensions/memory-core/src/memory-forget*.ts`, `memory-session-tombstones.ts`.
- **Snow:** missing. The event log has `purge_content` for retention (`src/snow/hub/eventlog.py:124`).
- **Value:** med · **Effort:** M · **Phase:** memory phase.
- **Idea:** "Snow, forget what I said about X" shows the matching entries on the HUD and, after confirmation, deletes them and writes `memory_tombstone(source_event_seq)`. The indexer skips tombstoned sequence numbers.

#### D6. A memory flush before compaction, plus a compaction budget that favours the user's words
- **They:**
  - **Flush:** 4,000 tokens before the compaction threshold, a silent turn runs that may only *append* new, non-duplicate text to today's note. The core files are read-only, it may answer `NO_REPLY`, and it never blocks the reply.
  - **Compaction input:** half the newest messages verbatim, a quarter of the user's older asks, decisions and corrections (each trimmed to 2,000 characters), a tenth of the oldest messages, and "N messages omitted, don't guess" markers.
  - **Integrity:** tool-call and result pairs are never split, and opaque IDs are preserved.
  - **Degraded summaries:** a failed summary audit is flagged with a visible warning.
  - Files: `extensions/memory-core/src/flush-plan.ts`, `src/agents/memory-flush-content.ts`, `docs/concepts/compaction.md`.
- **Snow:** six turns kept in RAM (`src/snow/brain/persona.py` `History`); nothing is compacted yet.
- **Value:** med · **Effort:** S · **Phase:** memory phase, or whenever history grows past six turns.
- **Idea:** when Snow moves to a longer rolling history, the summariser gets the user's own corrections first. Before any summarisation, the fast role writes new facts to the daily note.

#### D7. Memory scoped per project
- **They:** memories written inside a git repository are tagged with the normalised `origin` remote. Search boosts active repositories, and trigger injection requires every project key on the entry to be active. The user profile is never project-scoped. File: `extensions/memory-core/src/memory/project-ranking.ts`.
- **Snow:** missing. Snow will drive Claude Code across several repositories, Snow included.
- **Value:** med · **Effort:** S · **Phase:** memory phase.
- **Idea:** `memory_entry.project = normalised git remote of the task's repository, or NULL`. Recall filters to the active task's project plus global entries, so a workaround learned in one repository never steers another.

#### D8. A recall sub-agent behind a cheap gate
- **They:**
  - A regex for recall intent ("last time", "do you remember", "what did we decide", "N days ago") must match, *and* the no-model recall (D3) must have found nothing strong. Only then does a sub-agent run.
  - The sub-agent may only search and get memory, sees 4,000 characters, returns at most 220 characters or `NONE`, and times out after 15 s.
  - A circuit breaker trips after 3 timeouts and cools down for 60 s.
  - The docs recommend `gpt-oss-120b`.
  - Files: `extensions/active-memory/escalation.ts`, `docs/concepts/active-memory.md`.
- **Snow:** missing. The fast role is already Groq `gpt-oss-120b` (`config/models.toml`).
- **Value:** med · **Effort:** M · **Phase:** memory phase.
- **Idea:** the same gate, but with a timeout of about 1.5 s to fit the voice budget. While it runs, Snow speaks an LLM-written "let me think back…" acknowledgement (from Snow's acknowledgement pool, `src/snow/brain/acks.py`). Add Hinglish recall phrases.

### E. Scheduling and proactivity (later milestone; Snow has no scheduler)

#### E1. Scheduler semantics after downtime and sleep
- **They:**
  - **Schedule kinds:** `at`, `every`, `cron`+tz, `on-exit` (fire when a watched command exits) and `stream` (fire on batched stdout lines).
  - **After downtime:** overdue agent jobs are rescheduled, not run during startup. Catch-up is capped at 5 per restart, staggered by 5 s. After sleep, elapsed deadlines are coalesced so each runs once. One-shots always catch up.
  - **Never auto-replayed:** command and script jobs, and any job that might already have delivered.
  - Footgun: croner ORs day-of-month with day-of-week.
  - Files: `src/cron/types.ts`, `src/cron/service/timer-execution-timeout.ts:37`, `docs/automation/cron-jobs/how-it-works.md`.
- **Snow:** missing. Reminders ("remind me at 5") and "tell me when the build finishes" are natural voice requests; AWAR-02 is deferred.
- **Value:** med · **Effort:** M · **Phase:** after Phase 4, though `on-exit` fits Phase 4 hand-off.
- **Idea:** a `schedule` table in the hub DB, managed by the hub with a 1 s tick. One-shots catch up once, recurring jobs coalesce, and side-effecting jobs are never replayed. An `on-exit` trigger on an agent task gives "tell me when it's done" for free.

#### E2. Deterministic gates before any model call, and a silence token
- **They:**
  - Condition scripts return `{fire:false}`, so no model call happens.
  - An unattended run may answer exactly `NO_REPLY`, and only that exact token suppresses delivery. The reason is recorded.
  - A first result that is only an interim "on it" is re-prompted once for the real result.
  - Heartbeat defaults: do not rehash old chats, skip when the session is busy, respect active hours in the user's time zone, and apply a flood guard (5 starts in 60 s).
  - Files: `docs/automation/cron-jobs/payloads.md` (lines 364-404), `docs/gateway/heartbeat.md`, `src/cron/heartbeat-monitor.ts`.
- **Snow:** proactivity is out of scope for v1, but HAND-08 says Snow never starts the brief on its own.
- **Value:** low-med · **Effort:** S · **Phase:** the proactivity milestone.
- **Idea:** when proactivity lands, every proactive check is a cheap local predicate first. The LLM sees it only when the predicate fires, it must return a `{speak: bool}` header, and active hours plus the user's current "do not disturb" state gate it.

#### E3. Standing intents: prospective memory with built-in anti-nagging limits
- **They:**
  - "When X comes up, do Y" is stored as a SQLite row: up to 24 trigger keywords, scopes, `expiresAt`, `maxFires`, a cooldown, and a lifecycle of `pending → armed → fired → done | cancelled | expired`.
  - Defaults: 24 h cooldown, at most 3 fires, 90-day expiry, at most 3 intents and 1,200 characters injected per turn.
  - Matching is an FTS prefilter with no model call.
  - Cancellation is always explicit.
  - Files: `extensions/memory-core/src/standing-intents*.ts`, `docs/concepts/standing-intents.md`.
- **Snow:** missing.
- **Value:** med · **Effort:** M · **Phase:** memory phase or later.
- **Idea:** "next time I open the Snow repo, remind me about the AEC bug" becomes an intent row matched against task-start and transcript events, using those default limits.

### F. Operations, configuration and setup

#### F1. Doctor deepens: separate detect and repair, JSON output, shared with startup
- **They:**
  - Each check has `detect()` and `repair()`.
  - Findings carry `checkId, severity, message, path, fixHint`.
  - `--lint --json` uses a versioned envelope with exit codes 0, 1 and 2.
  - Startup applies the same prompt-free migrations and changes stale `running` sessions to `interrupted`.
  - Doctor reports tombstoned sessions, providers in cooldown, the reasons jobs were auto-disabled, stale locks and oversized prompt files.
  - Migrations take a backup and run `quick_check`, and refuse while another process owns the state.
  - Files: `src/flows/doctor-core-checks.ts`, `docs/gateway/doctor/checks.md`.
- **Snow:** `snow doctor` is planned (fullstack G1).
- **Value:** med · **Effort:** S · **Phase:** 2.
- **Idea:** build `snow doctor` as a list of `Check(id, detect, repair?)` with `--json`, so Claude Code can run it and parse the result while repairing Snow. The hub calls the same repair-free checks at boot and publishes failures to the health panel.

#### F2. Config guards, because Snow and Claude Code will edit config
- **They:**
  - Unknown keys stop startup.
  - A last-known-good copy is kept, but restored only by `doctor --fix`.
  - Writes are atomic renames with a `.bak` ring.
  - A write that shrinks the file by more than half is blocked and saved as `.rejected.<ts>`.
  - A write containing `***` or `[redacted]` placeholders is never promoted to last-known-good.
  - An invalid hot reload is skipped and the previous config keeps running.
  - Files: `docs/gateway/configuration.md`, `docs/gateway/configuration/hot-reload.md`.
- **Snow:** TOML files in `config/`, loaded through pydantic settings (`src/snow/config/settings.py`). There are no write guards, and Claude Code working on Snow's repo is planned.
- **Value:** med · **Effort:** S · **Phase:** 2 or 3.
- **Idea:**
  - After each healthy boot the hub copies `config/*.toml` to `data/config.lkg/`.
  - If the config does not parse at boot, Snow boots from the last-known-good copy *and* raises a HUD alert, so an always-on assistant is never down because of a typo.
  - `snow doctor` shows the diff.

#### F3. Setup checks each provider with a real completion before saving
- **They:** quick start detects candidates read-only, **verifies the chosen one with a real completion before saving anything**, never switches provider automatically after a failure, and resumes an interrupted setup. File: `docs/start/wizard.md` (lines 8-154).
- **Snow:** `snow setup` stores keys (`src/snow/config/setup.py`), and `snow dev probe-models` is separate.
- **Value:** low-med · **Effort:** S · **Phase:** 7, or as a quick task.
- **Idea:** `snow setup` runs a one-token completion against each provider before saving its key, and shows ok, bad key or unreachable.

#### F4. A local classifier role for fast routing without the LLM
- **They:** a `decisionModel` role with a typed result (choice, score or yes/no) that can run local CPU ONNX zero-shot classifiers (GLiClass Edge/Base, DeBERTa zero-shot, GLiNER) in a persistent subprocess. It is used for routing and tool filtering. Files: `docs/concepts/decision-models.md`, `docs/plugins/onnx.md`, `src/decisions/`.
- **Snow:** PCTL-01 and PCTL-02 require a fast path "without waiting on the LLM" (Phase 5). There is no design for the intent router yet.
- **Value:** med · **Effort:** M · **Phase:** 5.
- **Idea:** first, exact phrase rules (C1 style). Second, a small CPU ONNX zero-shot classifier (GLiClass-Edge size) over a fixed intent list, run in the voice or brain process under a 30 ms budget. Only "none" goes to the LLM. Measure it against the WAV fixture transcripts.

---

## 2. Security incidents and known weaknesses Snow must avoid

**Public incidents (2026, from secondary sources; counts vary by reporter):**
1. **CVE-2026-25253 / GHSA-g8p2-7wf7-98mq: one-click remote code execution.**
   - The Control UI accepted `gatewayUrl` from the URL query string (the feature was added in `CHANGELOG/2026.1.20.md`, "allow Control UI to read gatewayUrl from URL params") and connected automatically, sending the stored token.
   - A crafted link therefore stole the token, even for a localhost-bound gateway.
   - It was hardened in `CHANGELOG/2026.2.14.md` and `2026.2.22.md`.
   - **Snow rule:** the HUD never takes a hub URL or token from its own URL, a deep link or a page. They come only from the Electron main process environment (`hud/src/main/hubinfo.ts`, as today). Keep Host and Origin checks (`src/snow/hub/server.py` `_check_request`). The only URL parameter the HUD reads today is the test flag `snowtest` (`hud/src/renderer/src/levels.ts:28`); keep it that way.
2. **Exposed gateways.** Between about 17,500 and more than 40,000 internet-reachable instances, mostly through no-auth mode or reverse proxies that made "localhost-trusted" connections public.
   - **Snow rule:** never treat loopback as trusted when a proxy is involved; use a separate listener for Tailscale (B7); never use Funnel; refuse to start a remote listener without a token.
3. **ClawHub supply chain ("ClawHavoc").** 341 of 2,857 skills were malicious by one count, about 900 (≈20%) by another. Most told users to install fake prerequisites that dropped an infostealer. VirusTotal scanning was added later and still misses prompt-injection skills.
   - **Snow rule:** no third-party skill or MCP marketplace in v1. Pin exact MCP versions with integrity hashes, use a fail-closed install policy (A9), and never auto-load tool code from a repository Snow works on (GHSA-99qw-6mr3-36qr).
4. **CVE-2026-24763: Docker sandbox escape through PATH manipulation.**
   - **Snow rule:** fixed PATH for children, no PATH override (A6), and re-verify the executable identity before launch (A2).
5. **Moltbook (an agents' social network, not OpenClaw core).** A misconfigured Supabase database exposed every agent's API keys and claim tokens. Users had connected email and SMS-reading assistants to it.
   - **Snow rule:** never connect Snow to an agent-to-agent network. Treat any public input feed as `external` (A7).
6. **Prompt-injection evaluation.** A third-party ZeroLeaks run reported a 91% injection success rate and 84% system-prompt extraction, including SOUL.md and AGENTS.md.
   - **Snow rule:** the persona prompt is not a secret, so put no secrets in it. Make safety structural (A1-A3, A7), never prompt-only.

**Weaknesses the repository itself documents** (`SECURITY.md`, `docs/security/THREAT-MODEL-ATLAS/*.md`, `CHANGELOG/*.md`; 34 GHSA IDs in the changelogs):
- **Permissive defaults:** host exec defaults to `security=full, ask=off` and the sandbox is off. Their own threat model rates this residual risk Critical (T-IMPACT-001). The YOLO preset sets `askFallback: full`.
  - **Snow:** the fallback is always deny, and that is not configurable.
- **The model is not trusted, yet an LLM reviewer can *grant* (`allow`).** The reviewer also sees unmasked secrets.
  - **Snow:** if a reviewer is ever added, it may only deny or escalate.
- **Plugins and skills run in-process with no sandbox and no signing.** T-PERSIST-001 and T-EXFIL-003 are Critical. Updates can pull malicious versions (T-PERSIST-002).
- **Plaintext token and secret store** (T-ACCESS-003). Transcripts and tool results keep credentials verbatim.
- **No per-sender rate limiting** ("Current mitigations: None", T-IMPACT-002). `web_fetch` to any URL remains an exfiltration channel (T-EXFIL-001).
- **Best-effort audit** with no tamper evidence (A10). **No kill switch outside the process**; containment is "terminate the gateway".
  - **Snow:** SAFE-06 is already stronger. Keep it.
- **Approval UI spoofing** with zero-width and bidi characters (GHSA-pcqg-f7rg-xfvv), and Unicode tricks against obfuscation checks (GHSA-9r3v-37xh-2cf6). See A5.
- **Self-declared scopes** on shared-token connects (GHSA-rqpp-rjj8-7wv8), and a **cross-site WebSocket hijack** that granted admin (GHSA-5wcw-8jjv-m286). See A1; this is Snow's live issue.
- **Privilege escalation through device-token rotation**, rated critical (GHSA-4jpw-hj22-2xmc).
  - **Snow:** only the HUD on the PC may mint or rotate phone tokens, and every mint or rotation needs a fresh approval.
- **A subagent wrote into its parent session** (GHSA-wcxr-59v9-rxr8), and **sandboxed subagents read sibling transcripts** (GHSA-72fw-cqh5-f324).
  - **Snow:** when parallel tasks arrive (PARA-01), each task's events are scoped by `task_id`, and an agent adapter can read only its own task's events.
- **Bypasses of the command allowlist** (about 30 fixes; see A3). Among them: `$()` inside double quotes, heredocs, `BASH_ENV`/`LD_*`, a `cmd.exe /c` trailing-argument mismatch, `HOME`/`ZDOTDIR` injection, `sort --compress-program`, Ruby `-r` and Perl `-M`, the `time` wrapper, and `COMSPEC` in a workspace `.env`.
- **Telegram defaults that leak:**
  - `dmPolicy: pairing` lets strangers reach the bot and get replies.
  - Approval cards show full commands in a chat that is not end-to-end encrypted.
  - Link previews are on.
  - Delivery is at least once, so a side effect can repeat after a crash.
  - **Snow:** use an allowlist only, minimal card text (B9), turn link previews off, and add the dedupe and stale-update guard (B1).
- **Loopback counts as trusted, including over SSH port-forwards.** That gives silent pairing and scope upgrades, and the auth rate limiter exempts loopback.
  - **Snow:** a loopback connection still needs a role token (A1), and the phone listener is a separate port (B7).
- **Formal-verification claims rest on a TLA+ models repository that is unreachable and has no CI** (`docs/security/formal-verification.md`). Do not cite it as assurance.

---

## 3. What Snow already does better (do not regress)

| Area | Snow | OpenClaw |
|---|---|---|
| Default posture | Fail-closed tiers, timeout means deny, no auto-approve, the LLM can only raise a tier (planned SAFE-01..05) | Host exec `full` with no prompts by default; the sandbox is off; the LLM reviewer can grant |
| Kill switch | Voice, hotkey and HUD, outside the LLM (SAFE-06) | Kill the process |
| Secrets at rest | Windows Credential Manager with a canary test (SAFE-09) | Plaintext SQLite (0600) |
| Audit | Append-only, redacted and separate from display history (SAFE-11) | Best-effort and lossy by design |
| Presence routing | At the PC: voice and HUD; away or locked: phone; unknown counts as away (SAFE-04) | An activity roster of OpenClaw use only; no lock signal, no away routing |
| Provider privacy | Data-trust level per provider; private data never goes to untrusted providers (SAFE-12) | Not by provider trust; reviewers and summaries see raw transcripts |
| Speaker identity | Speaker verification gates commands (VOIC-07) | None; Talk mode trusts the microphone |
| Windows autostart | Logon task already sets no 72-hour limit, runs on battery, restarts on failure, IgnoreNew (`src/snow/hub/autostart.py:38-42`) | Same settings (`src/daemon/schtasks-xml.ts:44-58`), so this is parity, not a gap |
| Spoken wording | Every spoken word is written by the LLM | Fixed English status and approval templates in Talk |
| Tool isolation | MCP servers as separate processes behind a policy gate | Plugins in-process as part of the trusted computing base |

---

## 4. Skip list

- **The multi-channel catalogue** (WhatsApp, Discord, Slack, Signal, iMessage, Matrix and about 30 more), plus group-chat semantics, access groups and broadcast groups. Snow is single-user with Telegram only.
- **ClawHub, a skills marketplace and the in-process plugin SDK.** They are the source of their worst incidents.
- **Docker, Podman, SSH and cloud sandbox backends.** Snow drives Claude Code on the host inside worktrees; a container stack is too heavy for this laptop.
- **Team or shared Gateways, multi-user sessions, Git co-author credit.** Out of scope for v1.
- **Dreaming as a 3-phase nightly LLM sweep with weighted ranking.** Take its guards (D2), not its machinery.
- **The macOS active-computer node, Wear OS, Assistant App Actions, notification forwarding.** Platform-specific or off-mission.
- **Fixed-template spoken status, and the fixed "look at the screen" phrase.** These violate SPCH-01. Snow's rule is the same, but the wording is LLM-written.
- **The 1,500-line recovery "custody, fence, authority" vocabulary.** Copy the five invariants in C5 only.

---

## 5. Ranked top 8

| # | Item | Why | Value | Effort | Phase |
|---|---|---|---|---|---|
| 1 | **A1: tokens per role, the role taken from the token, `SNOW_*` stripped from agent children** | A live hole: any token holder can claim `dev` (fake transcripts) or `hud` (soon, approvals). OpenClaw shipped the same bug as GHSA-rqpp-rjj8-7wv8 | high | S | 2 (first task) |
| 2 | **A2 + A3: approvals bound to a plan hash and re-checked just before launch; shell, interpreter and wrapper calls high tier by default; parsing may only raise a tier** | Their allowlist was bypassed about 30 times; binding to the plan hash is what makes a spoken "yes" mean exactly what runs | high | S-M | 2 |
| 3 | **A7 + D1: an `origin` field on every content event, a per-turn taint bit that raises tool tiers, random-id wrappers around agent, screen and web text** | Makes SAFE-08 structural and is the foundation of memory trust; their wrappers alone kept getting bypassed | high | M (contract field S) | 2 |
| 4 | **B1 + B2 + B3: Telegram durable ingress (store before acknowledging, dedupe, drop stale updates), one poller per token with a watchdog, versioned callback pointers with a `from.id` re-check and first-answer-wins edits on every surface** | The whole phone-approval path, with every failure mode they hit already solved | high | S-M | 4 (atomic resolve in 2) |
| 5 | **C5 + C6: claim before the model call, 3 charged retries then needs-user, read-only resume when an outcome is uncertain, a crash-loop safe mode, separate execution and delivery status, failure notices that work with the LLM down** | Turns "tasks survive restarts" (CORE-05) into concrete, testable rules and prevents replaying a destructive step | high | M (crash-loop breaker S) | 4 (breaker in 2) |
| 6 | **C7 + C8: discard snapshots to a ref kept 30 days, removal must lose nothing, the base is the fetched remote; upgrade canary against a copied DB and config, rollback only when the schema is unchanged, autostart suspended during the swap** | Phase 3's accept and discard and the self-upgrade (CORE-07) are where data and Snow itself can be lost | high | M | 3 |
| 7 | **B7 + B8: Tailscale header checked with `whois` on a listener only Serve can reach; presence that ignores Snow's own synthetic input** | Closes the "trusted localhost through a proxy" class behind their exposed-gateway incident, and stops Snow's own clicks from routing approvals to an empty desk | high | S | 4 (B8 before 5) |
| 8 | **C1 + C2: a deterministic run-control classifier (cancel, steer, status, follow-up; ambiguous never cancels) ahead of the LLM, and redirects confirmed only after the SDK acknowledges them** | Makes "stop", "use Postgres instead" and "what's it doing?" fast and reliable without breaking the no-script rule | high | S | 2-3 |

**Next in line:**
- A5, approval text sanitising and typed scopes (S, Phase 2).
- A6, an allowlist environment for agents (S, Phase 2).
- C9, persisted cooldowns per model (S, Phase 1 polish).
- D2 + D3, memory operations with a loss guard and no-model trigger recall (memory phase).
- B9, lock-screen-private notifications (S, Phase 4).
- F2, last-known-good config (S, Phase 2/3).
- F4, a local ONNX intent classifier (M, Phase 5).
- E1, scheduler semantics (later).

---

## Sources

- Repository: https://github.com/openclaw/openclaw (MIT), read locally.
- Security coverage (secondary, counts vary):
  - https://www.immersivelabs.com/resources/c7-blog/openclaw-what-you-need-to-know-before-it-claws-its-way-into-your-organization
  - https://blog.barrack.ai/openclaw-security-vulnerabilities-2026/
  - https://www.digitalocean.com/resources/articles/openclaw-security-challenges
  - https://clawtrust.ai/blog/openclaw-security-341-malicious-skills-and-what-we-do-about-it
  - https://particula.tech/blog/openclaw-security-crisis-malicious-ai-agents
  - https://blog.cyberdesserts.com/openclaw-malicious-skills-security/
  - https://www.sangfor.com/blog/cybersecurity/openclaw-ai-agent-security-risks-2026
- Moltbook and prompt injection:
  - https://www.implicator.ai/moltbook-left-every-ai-agents-api-keys-in-an-open-database-security-researcher-finds/
  - https://the-decoder.com/openclaw-formerly-clawdbot-and-moltbook-let-attackers-walk-through-the-front-door/
  - https://gigazine.net/gsc_news/en/20260202-moltbook-database-leaked

**Not checked:**
- I did not trace in code the session-pruning thresholds, the compaction budget split, or the Telegram webhook mode.
- ClawHub's moderation code lives in a separate repository (`openclaw/clawhub`) and was not read.
- The CVE numbers and exposure counts come from secondary press and could not be matched to an advisory in the cloned changelogs, which list GHSA IDs only.
