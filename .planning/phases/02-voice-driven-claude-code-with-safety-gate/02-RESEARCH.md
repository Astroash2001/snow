# Phase 2: Voice-Driven Claude Code with Safety Gate - Research

**Researched:** 2026-10-27
**Domain:** agent control (Claude Agent SDK on Windows), deterministic policy gate, approvals, kill switch, speaker-gated commands, pinned running copy
**Confidence:** MEDIUM-HIGH (SDK and docs read this session; Claude Code runtime behaviours marked [ASSUMED] need the live smoke test in slice 4)

## Decisions the user must make in the morning (short list)

| # | Decision | Recommendation |
|---|----------|----------------|
| D1 | **Whose Claude login, and the terms.** STATE.md calls the account "borrowed". Anthropic's current wording: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK" [CITED: code.claude.com/docs/en/agent-sdk/overview]; and since 2026-10-07 "the Claude Agent SDK and claude -p still draw from your subscription limits" when signed in [CITED: support.claude.com/en/articles/15036540]. | Use only the user's OWN login on the user's own PC (a personal tool, not "offering" a login). If the account belongs to someone else, or Snow is ever distributed, switch to an API key. Keep the adapter provider-neutral. Not legal advice. |
| D2 | **Which `claude` binary and which SDK pin.** | SDK `claude-agent-sdk==0.2.164` (newest release before the 2026-10-08 cutoff, no override needed). Point `cli_path` at the user's own `~/.local/bin/claude.exe` (installed: 2.1.311), floor 2.1.302; fall back to the SDK-bundled CLI. The SDK refuses `.cmd` shims on Windows. |
| D3 | **Approve the package gate.** The seam rates `claude-agent-sdk` SUS ("too-new", "unknown-downloads": it keys on the 2026-10-24 upload, not the pin). It adds `mcp`, `starlette`, `sse-starlette`, `uvicorn`, `pyjwt`, `cryptography`, `python-multipart`, `httpx2` to the lock (dry resolve below). | Approve with `==0.2.164` and hash-locked `uv.lock`; CI pip-audit already exists. |
| D4 | **Kill switch details.** (a) Global hotkey owner and key combo; (b) "Snow, stop" only works while Snow is awake or as "Hey Snow, stop", because the only wake model is "Hey Snow" and a second always-on stop model is not trained; (c) stop is accepted from ANY voice (fail-safe direction). | (a) Hub-owned `RegisterHotKey` thread (survives a HUD crash), HUD button as second path; Electron `globalShortcut` is optional extra. (b) accept the limitation for v1. (c) yes, any voice may stop, never approve. |
| D5 | **Spoken approvals.** Verification is unreliable under about 0.5 s of speech (genuine mean 0.55, min 0.07 at 0.5 s [VERIFIED: 261026-wvr-RESEARCH.md table]). | `ask` tier: a spoken approval counts only if the utterance has at least 0.8 s of speech and a fresh verified score; otherwise Snow asks again or the user clicks the HUD. `always_ask` tier: HUD click, or verified spoken phrase with at least 1.0 s. Never a bare "yes". |
| D6 | **Taint aggressiveness.** After the agent has ingested external content (web, MCP, cloned third-party repos), how much starts asking? | Recommended default in the Taint section (shell, network, writes outside the project, push). User to confirm. |
| D7 | **Pinned copy layout (CORE-06).** User config and models move out of the repo to `%LOCALAPPDATA%\Snow\{config,models}`; keep the last 2 releases. Autostart re-pointed to the release. | Yes (see slice 6). Models are git-ignored and loaded from `repo_root()/"models"` in five places today. |
| D8 | **What may Claude work on in Phase 2?** Worktree isolation is Phase 3. | Project registry (`config/projects.toml`, name to path allowlist). Snow's own repo is allowed (dogfooding) because the running copy is separate; other paths need `always_ask`. |
| D9 | **LLM "raise-only" reviewer in Phase 2?** SC-2 says the LLM can raise a tier. | Ship the `raise_tier()` seam and tests now, default OFF (adds latency to every hook call and sends command text to a provider). Turn on after the gate is proven. |
| D10 | **Prerequisite.** Speaker verification (`SpeakerVerifier`, `snow dev enroll-voice`) is quick task 261026-wvr plan 02, NOT executed yet (no `src/snow/voice/speaker.py` exists; plan 01 only). | Execute 261026-wvr-02 first, or fold it into slice 3. VOIC-07 cannot be verified without an enrolled voiceprint. |

<user_constraints>
## User Constraints (from CONTEXT.md)

No `02-CONTEXT.md` exists yet (pre-discussion research; the discussion is tomorrow morning). Treat the following as binding anyway because they are in CLAUDE.md, ROADMAP.md and REQUIREMENTS.md:

### Locked Decisions
- Claude Code only in v1, behind the generic adapter contract; Snow spawns the user's own `claude` and never reads its tokens (ROADMAP Phase 2 notes).
- Build order inside the phase: speaker verification, the deterministic policy gate and the durable approval object come before the adapter is wired (ROADMAP Phase 2 notes).
- Kill switch runs outside the LLM path (own listener, hotkey hook, supervisor signal).
- The LLM can raise a tier, never lower it; an unanswered approval times out to deny and stays pending on the HUD.
- Electron HUD over loopback WebSocket; Python 3.12 core; uv with hash-locked deps and `exclude-newer`; plain `openai` SDK; keys only in Credential Manager.

### Claude's Discretion
- Everything else (library choices, module layout, slice order within the stated build order).

### Deferred Ideas (OUT OF SCOPE)
- Other agents (OpenCode, Antigravity: AGNT2-01), worktree isolation (Phase 3), self-upgrade with rollback (CORE-07, Phase 3), Telegram/phone approvals (Phase 4), screen/PC control (Phase 5), speaker-mode echo cancellation (v2), a `snow` MCP server inside agent sessions (seed item 8, Phase 3).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGNT-01..03 | Start, instruct, stop Claude Code by voice | SDK `ClaudeSDKClient` actor per session; project registry; stop ladder |
| AGNT-04 | Speak agent question, send spoken answer | `can_use_tool` receives `AskUserQuestion`; answer format verified in SDK docs |
| AGNT-05 | Route permission through Snow's approval system | PreToolUse hook returns `ask`, `can_use_tool` waits on the durable approval |
| AGNT-09 | Generic adapter contract | `AgentAdapter` Protocol below |
| VOIC-07 | Only enrolled voice commands | `speaker_verdict` on `transcript.final`, trust window, FA/h protocol |
| SAFE-01/02/03 | Deterministic tiers, routine free, sensitive always asks | `snow.policy` classifier tables |
| SAFE-05 | Unanswered approval times out to deny | Hub-authoritative `expires_at`, one-way state machine |
| SAFE-06 | Stop everything | Hotkey thread + `cmd.stop.all` + voice phrase + job object ladder |
| SAFE-07 | Secret entered directly | Pause and hand off; never relay secrets through the model |
| SAFE-08 | Content is data | Origin tags, taint floors, text-only rendering |
| SAFE-11 | Append-only redacted audit log | Separate `audit.db`, triggers, hash chain, log-before-act |
| HUD-07 | Pending approvals prominent | Needs a UI-SPEC (`/gsd-ui-phase 2`) before planning HUD tasks |
| CORE-06 | Pinned running copy | Release snapshot under `%LOCALAPPDATA%\Snow\releases` |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Python 3.12, uv, hash-locked deps; `exclude-newer = "2026-10-08T00:00:00Z"` with per-package overrides only for exact `==` pins [VERIFIED: pyproject.toml `[tool.uv]` read this session].
- Provider independence: no hard dependency on Claude; Claude is one adapter behind a contract. Keys only in Credential Manager; secrets never in logs/events/HUD.
- Never `cd`; use `uv --directory`, `npm --prefix`, `git -C`.
- No hard-coded spoken phrases; the LLM writes wording. Approval text shown on the HUD is built by code from structured fields (not model prose).
- Security is mandatory: speaker verification, approval tiers, secret isolation. Ruff (`S` rules), pyright strict on `src/snow`, CI on windows-latest.
- Work through GSD commands; this file is research only.

## Summary

Drive Claude Code with the Python `claude-agent-sdk` directly (not ACP). The SDK is the only route that lets Snow gate EVERY tool call: a `PreToolUse` hook runs before permission rules and modes, and "a hook deny applies even in `bypassPermissions` mode" [CITED: code.claude.com/docs/en/agent-sdk/permissions]. The ACP adapter (`@agentclientprotocol/claude-agent-acp` 0.97.0) is itself built on this SDK, adds a Node layer, and surfaces only `session/request_permission` for calls that already reached a prompt, so auto-approved reads/edits would bypass Snow. Keep ACP as the second implementation of Snow's own contract for OpenCode/Antigravity later (v2).

The gate is a pure-Python library (`snow.policy`) imported by a NEW supervised `agent` worker. The hook classifies each call (free / announce / ask / always_ask / blocked), writes the audit row BEFORE returning, and returns `allow`, `deny`, or `ask`. `ask` makes Claude Code call `can_use_tool`, which waits on a durable approval object owned by the hub (plan-hash bound, hub-enforced expiry, first answer wins). The hub, not the agent worker, is the trust anchor: it must first be fixed so a role comes from a per-role token, never from the Hello message (seed item 1; confirmed live in code below).

The phase also has to make the existing process model safe for an untrusted child tree: allowlisted environment (the SDK merges the full inherited `os.environ`), a per-session Job Object, a stop ladder that does not hard-kill during an OAuth refresh, protected paths (Claude's `.credentials.json`, the audit DB, the release dir), and a pinned release copy so Claude editing Snow's repo never touches the running Snow.

**Primary recommendation:** slices in this order: (1) hub trust foundation, (2) policy + approvals + audit library, (3) kill switch + speaker gate, (4) Claude adapter + agent worker, (5) voice-to-agent flow + HUD cards, (6) pinned release (parallel with 3-5).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tier classification, plan hash, taint | `snow.policy` library (pure functions) | agent worker (calls it in hook) | Deterministic, testable without Claude; no LLM in the path |
| Approval state, expiry, audit writes | Hub (SQLite) | HUD/voice (resolve via commands) | Single trust anchor; survives agent worker crash |
| Claude session, hooks, `can_use_tool` | `agent` worker (new) | SDK `claude.exe` child | SDK needs same-task async context; isolates env and crashes |
| Kill switch (hotkey, `cmd.stop.all`) | Hub thread + agent worker job object | HUD button, voice phrase matcher | Must work with the LLM, asyncio loop and HUD hung |
| Speaker verification | Voice worker (owns audio) | Hub enforces verdict on commands | Audio never leaves the voice process |
| Intent routing (voice to agent command) | Brain worker (rules first, LLM fallback) | Policy library | LLM never gets authority; agent text never reaches the router |
| Approval/question UI | Electron renderer | Preload IPC to hub | HUD-07; text-only rendering |
| Pinned release | `snow release` CLI + Task Scheduler | Supervisor | Separate files from any repo |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| claude-agent-sdk | 0.2.164 (PyPI, uploaded 2026-10-06; newest before cutoff). 0.2.165 is 2026-10-08T18:18Z, 0.2.174 is 2026-10-24 | Drive `claude.exe`: streaming client, hooks, `can_use_tool`, interrupt, resume | Official; only route to gate every call [VERIFIED: PyPI JSON API, sdist read] |
| Existing: pydantic 2.14.1, websockets 17.2, psutil 7.2.2, pywin32 312, structlog 26.1.0, sherpa-onnx 1.13.8 (via 261026-wvr-02) | pinned | Contracts, hub, job objects, redaction, speaker model | Already in the lock |
| stdlib: `sqlite3`, `hashlib`, `ctypes`, `shlex`, `ntpath`, `difflib` | n/a | Audit DB, hashing, RegisterHotKey, command tokenizing | No new deps for the gate |

Dry resolve with the existing pins (`uv pip compile`, windows, `--exclude-newer 2026-10-08`) succeeded with: `mcp==2.3.0`, `mcp-types==2.3.0`, `anyio==4.15.1`, `jsonschema==4.26.0`, `starlette==1.7.0`, `sse-starlette==3.5.0`, `uvicorn==0.54.0`, `pyjwt==2.15.1`, `cryptography==50.0.2`, `python-multipart==0.0.32`, `httpx2==2.13.1` [VERIFIED: ran it this session]. No version conflict, but 11 new packages enter the lock: review in the legitimacy checkpoint.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SDK direct | ACP `@agentclientprotocol/claude-agent-acp` 0.97.0 (Apache-2.0, built on the same SDK, Node layer, v2 surface "experimental draft") | Gives one protocol for all agents, but loses the all-calls PreToolUse gate, `AskUserQuestion` fidelity and hooks `defer`. Use ACP only for OpenCode/Antigravity [CITED: github.com/agentclientprotocol/claude-agent-acp] |
| User's own `claude.exe` | SDK-bundled CLI (2.1.292 in 0.2.164) | Bundled is hermetic but older than 2.1.302, below the version where "your app starts in `default` mode" is documented; always set `permission_mode="default"` explicitly either way |
| `bashlex` etc. for shell parsing | `shlex` plus "unparseable means ask" | A parser may only raise risk; no new dependency |
| Claude `auto` permission mode | Snow's tiers | `auto` is a model classifier (not deterministic) and model-dependent; do not use for SAFE-02 |

**Installation (in slice 4, after approval):**
```bash
uv add "claude-agent-sdk==0.2.164"   # then: uv lock && uv sync --frozen
```
**Version verification:** `pip`/PyPI JSON run this session: 0.2.164 `2026-10-06T23:50:25`, 0.2.165 `2026-10-08T18:18:56`, latest 0.2.174 `2026-10-24T00:21:45`. Windows wheel is 129 MB (bundles `claude.exe`) [VERIFIED: PyPI JSON].

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| claude-agent-sdk | PyPI | many releases since 2025; latest upload 2026-10-24 | unknown to seam | github.com/anthropics/claude-agent-sdk-python | SUS (too-new, unknown-downloads) | Named in Anthropic's official docs. Pin `==0.2.164`; planner adds `checkpoint:human-verify` (D3) |
| agent-client-protocol | PyPI | 1.0.0rc3 on 2026-10-12 | unknown | agentclientprotocol.github.io/python-sdk | SUS (unknown-downloads) | NOT needed in Phase 2 (ACP deferred). Do not install |
| transitive: mcp, starlette, sse-starlette, uvicorn, pyjwt, cryptography, python-multipart, httpx2, jsonschema, anyio | PyPI | not individually run | n/a | n/a | not run | `[ASSUMED]` legitimacy; the planner should run `package-legitimacy check` on the resolved lock diff in the same checkpoint |

**Removed (SLOP):** none. **Suspicious (SUS):** claude-agent-sdk (checkpoint), agent-client-protocol (not installed). Registry commands run: `gsd-tools query package-legitimacy check --ecosystem pypi claude-agent-sdk agent-client-protocol`.

## Architecture Patterns

### System Architecture Diagram

```
 user voice -> [voice worker: wake, VAD, STT, TitaNet score, stop-phrase matcher]
                    |  transcript.final(+speaker_verdict, origin=user_voice)      "Snow, stop" --+
                    v                                                                              |
              [brain worker: rules -> LLM intent router (user text ONLY)]                         |
                    |  agent.command(start|send|answer|stop)  (typed enum)                        |
                    v                                                                              v
   HUD button -> [HUB: per-role tokens, role/event matrix, approvals (SQLite), audit.db, halted flag]
   RegisterHotKey thread ------------------^   |  ^
                                               |  | approval.requested / resolved, agent.* events
                                               v  |
                           [agent worker (role "agent", env allowlist, token popped from os.environ)]
                              AgentAdapter -> ClaudeCodeAdapter (one actor task per session)
                              PreToolUse hook -> snow.policy.classify() -> audit row -> allow|deny|ask
                              can_use_tool    -> ask: wait on hub approval (plan-hash re-check)
                                              -> AskUserQuestion: agent.question -> user answer
                                               |  stdio stream-json
                                               v
                           claude.exe (user's own; per-session Job Object) -> Bash/PowerShell/Edit/...
                                               ^
    stop ladder: gate halt -> SDK interrupt -> close stdin + 10 s grace -> TerminateJobObject
```

### Recommended Project Structure
```
src/snow/
  policy/        # pure library: tiers.py, paths.py, shellparse.py, taint.py, planhash.py, rules.toml loader
  agent/         # __main__.py (worker), contract.py (AgentAdapter, AgentEvent), claude_code.py, spawn.py (env, job, cli path)
  hub/           # + approvals.py, audit.py, stop.py (hotkey thread), tokens in server.py
  release/       # create/activate/prune (CLI: snow release ...)
config/          # + policy.toml (tier tables), projects.toml, hotkey in snow.toml
tests/policy/, tests/agent/, tests/hub/ (trust, approvals, audit)
tests/fakes/     # fake SDK client for adapter tests
```

### Pattern 1: The gate is the hook, not the callback
**What:** `PreToolUse` fires on every call before deny/ask/allow rules and modes. Return `allow` only for free/announce; `deny` for blocked or any internal error; `ask` for ask/always_ask, which routes to `can_use_tool`.
**Why:** `can_use_tool` never fires for calls approved earlier (allow rules, `acceptEdits`, `bypassPermissions`) [CITED: code.claude.com/docs/en/agent-sdk/user-input]. "A hook that returns `allow` doesn't skip the deny and ask rules" [CITED: .../permissions], so settings-file deny rules remain a second layer.
**Fail closed:** "An Agent SDK callback hook on `PreToolUse` that exceeds its timeout blocks the tool call" [CITED: code.claude.com/docs/en/hooks]. The SDK's `HookMatcher.timeout` defaults to 60 s [VERIFIED: SDK `types.py` HookMatcher]. Keep the hook fast (no human waiting inside it), wrap the body in `try/except` returning `deny`, and set `timeout` explicitly.
**Example (types verified from SDK 0.2.174/0.2.164 source, not Snow code):**
```python
# Source: claude_agent_sdk/types.py (HookMatcher, PermissionResultAllow/Deny, PreToolUseHookSpecificOutput)
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, PermissionResultAllow, PermissionResultDeny

async def pre_tool_use(input_data, tool_use_id, context):
    try:
        verdict = gate.decide(input_data["tool_name"], input_data["tool_input"], session)  # pure, audited
    except Exception:
        verdict = Verdict.deny("gate error")           # fail closed
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": verdict.decision,        # "allow" | "deny" | "ask"
        "permissionDecisionReason": verdict.reason,    # forwarded to can_use_tool as decision_reason
    }}

async def can_use_tool(tool_name, input_data, ctx):
    if tool_name == "AskUserQuestion":
        answers = await questions.collect(input_data["questions"])      # user's verified spoken/HUD answer
        return PermissionResultAllow(updated_input={"questions": input_data["questions"], "answers": answers})
    approval = await approvals.wait(plan_hash(tool_name, input_data, session), ctx.tool_use_id)
    if approval.approved and plan_hash(tool_name, input_data, session) == approval.plan_hash:
        return PermissionResultAllow(updated_input=input_data)          # run EXACTLY what was approved
    return PermissionResultDeny(message=approval.denial_text)

options = ClaudeAgentOptions(
    permission_mode="default", can_use_tool=can_use_tool, cli_path=str(user_claude_exe),
    system_prompt={"type": "preset", "preset": "claude_code"},          # None would send --system-prompt ""
    setting_sources=["project"], tools=[...explicit allowlist...], disallowed_tools=[...outward/scheduling tools...],
    hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use], timeout=5)]},
)
```
Note `system_prompt=None` makes the SDK pass `--system-prompt ""` [VERIFIED: `subprocess_cli.py` `_build_command`], so the coding agent would run with an empty prompt unless the `claude_code` preset is set.

### Pattern 2: Actor per session
`ClaudeSDKClient` keeps an anyio task group from `connect()` to `disconnect()` and its docstring requires all operations "within the same async context where it was connected" [VERIFIED: `client.py` class docstring]. One owner task per session: it connects, runs the receive loop, and executes queued commands (`send`, `interrupt`, `stop`) from an inbox. Do not `break` out of `receive_response()` [CITED: Python SDK reference].
**Interrupt desync:** `interrupt()` does not clear the buffer; drain `receive_response()` to the interrupted turn's `ResultMessage` before sending the next query [CITED: code.claude.com/docs/en/agent-sdk/python, "Buffer behavior after interrupt"]. Seed 261019 item 7 flags the same.

### Pattern 3: Generic adapter contract (fits Claude now, ACP agents later)
```python
class AgentAdapter(Protocol):
    id: str                                   # "claude_code"
    capabilities: frozenset[str]              # {"steer_inflight","native_interrupt","resume","questions","per_tool_gate"}
    async def start(self, spec: SessionSpec, host: AgentHost) -> SessionId: ...
    async def send(self, sid: SessionId, text: str) -> SendResult: ...      # "accepted"|"not_delivered"|"unknown" (never re-send unknown)
    async def interrupt(self, sid: SessionId) -> None: ...
    async def stop(self, sid: SessionId, *, grace_s: float) -> StopResult: ...
    def events(self, sid: SessionId) -> AsyncIterator[AgentEvent]: ...      # started, text, tool, question, permission, turn_done, ended, error
class AgentHost(Protocol):                    # injected; adapter knows nothing about HUD or voice
    async def permission(self, req: PermissionRequest) -> Decision: ...
    async def question(self, q: Question) -> Answer: ...
    def audit(self, record: AuditRecord) -> None: ...
```
`SessionSpec` carries project name (resolved from the registry), cwd, resume id, and tier ceiling; never a raw path from the LLM. An ACP agent maps `session/request_permission` to `host.permission` and can only `cancel + re-prompt` (capability flag `steer_inflight` absent; Snow says so aloud).

### Pattern 4: Approval object (durable, hub-owned)
Table `approvals(id, session_id, tool_use_id, tool, summary, plan_hash, tier, reason, status, created_ns, expires_ns, resolved_ns, resolved_by, evidence)`. Status moves one way: `pending -> approved | denied | expired | cancelled`; resolve with `UPDATE ... WHERE id=? AND status='pending' AND expires_ns>now` so the first answer wins and late/duplicate answers are rejected. Expiry is enforced by a hub timer; the agent worker also denies on hub disconnect. A denied-by-timeout item stays visible on the HUD as "expired, denied" (SC-3) and can be retried only by a NEW approval. `plan_hash = sha256(canonical_json({adapter, session, tool, normalized_input, realpath(cwd), resolved_target_paths, env_profile, rules_version}))`, recomputed in `can_use_tool` immediately before returning `allow` with `updated_input` set to the hashed input.

### Pattern 5: Audit log (separate, append-only, log-before-act)
Own file `%LOCALAPPDATA%\Snow\audit\audit.db` (not `snow.db`, whose 30-day retention purges speech text). Columns: `id, ts_ns, kind, actor, origin, session_id, approval_id, tier, tool, summary_redacted, input_sha256, decision, reason, prev_hash, hash`; `BEFORE UPDATE`/`BEFORE DELETE` triggers `RAISE(ABORT)`; `hash = sha256(prev_hash || canonical_row)`; `snow audit verify` walks the chain. Hub is the only writer. Gate rule: if the audit append fails, return `deny` (no action without a record). Redaction reuses the existing scrubber (by key name, key shape, exact revealed secret) from `snow/logging.py` (`_scrub` is private: expose a public `redact_text`) [VERIFIED: src/snow/logging.py read this session]. Honest limit: same-user processes could delete the file, so the path is a gate-protected path and the chain makes tampering detectable, not impossible.

### Anti-Patterns to Avoid
- **Waiting for the human inside the hook** (60 s timeout, and a timeout denies). Wait in `can_use_tool`, which "can stay pending indefinitely" [CITED: user-input].
- **`bypassPermissions`, `auto`, or `allowed_tools` for tools you want gated.** `allowed_tools` does not constrain `bypassPermissions` [CITED: permissions].
- **Letting the LLM see agent text in the intent router.** Agent text may only reach a no-tools reply writer.
- **Building approval text from model prose.** Build from tool name, sanitized command and classifier reasons; show control and bidi characters as visible escapes (OpenClaw zero-width spoofing, seed 261020).
- **Using `defer` in Phase 2.** It needs `-p` mode, stops the run, resumes via `--resume`, and is ignored when several tool calls arrive together [CITED: code.claude.com/docs/en/hooks]. A pending callback plus a persistent agent worker is enough; revisit for restart-resume (CORE-05, Phase 4).

## Deterministic Risk Tiers (SAFE-01/02/03)

Tier names are fixed by the event contract: `risk_tier: Literal["free", "announce", "ask", "always_ask"] = "free"` [VERIFIED: src/snow/contracts/events.py:33]. Add a fifth internal verdict `blocked` that never reaches the user (no approval can override).

| Tier | Meaning | Examples (deterministic rules) |
|------|---------|--------------------------------|
| free | runs silently, audited | `Read`, `Glob`, `Grep`, `LSP` inside the project root and not protected; `Edit/Write/NotebookEdit` inside the project root, not in `.git/`, not protected; read-only git (`status`, `diff`, `log`, `show`); allowlisted test/lint/typecheck (`pytest`, `ruff`, `pyright`, `uv run pytest`, `npm test`, `npm run lint|typecheck`) |
| announce | runs, HUD notice | `git add/commit` (local), `uv sync --frozen`, `mkdir`, `mv/cp` inside project, `npm run build` |
| ask | wait for approval (voice or HUD); may be remembered for the session only as an exact plan-hash | network (`WebFetch`, `WebSearch`, `curl`, `git clone`/`fetch`/`pull`), package add (`uv add`, `npm install <pkg>`, `pip install`), writes outside the project but inside the user profile temp, `git push` (non-force), `git checkout/switch/merge/rebase`, any MCP tool, `Agent` subagent, unknown tool name, unparseable command |
| always_ask | explicit approval every time, never remembered | irreversible deletion (`rm -r`, `Remove-Item -Recurse`, `del /s`, `rd /s`, `git clean -f*`, `git reset --hard`, `git push --force*`, `git branch -D`), anything touching credentials, security settings or payments (protected paths below, `reg add/delete`, `schtasks`, `netsh`, `Set-ExecutionPolicy`, `icacls`, `cmdkey`, `iex`/`-EncodedCommand`, piping a download into a shell, payment-domain URLs), writes outside the user profile, a project not in the registry |
| blocked | denied, cannot be approved | write/delete of `audit.db`, `%LOCALAPPDATA%\Snow\releases\**`, `run\`, Snow's Credential Manager entries; read of Claude's `%USERPROFILE%\.claude\.credentials.json` [CITED: code.claude.com/docs/en/authentication, Windows storage path]; edits to `config/policy.toml`/session settings that would weaken the gate; killing Snow processes |

Rules for the classifier (keep it small and test-driven):
1. **Raise-only parsing.** Tokenize with `shlex` (Bash) or a conservative lexer (PowerShell); split on `; | & && || newline`; ANY of `$( ` backtick, `%VAR%`, `$VAR`, `~`, here-strings, `-EncodedCommand`, `iex`, redirection to a path, or a parse error makes the segment `ask` at minimum. The tier of a command is the max over segments; a segment is `free` only if its verb is on the allowlist AND every path argument classifies free.
2. **Unknown tool names default to `ask`.** The built-in tool surface is large (`Bash`, `PowerShell`, `Monitor`, `Workflow`, `CronCreate`, `RemoteTrigger`, `Artifact`, `SendUserFile`, `PushNotification`, `SendFeedback`, `EnterWorktree`, ...) [CITED: code.claude.com/docs/en/tools-reference]. Shrink it with `tools=[explicit allowlist]` and `disallowed_tools=["RemoteTrigger","Artifact","SendFeedback","SendUserFile","PushNotification","ShareOnboardingGuide","CronCreate","Workflow"]` (outward sends and persistent schedules), so the classifier covers a small set.
3. **Path canonicalization.** `os.path.realpath` (resolves junctions and symlinks on Python 3.12), `win32api.GetLongPathName` for 8.3 names, `os.path.normcase`, strip `\\?\`, reject alternate data streams (`:` after the drive), trailing dots/spaces, UNC paths, device names; containment by `is_relative_to(realpath(project_root))`. Any path containing an unexpanded variable is unclassifiable and goes to `ask`.
4. **LLM raise-only seam.** `raise_tier(tool, summary) -> tier|None` with a hard 2 s timeout; result is `max(deterministic, llm)`; `data_class="private"` routing (SAFE-12) applies; default OFF (D9).
5. **Cap outward sends per task** (messages, pushes, uploads) with a counter in the approval store.

### Taint (SAFE-08) and origin tags
- Every content-bearing event gets `origin: user_voice | user_hud | agent | tool_result | file | web | screen | system`. Only `user_voice` with `speaker_verdict=verified` and `user_hud` can create an `agent.command` or resolve an approval. The hub rejects any other origin on those paths.
- Session `taint` becomes `external` when the agent has used `WebFetch/WebSearch`, any MCP tool, `git clone/fetch/pull` of a non-registry repo, or package installs. While `external`: any shell command not on the read-only allowlist is `ask`; writes outside the project are `always_ask`; network and `git push` are `always_ask`. Reading project files does not taint (a coding agent reads files constantly); instead a NEW project path needs one `always_ask` trust approval, bound to the path hash. [ASSUMED: this floor is a design recommendation, tune in D6.]
- Untrusted text handed to any Snow LLM is wrapped in delimiters with a per-call random id; the speech-reply writer has no tools. This is defence in depth, not the control.

## Kill Switch Outside the LLM (SAFE-06)

| Path | Mechanism | Notes |
|------|-----------|-------|
| Hotkey | Dedicated thread in the HUB process calling `RegisterHotKey(NULL, id, MOD_NOREPEAT plus modifiers, vk)` and a `GetMessage` loop; on `WM_HOTKEY` it sets the `halted` flag and posts to the asyncio loop | `hWnd=NULL` posts `WM_HOTKEY` to the calling thread's queue; it fails if the combo is taken, so log the failure and show it in health [CITED: learn.microsoft.com RegisterHotKey]. Do not use F12. Electron `globalShortcut.register` "will silently fail" when the accelerator is taken and needs the `ready` event [CITED: electronjs.org/docs/latest/api/global-shortcut]; keep it only as an optional extra |
| HUD button | `cmd.stop.all` over the WebSocket, role `hud` only | Add to `COMMAND_ROLES` |
| Voice | Local phrase matcher in the voice worker on Moonshine partials and finals ("stop", "Snow stop", "stop everything"); emits `cmd.stop.all` (role `voice`); never sent to the LLM | Works while awake or after "Hey Snow" (D4). Not speaker-gated (fail-safe) |
| Supervisor signal | Hub sets `halted`; supervisor can terminate the `agent` worker, whose Job Object kills the whole Claude tree | Job Object has `KILL_ON_JOB_CLOSE` (existing pattern) |

**Stop ladder** (a stop must not lose the Claude login): (1) gate halts instantly: `halted=True`, every pending approval becomes `cancelled`, the hook returns `deny` for every new call; (2) SDK `interrupt()`; (3) close stdin and wait up to 10 s (the SDK's own `close()` waits 5 s then terminates [VERIFIED: `subprocess_cli.py` close]; on Windows anyio maps terminate to a hard TerminateProcess); (4) `TerminateJobObject` on the session's Job Object. Rationale for the grace: "Claude Code killed during an OAuth refresh loses the new refresh token, and the user's login with it" [CITED: seeds/codync-openmausbot-gap-study.md line 67, a third-party study, MEDIUM]. Set a `stop_requested` flag synchronously before the first await so an intentional stop is never reported as a crash.

## Spawn Hygiene on Windows (seed item 4)

- **Binary:** the user's native `claude.exe`. The SDK's `_find_cli` prefers its bundled CLI, then `shutil.which("claude")`, then `~/.local/bin/claude.exe`; it refuses `.bat/.cmd` shims ("Refusing to execute batch script") [VERIFIED: `subprocess_cli.py` `_find_cli`, `_reject_windows_batch_cli`]. Pass `cli_path` explicitly. Present on this machine: `~/.local/bin/claude.exe`, `2.1.311 (Claude Code)` [VERIFIED: ran `claude --version`].
- **Environment:** the SDK builds `{**os.environ minus CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, **options.env}` [VERIFIED: `connect()`], so `options.env` can only add, not remove. Scrub in the `agent` worker itself: it is launched with an allowlisted environment (`PATH`, `SystemRoot`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP`, `COMSPEC`, `PATHEXT`, `HOMEDRIVE/HOMEPATH`, `ProgramFiles*`), and it `os.environ.pop`s `SNOW_TOKEN` after reading it. Existing `scrub_env` is a blocklist by name fragment (`_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")`) [VERIFIED: src/snow/hub/supervisor.py:53] and is not enough for a child tree. Never pass `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_*` or `CLAUDE_CODE_OAUTH_TOKEN`: they outrank the subscription login ("In non-interactive mode (`-p`), the key is always used when present") [CITED: code.claude.com/docs/en/authentication, Authentication precedence]. `USERPROFILE` must stay or the login is not found.
- **Job Object:** the supervisor puts workers in a hub-wide kill-on-close job [VERIFIED: supervisor.py `_spawn` calls `assign`]. Claude's children inherit it, so a hub death kills them. For "stop this agent only", create a nested job per session and assign `claude.exe` right after `connect()`; find the pid by diffing `psutil.Process().children()` before and after `connect()` (the SDK exposes no pid). `assign()` documents the race for grandchildren started earlier [VERIFIED: src/snow/hub/jobobject.py `assign` docstring]; `claude.exe` spawns no tool children in its first moments, accepted.
- **Settings:** `setting_sources=["project"]` (so `CLAUDE.md` loads; `[]` would drop it) and explicit `permission_mode="default"`. Prompts go over stdin (streaming), not argv.
- **Second layer:** `disallowed_tools` deny rules in the options, e.g. `Read(//c/Users/*/.claude/.credentials.json)` style patterns, because a deny rule applies "even when a hook returned `allow`" [CITED: permissions]. Exact pattern syntax needs a spike (`//path` anchors absolute paths).

## Speaker Verification for Commands (VOIC-07)

Reuse the verifier from quick 261026-wvr plan 02: `SpeakerVerifier` (sherpa-onnx 1.13.8, NeMo TitaNet-small, 192-dim, ~39 ms per 1 s of audio on one thread, voiceprint DPAPI-wrapped under `%LOCALAPPDATA%\Snow`) [CITED: 261026-wvr-RESEARCH.md; plan 02 not executed yet, D10].
- **Where:** the voice worker scores the whole finished turn audio and attaches `speaker_score` and `speaker_verdict: verified | unverified | too_short | not_enrolled` to `transcript.final` (contract change, regenerate JSON Schema and HUD types). The hub drops `unverified` turns before the brain sees them and publishes `speaker.ignored` for the HUD ("ignored: not your voice") (VOIC-07 display).
- **Trust window:** verify the wake clip, then trust the follow-on turn only until silence or turn end. Every command-bearing turn is still scored; below the speech-length floor it falls back to the window for `free`/`announce` actions only.
- **Measured short-utterance behaviour (261026-wvr, one phone-mic speaker, clean):** genuine whole clip 0.71-0.91; first 0.5 s mean 0.55, min 0.07; first 0.3 s mean 0.32, min -0.03; Snow's own voice 0.5 s crops max 0.07; six real other speakers max 0.25 (crop length not stated); starting threshold 0.35. Hence D5.
- **False accepts per hour: how to measure (not yet measured on real audio):**
  1. Corpus of at least 10 h of speech that is NOT the user: licensed public speech sets plus 2+ h of the user's own TV/YouTube/podcast audio played at normal volume through the laptop speakers into the real mic path (same AEC). Include both sexes and music-under-speech.
  2. Cut with the same VAD into utterance-length windows (0.6-3 s) and score each against the enrolled centroid with the production code path.
  3. FA/h = accepted windows / hours of speech. With zero false accepts in T hours, the 95% upper bound is about 3/T per hour (rule of three), so 10 h proves "at most 0.3 per hour of speech" and 30 h proves 0.1. Report separately for windows under 1 s and over 1 s.
  4. Also report FRR on held-out genuine windows of the same lengths. Set the threshold from the laptop-mic data, not the phone clips.
  5. Out of reach for embeddings: replay of the user's recorded voice (accepted risk, documented).
  Mark the target as an explicit acceptance number in the plan (suggested: 0 false accepts in 10 h of TV speech; FRR under 10% at 1.5 s).

## Pinned Running Copy (CORE-06)

Facts today: `repo_root()` is derived from `__file__` (`parents[3]`), so a copied tree resolves its own root [VERIFIED: src/snow/config/settings.py read]; autostart registers `repo_root() / ".venv" / "Scripts" / "pythonw.exe"` [VERIFIED: src/snow/hub/autostart.py:25], i.e. the dev checkout is what runs at logon; workers launch with `cwd=repo_root()` [VERIFIED: supervisor.py:122]; models are read from `repo_root()/"models"` in `stt_local.py:47`, `tone.py:40`, `kokoro.py:61`, `wake.py:53` and `voice.toml:11` (`model = "models/wakeword/hey_snow.onnx"`) [VERIFIED: grep this session].

Recommended design:
- `snow release create`: `git archive <sha>` into `%LOCALAPPDATA%\Snow\releases\<sha>\` (no `.git`), `uv sync --frozen --no-editable` there (flag exists in `uv sync --help`), `npm --prefix hud ci` and `npm --prefix hud run build`, write `release.json` (sha, versions, lock hash, timestamp).
- `snow release activate <id>`: atomically re-point a directory junction `releases\current` (`mklink /J`, no elevation) and re-register the Task Scheduler action to `releases\current\.venv\Scripts\pythonw.exe -m snow.hub --autostart`. Activation is a user-approved command in Phase 2; automatic switching with health-check rollback is CORE-07 (Phase 3).
- Move user-owned state out of any release: config to `%LOCALAPPDATA%\Snow\config` via the existing `SNOW_CONFIG_DIR` override, models to `%LOCALAPPDATA%\Snow\models` (add `models_dir()` to `settings.py`; fix the five call sites). Keep the last 2 releases, prune older.
- Gate rule: `releases\**`, `run\`, `audit\` are `blocked` for the agent. Even if Claude edits the dev repo (its job), the running Snow is a different directory. Rehearsal task for sign-off: Claude, driven by voice, changes a file in the dev repo; the running copy's file hashes are unchanged.
- Disk: `node_modules` per release is large; accepted for Phase 2, Phase 7 replaces this with the installer.

## Per-Role Hub Tokens (seed item 1, FIRST task)

Live weakness, re-confirmed: one token is written to `hub.json` (`json.dumps({"port": self._port, "token": self._token, "pid": os.getpid()})`) [VERIFIED: src/snow/hub/server.py:119-124]; the role comes from the client's Hello (`return _Client(ws=ws, role=hello.role)`) [VERIFIED: server.py:186]; `Role = Literal["voice", "brain", "hud", "dev"]` [VERIFIED: src/snow/contracts/wire.py:19]; `Worker = Literal["voice", "brain", "hud"]` [VERIFIED: src/snow/contracts/events.py:44]; events only need `source == role` (server.py:201-203). Command rights today: `"cmd.mute.set": frozenset({"hud"})`, `"cmd.dev.say": frozenset({"dev"})`, `"cmd.dev.kill": frozenset({"dev"})` [VERIFIED: wire.py:75-81].

Required changes:
1. Hub makes one token per role (`secrets.token_hex(32)`), authenticates by token, derives the role from it, and rejects a Hello whose `role` differs (close 4401).
2. `hub.json` carries `port` and `pid` only. The supervisor passes each worker ONLY its own `SNOW_TOKEN` (the HUD gets the `hud` token via env, as `hubinfo.ts` already accepts `SNOW_HUB_URL`/`SNOW_TOKEN` from env). `dev` token exists only when config `[hub] dev_access = true` (dev checkout), written to a separate file; never in the pinned production copy.
3. Add `agent` to `Role` and `Worker`, to supervisor `_LABELS`/`_WATCHED`, and to `snow.toml` `[workers.agent]`.
4. Add `EVENT_ROLES` (which event types each role may publish) beside `COMMAND_ROLES`; today any role may publish any event type with its own `source`.
5. New commands: `cmd.stop.all` (hud, voice), `cmd.approval.resolve` (hud, and voice only with verified-speaker evidence), `cmd.agent.control` (brain). The `agent` and `dev` roles can resolve nothing.
6. The `agent` worker `os.environ.pop`s its token after the first connect, so `claude.exe` never inherits it; the gate marks `hub.json`, `run\`, and the HUD data dir as protected paths.
Tests: a token for role A cannot claim role B; the `agent` role cannot publish `transcript.final`/`approval.resolved` or send `cmd.approval.resolve`; `hub.json` contains no token.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Claude process protocol (stream-json, control requests) | A stdio JSON client | `claude-agent-sdk` | Control protocol, resume, hooks, version check |
| Process-tree kill | Walk children and `taskkill` | Windows Job Object (`win32job`, already wrapped in `hub/jobobject.py`) | Catches grandchildren, one call |
| Speaker embeddings | Own model code | sherpa-onnx `SpeakerEmbeddingExtractor` + TitaNet-small | Already chosen and measured |
| Voiceprint at rest | Own crypto | `win32crypt.CryptProtectData` (DPAPI) | per user |
| Secret redaction | New regexes | existing `snow.logging` scrubber (key name, key shape, exact revealed secrets) | One redaction truth |
| Hash chain | A blockchain-style library | `hashlib.sha256` + SQLite triggers | 20 lines |
| Text similarity / fuzzy project names | A matcher | stdlib `difflib` | Already used in barge-in |
| Global hotkey | A keyboard-hook library | `ctypes` `RegisterHotKey` | No `keyboard`-style low-level hook (AV flags), no dependency |

**Key insight:** the hard part is policy and process hygiene, not libraries. Everything risky should be a small, pure, table-tested module with no LLM and no network.

## Common Pitfalls

1. **Hook timeout/exception semantics.** Callback `PreToolUse` timeouts deny, but how the CLI treats an exception response from a hook callback is not documented (`query.py` sends an error control response) [VERIFIED: query.py `_handle_control_request`]. Catch everything inside the hook and return an explicit `deny`. Test with a fault-injecting fake.
2. **`allow` from a hook is not final.** Deny/ask rules in settings still apply; recognized critical-path `rm` stays unapprovable even with hook `allow` [CITED: permissions]. Do not rely on `allow` to "unlock" anything.
3. **Hook `ask` versus a project allow rule.** Expect the prompt to still reach `can_use_tool` (hook precedence is deny > defer > ask > allow [CITED: hooks]). [ASSUMED] against a project `settings.local.json` containing `Bash(*)` allow rules: verify in the live smoke test.
4. **SDK desync after `interrupt()`:** drain to the stale `ResultMessage` before the next `query()`.
5. **Default mode drift.** "With Claude Code v2.1.302 or later, your app starts in `default` mode" [CITED: permissions]. Always pass `permission_mode="default"`.
6. **Project `.claude/` in the Snow repo contains hooks and a `settings.local.json`** (untracked, per git status). With `setting_sources=["project"]` those run inside Snow-driven sessions. Review them before the first dogfooding run.
7. **Windows path evasion:** 8.3 short names, junctions, `\\?\`, UNC, ADS, case, trailing dots, `%VAR%`. Test with real junctions in `tmp_path`.
8. **Voice approvals under 0.5 s are unverifiable** (D5). Never accept a bare "yes".
9. **A TV or the agent's own spoken question echoing into the mic.** The verifier plus the existing self-echo filter handle most; never let a reply to an approval count unless it started AFTER the question was spoken (seed item 8).
10. **Stale approvals:** a late "yes" after expiry or after kill must not revive anything (conditional UPDATE).
11. **Secret entry (SAFE-07):** do not relay secrets to the model. On a secret request (question/permission text matching `password|passphrase|token|api key|secret|2fa|otp|pin|card`), deny with a message telling Claude the user will enter it directly, show a HUD banner, and discard voice transcripts until the user dismisses it. The secret never touches Snow, the LLM or the audit log. [ASSUMED: detection is heuristic; the structural guarantee is "Snow never accepts a secret value".]
12. **mcp v2 breaking renames** if any code imports `mcp` directly (`FastMCP` to `MCPServer`); Phase 2 does not import it, the SDK does.
13. **Large wheel and CLI drift:** the Windows wheel is 129 MB and the user's `claude.exe` auto-updates; log `claude --version` in every session audit row and keep the live smoke test.

## Code Examples

### Rule inputs verified in this repo (verbatim)
```
events.py:33   risk_tier: Literal["free", "announce", "ask", "always_ask"] = "free"
wire.py:19     Role = Literal["voice", "brain", "hud", "dev"]
events.py:44   Worker = Literal["voice", "brain", "hud"]
supervisor.py:53  _SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
```

### Voice stop-phrase matcher (shape only)
Deterministic, in the voice worker, before any brain call: normalized final or partial text fully matching `^(hey )?snow[, ]*(stop|halt|cancel)( everything)?$` or `^stop( everything)?$` while an agent session is active. Ambiguous speech never cancels (seed item 7).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `--permission-prompt-tool` MCP tool for approvals | `can_use_tool` callback plus `PreToolUse` hook in the SDK | SDK 0.1.x to 0.2.x | Use callbacks; `permission_prompt_tool_name` and `can_use_tool` cannot be combined (SDK raises `ValueError`) |
| Claude Code SDK name | Claude Agent SDK; `claude-agent-sdk` | 2025 | Use the new package |
| Plan-hash approvals with `defer` | `defer` only for process-exit waits (`-p`) | current | Not needed in Phase 2 |
| ACP for Claude | ACP adapter still wraps this SDK | current | SDK direct for Claude |
| `.cmd` npm shim on Windows | native `claude.exe`; SDK refuses shims | 2026 | Use `~/.local/bin/claude.exe` |

**Deprecated/outdated (STACK.md in CLAUDE.md):** `claude-agent-sdk` 0.2.165 is no longer "current" (0.2.174); no needed feature requires it. `@zed-industries/claude-code-acp` is superseded (last 0.16.2, 2026-03-26).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SDK 0.2.164 talks correctly to `claude.exe` 2.1.311 | Standard Stack | Version skew bug; mitigated by live smoke test and the SDK's version check |
| A2 | The SDK-bundled and user-installed `claude.exe` share `%USERPROFILE%\.claude\.credentials.json` | D2 | Fallback binary would not be logged in |
| A3 | A hook `ask` still reaches `can_use_tool` when settings contain allow rules | Pitfalls 3 | Approvals bypassed; spike before slice 4 sign-off |
| A4 | A hook callback that raises is treated as a block (not fail-open) by the CLI | Pitfall 1 | Hook errors would run tools; explicit `deny` in a try/except removes the dependence |
| A5 | The taint floors in the Taint section are acceptable friction | Taint | Too many prompts or too few; D6 |
| A6 | Secret-request detection by keyword is good enough as a heuristic | Pitfall 11 | Missed secret prompt; the structural rule (never accept a secret value) still holds |
| A7 | `PowerShell` tool is available to Claude on this Windows install | Tiers | Classifier must cover it either way (it is in the documented tool list) |
| A8 | Nested Job Object assignment right after `connect()` catches all later tool children | Spawn Hygiene | A fast grandchild escapes the per-session job (still dies with the hub-wide job) |
| A9 | Hub-owned `RegisterHotKey` works while the HUD is crashed and not while the session is locked | Kill switch | Locked-screen stop relies on voice/other paths |
| A10 | Package legitimacy of the 11 transitive packages | Audit | Supply-chain; run the seam on the lock diff |
| A11 | Windows Job Object kill of `claude.exe` mid-refresh could lose the login (third-party claim) | Stop ladder | Only affects how long the grace should be |

## Open Questions

1. **Does the Python `ClaudeSDKClient` honour a hook `defer`?** Docs say `defer` needs `-p`; the SDK streams. Not needed now. Revisit for CORE-05.
2. **Exact deny-rule pattern for the credentials file** (`Read(//c/Users/...)` anchoring). Spike in slice 4 against a scratch dir.
3. **How should "tell it ..." be addressed during a session?** (routing): recommended rule-first grammar ("tell Claude ...", "Claude, ...") with an LLM classifier fallback that only outputs the typed command enum; confirm wording in discussion.
4. **UI work:** HUD cards (approval, question, agent state, stop button) need `/gsd-ui-phase 2` before planning those tasks (config `ui_phase: true`, roadmap `UI hint: yes`).
5. **Speaker enrollment on the laptop mic** is a human action (30 s recording); schedule it with the user.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 + uv | everything | yes | uv 0.11.8 (3.12 venv) | - |
| Node | HUD build for releases | yes | v25.6.0 | - |
| Git for Windows (Git Bash) | Claude's `Bash` tool, `git archive` | yes | git 2.52.0; `C:\Program Files\Git\bin\bash.exe` | - |
| `claude.exe` (native) | adapter | yes | 2.1.311 at `~/.local/bin/claude.exe` | SDK-bundled CLI |
| Claude login state | live smoke test | not probed (no credentials read) | - | user runs one login if needed |
| RTX/GPU, Tailscale | not needed in Phase 2 | - | - | - |

**Missing with no fallback:** none found. **Human action needed:** voiceprint enrollment; one live Claude smoke run.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), markers `hardware`, `gpu`, `slow`, `network` [VERIFIED: pyproject.toml] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest -q tests/policy tests/hub tests/agent` |
| Full suite command | `uv run pytest -q` then `uv run ruff check src tests`, `uv run pyright`, `npm --prefix hud run lint`, `npm --prefix hud test` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SAFE-01/02/03 | table of 200+ commands/paths to tier; appending a dangerous segment never lowers a tier (monotonic property over generated pairs) | unit | `uv run pytest tests/policy -x` | Wave 0 |
| SAFE-05 | late/duplicate/expired answers rejected; timeout to deny; disconnect to deny | unit | `uv run pytest tests/hub/test_approvals.py` | Wave 0 |
| SAFE-11 | UPDATE/DELETE aborted; chain verifies; tampered row detected; append failure denies | unit | `uv run pytest tests/hub/test_audit.py` | Wave 0 |
| SAFE-06 | stop ladder order with a fake client that ignores interrupt; hotkey thread posts event (fake `user32`) | unit | `uv run pytest tests/agent/test_stop.py tests/hub/test_stop.py` | Wave 0 |
| SAFE-08 | agent/web/file origin cannot create `agent.command` or resolve approval; taint floors | unit | `uv run pytest tests/policy/test_taint.py tests/hub/test_origin.py` | Wave 0 |
| AGNT-04/05 | `can_use_tool` for `AskUserQuestion` and `ask` verdict through a fake SDK client | unit | `uv run pytest tests/agent/test_claude_adapter.py` | Wave 0 |
| AGNT-09 | one contract test suite run against fake and Claude adapters | unit | `uv run pytest tests/agent/test_contract.py` | Wave 0 |
| role tokens | role from token; `hub.json` has no token; `agent` role limits | unit/integration | `uv run pytest tests/hub/test_ws_security.py tests/hub/test_roles.py` | partly exists |
| VOIC-07 | ignored events and HUD row; FA/h harness runs on fixtures | unit + hardware | `uv run pytest tests/voice/test_speaker_gate.py`; FA/h as `-m hardware` | Wave 0 |
| CORE-06 | release create/activate on a temp dir; running copy hashes unchanged after dev edit | integration | `uv run pytest tests/release` | Wave 0 |
| live Claude | start, steer, question, permission, stop on a scratch dir | manual/`network` | `uv run pytest -m "network and slow" tests/agent/test_live.py` (human-run) | Wave 0 |

### Sampling Rate
- **Per task commit:** the quick run command.
- **Per wave merge:** full suite plus ruff, pyright, HUD lint/tests.
- **Phase gate:** full suite green, FA/h report attached, live smoke test log, dogfooding rehearsal (CORE-06) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/policy/`, `tests/agent/`, `tests/release/`, `tests/fakes/fake_sdk.py` (fake client with scripted misbehaviours: ignores interrupt, duplicate permission ids, dies mid-turn, slow connect, hook raises)
- [ ] `uv add claude-agent-sdk==0.2.164` after the D3 checkpoint
- [ ] a `live_agent` marker or reuse `network`+`slow`

## Security Domain

### Applicable ASVS Categories (config: `security_enforcement` true, ASVS level 1)
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | per-role hub tokens (`hmac.compare_digest`), speaker verification, voiceprint DPAPI |
| V3 Session Management | yes | approval ids, expiry, one-way state machine |
| V4 Access Control | yes | `COMMAND_ROLES` + new `EVENT_ROLES`, protected/blocked paths |
| V5 Input Validation | yes | pydantic `extra="forbid"` on every message; command/path canonicalization |
| V6 Cryptography | yes | DPAPI, `hashlib`/`secrets` only, no hand-rolled crypto |
| V7 Logging | yes | separate append-only redacted audit; no speech text in logs |
| V10 Supply chain | yes | `==` pins, hash-locked `uv.lock`, legitimacy checkpoint |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection from files/web/tool output | Tampering/EoP | origin tags, taint floors, tools allowlist, text-only rendering, no tools on the speech writer |
| Agent child reads hub token or `hub.json` | EoP/Info | per-role tokens, env allowlist, token popped, protected paths |
| Token holder claims another role | Spoofing | role from token (slice 1) |
| Approval spoofing (zero-width characters, model-written summary) | Spoofing | code-built summary, visible escapes, verbatim command in monospace |
| Plan changed after approval (TOCTOU) | Tampering | plan hash recomputed, `updated_input` = hashed input |
| Subscription flips to pay-as-you-go via inherited key | Info/Repudiation | env allowlist; strip `ANTHROPIC_*` |
| Credentials file read by the agent | Info disclosure | `blocked` path + deny rule |
| Audit tampering | Repudiation | triggers, hash chain, protected path, log-before-act |
| TV/other voice commands | Spoofing | speaker verdict, ignored display; replay of the user's voice is an accepted risk |
| Hung LLM blocks stop | DoS | stop path never touches the LLM or the HUD event loop |
| Orphaned Claude tree after crash | DoS | Job Objects (kill on close) |

## Suggested Build Order (plan slices)

Roadmap order is kept: trust and gate first, adapter after. Estimates are relative sizes.

1. **Slice 1, Hub trust foundation (M).** Per-role tokens, `hub.json` without tokens, `EVENT_ROLES`, `agent` role/worker slot, `cmd.stop.all`/`cmd.approval.resolve`/`cmd.agent.control` shells, origin field, new event types (`agent.*`, `approval.*`, `policy.*`, `speaker.*`, `kill.*`), JSON Schema + HUD types regenerated, tests. Seed items 1 and the `agent` worker supervision.
2. **Slice 2, Policy, approvals, audit (L).** `snow.policy` (tiers, paths, shell parse, taint, plan hash, `raise_tier` seam), approvals store and timers in the hub, `audit.db` with chain and `snow audit verify`, redaction helper made public. All pure and table-tested. No Claude yet.
3. **Slice 3, Kill switch and speaker gate (M).** Hotkey thread, `halted` state, voice stop-phrase matcher, HUD stop command, speaker verdict on `transcript.final`, ignored display event, trust window and spoken-approval rules, FA/h harness. Depends on 261026-wvr-02 (D10).
4. **Slice 4, Adapter contract and Claude Code adapter (L).** `AgentAdapter` protocol, fake SDK client, actor-per-session `ClaudeCodeAdapter`, hook + `can_use_tool` wiring to the gate, `AskUserQuestion` flow, spawn hygiene (cli path, env allowlist, Job Object), stop ladder, three-way `SendResult`, session-id persistence, human-verify checkpoint for the SDK package, one human-run live smoke test (assumptions A1-A4).
5. **Slice 5, Voice-to-agent flow and HUD (L, UI).** Project registry, rule-first intent router with typed commands, brain/agent bridge (speak questions, accept spoken answers, secret hand-off), HUD approval card, question card, agent state, stop button (needs UI-SPEC first).
6. **Slice 6, Pinned release (M), parallel with 3-5.** `snow release create/activate/prune`, `models_dir()`/config relocation, autostart re-pointing, gate protected paths, the dogfooding rehearsal that proves the running copy is untouched.

## Sources

### Primary (HIGH confidence)
- Read this session: `src/snow/hub/server.py`, `hub/supervisor.py`, `hub/__main__.py`, `hub/jobobject.py`, `hub/autostart.py`, `contracts/wire.py`, `contracts/events.py` (envelope), `brain/worker.py`, `config/settings.py`, `logging.py`, `config/snow.toml`, `pyproject.toml`, `.planning/{ROADMAP,REQUIREMENTS,STATE}.md`, both seeds and both gap-study excerpts, `261026-wvr-RESEARCH.md` and plan 01 summary.
- claude-agent-sdk 0.2.164, 0.2.165, 0.2.174 sdists read (`subprocess_cli.py`, `query.py`, `client.py`, `types.py`); PyPI JSON API (versions, dates, wheel sizes).
- https://code.claude.com/docs/en/agent-sdk/permissions , /agent-sdk/user-input , /agent-sdk/python , /agent-sdk/overview , /authentication , /hooks (PreToolUse, defer, timeouts) , /tools-reference
- https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan (2026-10-07 update)
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey ; https://www.electronjs.org/docs/latest/api/global-shortcut
- `uv pip compile` dry resolve and `package-legitimacy check`, run this session.

### Secondary (MEDIUM confidence)
- https://github.com/agentclientprotocol/claude-agent-acp (README); npm registry for 0.97.0.
- seeds/codync-openmausbot-gap-study.md (third-party studies of other projects: stop ladder, spawn hygiene); WebSearch on SDK interrupt buffer issue (claudeissues.com #20648).

### Tertiary (LOW confidence)
- Anything tagged [ASSUMED] in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH for the SDK choice and pin (read the source); MEDIUM for the client/CLI skew (A1).
- Architecture: MEDIUM-HIGH; the hook-as-gate design follows the documented evaluation order, with A3/A4 to prove live.
- Pitfalls: MEDIUM-HIGH; Windows path and taint rules are design recommendations.
- Speaker FA/h: LOW-MEDIUM; no real-audio numbers exist yet, only the protocol.

**Research date:** 2026-10-27
**Valid until:** 2026-11-10 (the SDK ships roughly every 1-2 days; re-check the pin and CLI version at planning time)
