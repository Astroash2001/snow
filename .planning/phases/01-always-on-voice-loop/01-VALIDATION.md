---
phase: "1"
slug: "always-on-voice-loop"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-15"
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `01-RESEARCH.md` § Validation Architecture, adjusted for the voice stack revision of 2026-10-15 (CONTEXT D-32 to D-41): Groq speech-to-text plus local Moonshine, the voice router (Pocket TTS, Cartesia, Chatterbox, Kokoro) and tone detection.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode=auto`), respx for HTTP mocks; Vitest 5.0.4; @playwright/test (Electron) |
| **Config file** | none — Wave 0 installs `pyproject.toml` `[tool.pytest.ini_options]` (markers `hardware`, `gpu`, `slow`, `network`), `hud/vitest.config.ts`, `hud/playwright.config.ts` |
| **Quick run command** | `uv run pytest -x -q -m "not hardware and not gpu and not slow and not network"` ; `npm --prefix hud run test` |
| **Full suite command** | `uv run pytest -m "not hardware and not gpu and not network" && npm --prefix hud run test && npm --prefix hud run e2e` (CI); the local hardware suite adds `-m "hardware or gpu or network"` |
| **Estimated runtime** | ~30 seconds quick, ~3 minutes full CI set |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full CI suite green plus the local hardware suite (latency percentiles, wake false accepts, barge-in on headphones, Groq and Cartesia live calls)
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

Task IDs are filled in by the planner. Rows below are seeded per requirement; each plan task must point at one of these commands or add its own.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | CORE-01 | — | Logon task runs as the user, not a service | unit + manual (reboot) | `uv run pytest tests/hub/test_autostart.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CORE-02 | — | N/A | integration | `uv run pytest tests/hub/test_supervisor.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CORE-03 | — | Events schema-valid; no secrets in events | unit | `uv run pytest tests/contracts tests/hub/test_eventlog.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CORE-04 | — | N/A | unit (respx) | `uv run pytest tests/brain/test_config_swap.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CORE-08 | — | Keyless providers skipped | unit (respx) | `uv run pytest tests/brain/test_chain.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CORE-09 | — | N/A | unit | `uv run pytest tests/brain/test_cooldown.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | CORE-10 | — | N/A | unit | `uv run pytest tests/brain/test_provenance.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | VOIC-01 | — | No network sockets from the voice worker while asleep; no audio sent before wake | unit + integration | `uv run pytest tests/voice/test_wake.py tests/voice/test_no_egress.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | VOIC-03 | — | Mute closes the input stream | unit + e2e | `uv run pytest tests/voice/test_mute.py -x` ; `npm --prefix hud run e2e -- mute` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | VOIC-04 | — | Only in-conversation audio goes to Groq; key never logged | unit (respx Groq mock) + slow (Moonshine on fixture WAVs under a WER bound) + network | `uv run pytest tests/voice/test_stt_router.py -x` ; `uv run pytest -m slow tests/voice/test_moonshine_wer.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | VOIC-05 | — | N/A | unit | `uv run pytest tests/voice/test_turn_engine.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | VOIC-06 | — | N/A | integration (fake transport) | `uv run pytest tests/voice/test_bargein.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | VOIC-08 | — | N/A | unit + e2e | `uv run pytest tests/voice/test_partials.py -x` ; `npm --prefix hud run e2e -- transcript` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SPCH-01 | — | N/A | unit | `uv run pytest tests/brain/test_no_scripts.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SPCH-02 | — | Tone audio stays in memory, never written to disk | unit | `uv run pytest tests/voice/test_tone.py tests/brain/test_emotion.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SPCH-03 | — | N/A | integration | `uv run pytest tests/voice/test_tts_router.py tests/voice/test_tts_failover.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SPCH-04 | — | N/A | unit + hardware | `uv run pytest tests/voice/test_latency_fake.py -x` ; `uv run pytest -m hardware tests/hardware/test_latency.py` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HUD-03 | — | N/A | e2e perf | `npm --prefix hud run e2e -- perf` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | QUAL-01 | — | Secret scan and dependency audit in CI | CI config lint + manual (failing PR) | `gh run list` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | QUAL-03 | — | Log redaction | unit + e2e | `uv run pytest tests/test_logging.py tests/hub/test_health.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SAFE-09 | — | Canary secret absent from logs, events, WebSocket frames, config | unit | `uv run pytest tests/test_secrets_canary.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SAFE-12 | — | Private data with only untrusted providers raises `PrivacyBlockedError` with zero HTTP calls | unit (respx) | `uv run pytest tests/brain/test_privacy.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` (pytest markers, ruff, pyright strict), `uv.lock`, `.python-version` = 3.12
- [ ] `tests/conftest.py` — fake audio source and sink, fake hub client, in-memory keyring backend, respx fixtures (Groq STT, LLM providers, Cartesia), fake clock
- [ ] `tests/fixtures/audio/*.wav` — synthetic fixtures: wake only, wake plus command at 0/150/600 ms gaps, mid-thought pause, TV-like negatives, "that's all" and "mute" phrases, barge-in overlap, calm versus stressed delivery for tone tests
- [ ] `hud/` toolchain — Vitest, Playwright (Electron), Biome, ajv contract tests; mock hub for e2e
- [ ] `.github/workflows/ci.yml`; gitleaks config; pip-audit
- [ ] `tests/hardware/` harness (marked) — latency p50/p95, wake false accepts per hour, barge-in on headphones, reboot-logon checklist, Pocket TTS first-audio time, Chatterbox VRAM

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Snow is running after Windows logon | CORE-01 | Needs a real reboot | Reboot, log in, say "Hey Snow", confirm the orb shows listening |
| CI blocks a failing change | QUAL-01 | Needs a real failing branch; private repo on GitHub Free has no enforced required checks (D-41), so the pre-push hook is checked too | Push a branch with a failing test; confirm CI fails and the pre-push hook refuses |
| Mood clips change Pocket TTS delivery enough | SPCH-02, SPCH-03 | Subjective listening | Play the same line with each mood clip; the user judges whether moods are distinct |
| Tone tags look right for the user's voice | SPCH-02 | Subjective, real voice | Speak 10 turns calm and 10 stressed; check the tone tags in the event log |
| Voice audition (Pocket TTS reference voice, Cartesia stock voice) | SPCH-02 | User preference | Run the audition command and pick voices; store IDs in config |
| Reply starts within about 1 second on real hardware | SPCH-04 | Needs the real mic, network and CPU | Run the hardware latency suite; p50 <= 1.0 s, p95 <= 1.6 s |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
