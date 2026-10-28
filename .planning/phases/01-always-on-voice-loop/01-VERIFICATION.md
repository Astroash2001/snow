---
phase: 01-always-on-voice-loop
verified: 2026-10-28T12:00:00Z
status: passed
score: 5/5 must-haves verified
covered_files:
  - .github/workflows/ci.yml
  - .planning/phases/01-always-on-voice-loop/01-01-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-01-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-02-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-02-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-03-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-03-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-04-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-04-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-05-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-05-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-06-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-06-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-07-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-07-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-08-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-08-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-09-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-09-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-10-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-10-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-11-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-11-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-12-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-12-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-13-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-13-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-14-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-14-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-15-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-15-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-16-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-16-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-17-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-17-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-18-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-18-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-19-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-19-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-20-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-20-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-21-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-21-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-22-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-22-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-23-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-23-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-24-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-24-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-25-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-25-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-26-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-26-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-27-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-27-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-28-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-28-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-29-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-29-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-30-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-30-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-31-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-31-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-32-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-32-SUMMARY.md
  - .planning/phases/01-always-on-voice-loop/01-33-PLAN.md
  - .planning/phases/01-always-on-voice-loop/01-33-SUMMARY.md
  - config/models.toml
  - config/tts.toml
  - config/voice.toml
  - hud/playwright.config.ts
  - src/snow/brain/chain.py
  - src/snow/config/secrets.py
  - src/snow/hub/autostart.py
  - src/snow/hub/supervisor.py
  - src/snow/voice/__init__.py
  - src/snow/voice/__main__.py
  - src/snow/voice/aec.py
  - src/snow/voice/config.py
  - src/snow/voice/loopback.py
  - src/snow/voice/pipeline.py
  - tests/test_cli.py
  - tests/voice/test_loopback.py
covered_digest: "v3:sha256:3e0e9972d3983a527a527f5d11b72652bc4c78e17999cf161a0cb256e34e81a1"
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "After the user logs in to Windows, Snow is already running (CORE-01)"
    test: "Run `uv run snow install-autostart`, sign out and back in to Windows"
    expected: "Snow's hub, voice and brain workers and the mini orb are up with no manual launch, and the Health panel shows no Down row"
    why_human: "Only the generated Task Scheduler script text is unit-tested (tests/hub/test_autostart.py). Accepted untested by the user on 2026-10-28 (see Acknowledged Gaps)."
re_verification:
  previous_status: human_needed
  previous_score: 5/5
  gaps_closed: []
  gaps_remaining: []
  regressions: []
---

# Phase 1: Always-On Voice Loop Verification Report

**Phase Goal:** As a developer, I want to wake Snow by voice and talk with it naturally, so that I can speak to my PC instead of typing.
**Verified:** 2026-10-28 (re-verified after quick 261028-gyg and later commits)
**Status:** passed
**Re-verification:** Yes, covered source files changed since the first report (commit 974c356)

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After Windows logon Snow is running; "Hey Snow" opens a turn, HUD shows listening within 100 ms, no idle audio leaves the PC | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED (logon part) / VERIFIED (wake, HUD, privacy) | `src/snow/hub/autostart.py` builds an AtLogOn, Interactive, RunLevel Limited task (84 lines, not a Windows Service); `tests/hub/test_autostart.py` checks the script text. Wake is `WakeGate` in `pipeline.py` before any STT; UAT 1-3, 6, 7 passed live (wake 7 of 9 at desk). Far-field wake was waived by the user (UAT 14). HUD 100 ms is covered by HUD e2e per SUMMARYs 07/09/15. The real logon path was never run live. |
| 2 | Natural speech: mid-thought pauses tolerated, live transcript, LLM-written emotion-voiced reply within about 1 s, barge-in stops and cancels the reply | ✓ VERIFIED | `config/voice.toml` `stop_secs = 0.7` (UAT 4 retest yes). UAT 2, 4, 5, 10 pass live; barge-in reworked by quick tasks 261026-wvr and 261027-rx2 (speaker-verified, instant pause, interruption-aware brain history); UAT 5 retest "yes it works fine". Replies come from `src/snow/brain` with `persona.toml`; no hardcoded phrases beyond the LLM-down fallback. |
| 3 | Local voice for everyday replies; cloud TTS and STT failover; provider and model changes are config-only; fallback chain with limits and cooldown, HUD shows active provider; untrusted providers never get private data; keys only in Credential Manager | ✓ VERIFIED | `config/models.toml` defines three roles with ordered chains over five providers and trust levels. `src/snow/brain/chain.py` (595 lines) skips untrusted providers for private data (`data_class="private"` default, fails closed, cooldown never promotes an untrusted entry). `src/snow/brain/limits.py` (230 lines) holds counters and cooldown; quick 261026-nvh made timeouts per-model (`tests/brain/test_cooldown.py`). `src/snow/config/secrets.py` uses `keyring` only, and `redact_secrets` runs in the structlog chain. Grep found no key literals in `config/`, `src/` or `hud/src`. TTS routing, Cartesia and Chatterbox policy and outage fallback are covered by automated tests (UAT 12). By user decision every reply is Kokoro `bm_daniel` (UAT 13 skipped). |
| 4 | Killing a subsystem brings it back; HUD shows each subsystem up or down and unmistakable mute; every turn is a typed event in a durable log | ✓ VERIFIED | `src/snow/hub/supervisor.py` (389 lines): jittered backoff 0.5 s to 30 s, heartbeat hang watch, crash-loop breaker, Job Object; real-subprocess crash and kill tests in `tests/hub/test_supervisor.py`. Health rows in `pipeline.py` (`wake_word`, others). `src/snow/hub/eventlog.py` plus `contracts/events.py` typed catalog and schema-drift check in CI. UAT 1, 6, 11 pass (mute banner, health rows, sleep/resume). |
| 5 | Every change runs typed, linted, tested CI and a failing change cannot be merged | ✓ VERIFIED (with accepted deviation) | `.github/workflows/ci.yml` runs ruff, ruff format, pyright, pytest, contract and fixture drift, pip-audit, plus HUD lint, tests and e2e; actions pinned by SHA. `gh api` shows `main` has no branch protection (GitHub Free private repos cannot enforce it, D-41). The substitute is `.githooks/pre-push` calling `scripts/check.sh`, with `core.hooksPath` set to `.githooks` on this clone. Run 40129871671 on 690c6b5 is green. |

**Score:** 5/5 truths verified at the roadmap level; 1 sub-part (real Windows logon) present but not exercised live.

### Required Artifacts / Key Links

All 33 plans have SUMMARYs. The files above (pipeline, chain, supervisor, autostart, secrets, config, CI) exist, are substantive and are wired: `pipeline.py` imports `WakeGate`, the STT router and TTS router; the supervisor launches `snow.brain` and `snow.voice` workers (live process listing shows both running under the user's Snow).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full Python suite (excluding hardware, gpu, network markers per `pyproject.toml`) | `uv run pytest -q` | 665 passed, 22 deselected, 0 errors | PASS |
| New and changed tests | `uv run pytest tests/voice/test_loopback.py tests/test_cli.py tests/hub/test_autostart.py -q` | 47 passed | PASS |
| Lint, format, types | `uv run ruff check src tests`, `ruff format --check`, `pyright src/snow/voice` | all clean, 0 errors | PASS |
| CI | `gh run list` | run 40655415486 on 6f1ea22 green (run 40653137667 on cb834e7, a docs-only commit, failed and is superseded) | PASS |

### Requirements Coverage

Every ID in the ROADMAP list was found in at least one PLAN `requirements:` field, and each is mapped to Phase 1 in REQUIREMENTS.md. No orphans: REQUIREMENTS.md maps no other ID to Phase 1 (VOIC-09 is Phase 6, SPCH-05/06 Phase 3, SPCH-07 Phase 6).

| Requirement | Source Plans | Status | Evidence |
|-------------|--------------|--------|----------|
| CORE-01 | 06, 14, 27 | ? NEEDS HUMAN | Logon task code and tests exist; no live logon run (see human item) |
| CORE-02 | 14 | ✓ SATISFIED | Supervisor restart policy and subprocess crash/kill tests |
| CORE-03 | 01, 04, 06, 07 | ✓ SATISFIED | Typed event catalog, durable SQLite log, hub round-trip tests |
| CORE-04 | 03, 08, 17 | ✓ SATISFIED | `models.toml` roles, providers and base URLs are config-only |
| CORE-08 | 08, 17 | ✓ SATISFIED | Ordered chains, failover on 429/5xx/timeout, "not configured" for missing keys |
| CORE-09 | 12 | ✓ SATISFIED | `limits.py` counters and reset-header cooldown; per-model cooldown (261026-nvh) |
| CORE-10 | 08, 16, 21, 23 | ✓ SATISFIED | Provider/model recorded per response, shown in HUD health (UAT 16 screenshot shows the provider notices) |
| VOIC-01 | 02, 05, 13, 18, 20, 30 | ✓ SATISFIED | Local openWakeWord gate; no audio before wake (automated); desk use only, far-field waived (UAT 14) |
| VOIC-03 | 04, 20, 21, 25, 27 | ✓ SATISFIED | UAT 6 passed (mute by voice, Muted banner, mic indicator) |
| VOIC-04 | 02, 13, 20, 22 | ✓ SATISFIED | Groq final, Moonshine live and fallback; router tests (UAT 12), live row (UAT 4) |
| VOIC-05 | 05, 18 | ✓ SATISFIED | `stop_secs = 0.7`, Smart Turn; UAT 4 retest |
| VOIC-06 | 29 | ✓ SATISFIED | UAT 5 retest after 261026-wvr and 261027-rx2 |
| VOIC-08 | 09, 21, 22 | ✓ SATISFIED | Live and final You rows (UAT 2, 4, 15) |
| SPCH-01 | 16 | ✓ SATISFIED | LLM-written replies from persona; UAT 2, 10 |
| SPCH-02 | 05, 16, 24, 31, 32, 33 | ✓ SATISFIED | Local tone analysis; UAT 10 (stressed question gets a calm short reply) |
| SPCH-03 | 02, 26, 28, 31, 33 | ✓ SATISFIED | Router with failover covered by automated tests; live path is Kokoro by user choice (UAT 13 skipped) |
| SPCH-04 | 17, 26, 29 | ✓ SATISFIED | Latency test and live use (UAT 2); the 0.7 s turn wait adds about 0.5 s, accepted by the user |
| HUD-03 | 07, 09, 15, 19, 20, 23, 25 | ✓ SATISFIED | Local-event-driven HUD, e2e tests |
| QUAL-01 | 10 | ✓ SATISFIED (deviation) | CI present and green; merge blocking is a local pre-push hook because GitHub Free cannot enforce checks (D-41) |
| QUAL-03 | 11, 14, 23 | ✓ SATISFIED | structlog JSON logs; Health panel subsystem rows |
| SAFE-09 | 03, 11 | ✓ SATISFIED | `keyring`-only secrets, `snow setup`, redaction, canary test `tests/test_secrets_canary.py` |
| SAFE-12 | 08 | ✓ SATISFIED | Trust levels in config; private data fails closed on untrusted providers (`chain.py`) |

### Quick Tasks Folded Into the Phase

261026-nui, 261026-nvh, 261026-wvr (01, 02) and 261027-rx2 each have a SUMMARY in `.planning/quick/`. Their effects are visible in code and config: per-model cooldown, speaker-verified barge-in, instant pause and `barge_in_min_ms = 400`. UAT 5 and 7 were re-run after them and passed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/test_cli.py` | 108-114 | `launched_hub` previously lacked its own `SNOW_HUB_MUTEX` | Resolved | Commit 536aee7 gives it a unique mutex; the earlier environmental error is gone (full suite 0 errors with the user's Snow running) |
| `tests/test_cli.py` | 113 | `f"Local\SnowHubTest..."` has an unescaped backslash in a non-raw string | Info | Ruff and pyright pass and the test passes; a raw string would be cleaner |

A grep for TBD/FIXME/XXX over `src/snow/voice`, `hub`, `brain`, `config`, `config/` and `tests/voice/test_loopback.py` found none.

### Human Verification Required

None outstanding. The Windows logon autostart check was accepted untested by the user (see Acknowledged Gaps).

### Accepted Limits (not gaps)

- UAT 13 (non-Kokoro voices) and UAT 14 (far-field wake, measured 20/50) are user-waived decisions.
- Backlog 999.1 (Kokoro on the GPU); orb polish moves to Phase 6. Backlog 999.2 (FxSound-proof echo cancellation) is now done, see below.
- Misheard words from residual echo of Snow's own voice are reduced by speaker-verified barge-in; full speaker verification gating belongs to Phase 2.

### Changes Since the First Report

Quick 261028-gyg feeds the echo canceller a WASAPI loopback reference (VOIC-06). Verified in code: `src/snow/voice/loopback.py` (`LoopbackReference`, `pick_endpoint`) is imported and started in `pipeline.py` when `audio.aec_reference == "loopback"` and closed on shutdown; `aec.py` exposes `use_loopback`, `loopback_block`, `loopback_stale`; it falls back to the render reference on missing, lost, ambiguous or silently dead loopback, logging the loss before the switch; audio stays in memory only. `config/voice.toml` enables it, and the model default stays `render`. `tests/voice/test_loopback.py` passes. The hardware loopback suite (7/7 with FxSound on, per the quick SUMMARY) is a user-run result and was not re-run by this verifier. The wake-only fallback was removed (3baf5f5), sherpa-onnx now loads in `snow/voice/__init__.py` (b7e8eec), and CI-only Playwright retries were added; none change a roadmap criterion.

### Gaps Summary

No gaps. The phase goal is delivered: UAT shows wake, natural talk, barge-in, mute, sleep, tone matching and provider failover working live, and the code, configuration and tests back each roadmap criterion. The one open item, a live check of the Windows logon autostart, was accepted untested by the user on 2026-10-28 and is recorded under Acknowledged Gaps, so the status is `passed`.

---

_Verified: 2026-10-28_
_Verifier: Claude (gsd-verifier)_

## Acknowledged Gaps

- CORE-01 / success criterion 1: Windows logon autostart (`uv run snow install-autostart`, then a sign-out and sign-in) was not run live. The user accepted it untested on 2026-10-28 ("ok i think it will work"). Generated Task Scheduler script is unit-tested.
