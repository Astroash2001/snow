---
phase: 01-always-on-voice-loop
plan: 06
subsystem: hub
tags: [cli, launcher, subprocess, env-scrub, dev-tools]

requires:
  - phase: 01-always-on-voice-loop/01-03
    provides: HubClient, BrainWorker, settings helpers, test fixtures
  - phase: 01-always-on-voice-loop/01-04
    provides: dev role, DevSay/DevKill commands, COMMAND_ROLES
provides:
  - "`snow` CLI dispatch table for every Phase 1 command"
  - "`snow run` / `python -m snow.hub`: hub plus config-driven workers with scrubbed environments"
  - "`snow dev say` (exit 0 on reply, 1 on no reply) and `snow dev kill`"
  - config/snow.toml hub settings and worker table
affects: [01-09, 01-11, 01-13, 01-14]

commits: 1
plan_head_before: f12b47dbece29993c5b9eeb1f0afbf9a2c67c229
plan_head_after: f51c343

actuals:
  tokens: 9000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Lazy 'module:function' command table; ModuleNotFoundError for the command's own module means 'not available in this build'"
    - "Worker env = parent env minus any name containing KEY/TOKEN/SECRET/PASSWORD, plus SNOW_HUB_URL and SNOW_TOKEN"

key-files:
  created:
    - src/snow/hub/__main__.py
    - src/snow/cli.py
    - src/snow/devtools.py
    - config/snow.toml
    - tests/test_cli.py
  modified: []

key-decisions:
  - "The hub reads its own token back from hub.json instead of exposing Hub._token, so server.py is untouched"
  - "`snow dev say` counts a reply.final with empty text as no reply (the silent all-providers-down case of D-41), so it stays correct after plan 01-08 starts publishing that event"
  - "Worker stderr is written to logs/<name>.err so an import-time crash of a not-yet-built worker is diagnosable"

requirements-completed: [CORE-01, CORE-03]

coverage:
  - id: D1
    description: "snow run starts the hub on loopback, writes hub.json and launches enabled workers; the brain worker connects and heartbeats; dev say is echoed durably"
    requirement: CORE-03
    verification:
      - kind: integration
        ref: "tests/test_cli.py#test_hub_launches_workers_with_scrubbed_env"
        status: pass
    human_judgment: false
  - id: D2
    description: "Workers get SNOW_HUB_URL and SNOW_TOKEN and no variable containing KEY, TOKEN, SECRET or PASSWORD (T-01-55)"
    requirement: CORE-01
    verification:
      - kind: integration
        ref: "tests/test_cli.py#test_hub_launches_workers_with_scrubbed_env"
        status: pass
      - kind: unit
        ref: "tests/test_cli.py#test_scrub_env_removes_secret_names_and_adds_hub_address"
        status: pass
    human_judgment: false
  - id: D3
    description: "A missing worker module (voice, hud) is logged and never stops the hub"
    requirement: CORE-01
    verification:
      - kind: manual
        ref: "default config/snow.toml enables voice and hud, whose modules do not exist yet; only the brain+envdump table is exercised by the automated test"
        status: untested
    human_judgment: true
  - id: D4
    description: "snow --help lists every Phase 1 command; an unimportable command prints the 'not available in this build' line and exits 2"
    requirement: CORE-01
    verification:
      - kind: unit
        ref: "tests/test_cli.py#test_help_lists_phase_1_commands"
        status: pass
      - kind: unit
        ref: "tests/test_cli.py#test_missing_module_is_not_available_in_this_build"
        status: pass
    human_judgment: false
  - id: D5
    description: "snow dev say exits 1 with 'no reply' after its timeout when no provider answers"
    requirement: CORE-03
    verification:
      - kind: integration
        ref: "tests/test_cli.py#test_hub_launches_workers_with_scrubbed_env"
        status: pass
    human_judgment: false
  - id: D6
    description: "Live reply: with a Groq key stored, `snow run` plus `snow dev say \"Good evening\"` prints a Jarvis-style reply and snow.db holds both rows"
    requirement: CORE-03
    verification:
      - kind: manual
        ref: "01-06-PLAN.md human-check"
        status: untested
    human_judgment: true

duration: 20min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 06: CLI, Hub Launcher and Dev Commands Summary

**`snow run` starts the hub and launches config-listed workers with secret-scrubbed environments, and `snow dev say` prints the streamed reply (exit 1 "no reply" on timeout) through a lazy dispatch table covering every Phase 1 command**

## Accomplishments
- Tracer slice runs end to end from a terminal: hub, brain worker subprocess, dev input and durable log, proven by a real `python -m snow.hub` smoke test (brain heartbeat seen, `transcript.final` echoed, `snow dev say ping --timeout 2` exits 1 with "no reply").
- T-01-55: the launcher drops every variable whose name contains KEY, TOKEN, SECRET or PASSWORD (case-insensitive) and adds `SNOW_HUB_URL` and `SNOW_TOKEN`; the env-dump worker confirms `FAKE_API_KEY` and `SOME_SECRET` never reach a child.
- `snow --help` lists run, setup, install-autostart, uninstall-autostart and the five `dev` commands; commands whose modules do not exist yet (`setup`, `install-autostart`, `dev inject-wav`, ...) print `snow: '<name>' is not available in this build` and exit 2, while a broken import inside an existing module still raises.
- Verified: `uv run pytest -x -q` 46 passed, `ruff check` and `ruff format --check` clean, `pyright` strict 0 errors.

Tracer gate: single-task plan, nothing to expand; both `<verify>` commands re-run green after the commit.

## Task Commits
1. **Task 1: snow run and snow dev say** - `f51c343` (feat)

## Safety note for the launch smoke test
The launched brain subprocess reads the REAL Windows Credential Manager (the hub's scrub removes `PYTHON_KEYRING_BACKEND`, so a fake keyring cannot reach it). The test therefore rewrites every `base_url` in a temp copy of `models.toml` to `http://127.0.0.1:9/v1` (nothing listens there), so a key the user has stored can never reach a real provider and the "no reply" path is guaranteed. The test never reads, prints or sets a real key; its only fake secrets are `FAKE_API_KEY` and `SOME_SECRET` in the hub's environment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Hub-not-running guard in dev commands**
- `snow dev say` / `snow dev kill` print `snow: the hub is not running (start it with snow run)` and exit 1 when `hub.json` is absent, instead of waiting out the reconnect backoff silently.
- Files: src/snow/devtools.py. Commit f51c343.

**2. [Rule 2 - Missing Critical] Empty reply.final counts as no reply**
- ReplyFinal with empty text is the D-41 silent case; `say` exits 1 on it so plan 01-08's durable-error path does not flip the exit code to 0.

Beyond that: plan executed as written. The smoke test waits 15 s (not 10 s) overall for the brain heartbeat plus echo to avoid cold-start flakiness; `Ctrl+C` handling and the Job Object are left to plan 01-14 as planned.

## Issues Encountered
- Test seam: the `hub` fixture in conftest is in-process, so the launch test uses its own `launched_hub` fixture that spawns the real process and kills the whole tree with psutil on teardown.

## Known Stubs
- `config/snow.toml` enables `voice` and `hud` workers whose modules (`snow.voice`, `hud/`) do not exist yet; they fail to launch or exit and are logged. Intentional per the plan; plans 01-09 and 01-13 make them real.
- CLI entries `setup`, `install-autostart`, `uninstall-autostart`, `dev inject-wav`, `dev probe-models`, `dev audition-voices`, `dev record-negatives` point at modules later plans add.
- `cmd.dev.kill` is accepted by the hub but acted on only by plan 01-14.
- Worker `hud` command path is an unverified Windows Electron location until plan 01-13.

## Threat Flags
None. T-01-55 mitigated and tested; T-01-SC: no new packages.

## Not run
- Human-check (live reply with a stored Groq key) was not performed by the agent, by design: it would use the user's real key.

## Self-Check: PASSED
- Created files exist: src/snow/hub/__main__.py, src/snow/cli.py, src/snow/devtools.py, config/snow.toml, tests/test_cli.py.
- Commit f51c343 is an ancestor of HEAD; acceptance greps (`CREATE_NO_WINDOW`, `SNOW_TOKEN`, `snow.config.setup:main`, `snow.hub.autostart:install`, `snow.voice.devinput:main`, `[workers.brain]`, `retention_days = 30`) satisfied.

---
*Phase: 01-always-on-voice-loop*
*Completed: 2026-10-16*
