---
id: SEED-261020-s0w
status: dormant
planted: 2026-10-20
planted_during: Phase 01 (Always-On Voice Loop), plans 01-30 and 01-10 at user checkpoints
trigger_when: when planning Phase 2 (the hub token item is its FIRST task); again when planning Phases 3 and 4
scope: medium
---

# SEED-261020-s0w: Agent control and security ideas from OpenClaw, Codync and OpenMausBot

Three projects were studied:

| Project | Repo | Licence |
|---------|------|---------|
| OpenClaw | github.com/openclaw/openclaw | MIT |
| Codync | github.com/leepokai/Codync | Apache-2.0 |
| OpenMausBot | github.com/milind-soni/OpenMausBot | Apache-2.0; `enterprise/` is source-available and was not studied |

Only ideas were taken; no code was copied. The full studies are [openclaw-gap-study.md](./openclaw-gap-study.md) and [codync-openmausbot-gap-study.md](./codync-openmausbot-gap-study.md). This seed adds to [SEED-261019-mnj](./SEED-261019-mnj-fullstack-agent-gap-study-ideas.md).

## Why This Matters

Both studies found the same live weakness in Snow's hub (confirmed in code, 2026-10-20). One shared token is written to `hub.json` (`src/snow/hub/server.py:119-124`). The supervisor gives that token to every worker as `SNOW_TOKEN` (`supervisor.py:99`). Each client then declares its own role in Hello (`server.py:186`).

So today any token holder can claim `dev` and inject a fake transcript. Once Phase 2 adds approvals, a token holder could claim `hud` and approve its own requests; a Claude Code child that inherits the environment counts as a token holder. OpenClaw shipped the same bug and fixed it under advisory GHSA-rqpp-rjj8-7wv8.

## When to Surface

**Trigger:** when planning Phase 2. Item 1 is a precondition for any approval feature. Surface again for Phases 3 and 4.

## Items

### Phase 2

1. **Per-role tokens (first task).** The role is taken from the token, never from Hello. Approvals are accepted only from the HUD's private channel, voice and phone. Strip `SNOW_*` and provider keys from agent children.
2. **Approvals bound to the exact plan.** Hash the command, folder and environment, and re-check the hash right before it runs. Shell, interpreter and wrapper calls are high-risk by default. Parsing may only raise the risk, never lower it; a command that cannot be parsed means "ask". Pick a permission option by its kind, never its position. Deny late or duplicate requests. Keep a short list of actions no approval can override, and cap outward sends per task.
3. **Origin tags and taint.** Code sets an `origin` field on every content event. A turn that has seen agent, web or screen text is tainted, which raises the risk of its tool calls. Untrusted text is wrapped in markers with random ids.
4. **Clean agent spawning on Windows.**
   - Build the environment from an allowlist; an inherited `ANTHROPIC_API_KEY` flips a subscription login to pay-as-you-go.
   - Use project-only Claude settings and keep the prompt off argv.
   - Launch the real `.exe`, not the npm `.cmd` shim.
   - Give each agent a nested Job Object.
5. **Stop in steps.** Halt at the safety gate first. Then send the agent's own interrupt, close stdin and wait 10 s; force-kill only after that. A hard kill during a token refresh can lose the Claude login.
6. **Three-way steer result.** A steer comes back as accepted, not delivered, or unknown; never re-send an unknown one. ACP agents can only be cancelled and re-prompted, and Snow says so aloud.
7. **Voice run control.** Rules sort speech during a run into cancel, steer, status or follow-up before the LLM sees it; ambiguous speech never cancels. Announce a redirect only after the agent acknowledges it.
8. **A `snow` MCP server injected into agent sessions.** Tools: `notify_user`, `ask_user`, `show_on_hud`, `report_progress`, all through the gate.
9. **Crash-loop breaker and safe mode**, plus failure notices that work when the LLM is down.
10. **Fake agents and scenario tests**, and a guard that stops an agent making no progress.

### Phase 3

11. **Safe worktree discard.** Save a snapshot ref kept 30 days first, and remove a worktree only if nothing is lost.
12. **Self-upgrade dry boot.** Boot the new build against copies of the DB and config first; roll back automatically only when the schema is unchanged.
13. **Per-turn undo** inside the worktree.

### Phase 4

14. **Honest restart.** Claim the work before calling the model. Allow 3 charged retries, then wait for the user. Resume with read-only tools when an outcome is unknown. Never rerun a turn that pushed, sent or paid. Always name the approvals that timed out.
15. **Reliable Telegram.**
    - Store each update before acknowledging it; drop duplicates and stale updates after a restart.
    - One poller per bot token, with a stall watchdog.
    - Approval buttons carry versioned pointers, the user id is re-checked on every tap, and the first answer wins.
    - The gateway is default-deny with pairing.
16. **Tailscale identity.** Trust the identity header only after a `whois` cross-check, on a port that only Serve reaches.
17. **Presence detection** ignores Snow's own synthetic input (before Phase 5).
18. **Keep the laptop awake** during hand-off (`SetThreadExecutionState`). Scheduled routines are not in any requirement yet.
19. **Switch agents at usage limits**, without rotating accounts.

## Incidents to avoid (OpenClaw)

- **CVE-2026-25253:** the dashboard took the gateway URL from its own URL, which allowed token theft and RCE.
- **Exposed instances:** 17k to 40k+ reachable from the internet.
- **"ClawHavoc":** malicious marketplace skills.
- **CVE-2026-24763:** Docker sandbox escape through PATH.
- **Moltbook:** an API key leak.
- **Approval-prompt spoofing** with zero-width characters.
- **Unsafe defaults:** full access, sandbox off, an LLM reviewer can approve, plaintext secrets, best-effort audit.

CVE numbers and exposure counts come from press coverage.

## Breadcrumbs

- `src/snow/hub/server.py:86,119-124,186` (token, hub.json, role from Hello)
- `src/snow/hub/supervisor.py:99` (`SNOW_TOKEN` to workers)
- `src/snow/hub/__main__.py:88` (reads hub.json)
