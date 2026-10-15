# Walking Skeleton — Snow

**Phase:** 1
**Generated:** 2026-10-15

## Capability Proven End-to-End

After plans 01-01, 01-03 and 01-06 (Python path) and 01-09 (HUD window), a developer runs `uv run snow run`, types `uv run snow dev say "Good evening"`, and sees Snow's LLM-written reply appear live in the Electron dashboard and as durable rows in the SQLite event log; the voice plans then replace the typed line with "Hey Snow" and a spoken reply.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Runtime | Python 3.12 via uv (`.python-version`, hash-locked `uv.lock`, `exclude-newer` delayed adoption), always `uv run` | Voice ML and Windows integration are Python-first; system Python is 3.10 (research F5); supply-chain posture from CLAUDE.md |
| Process topology | One hub process (event bus, SQLite log, WebSocket server, supervisor, health) plus `voice` and `brain` worker processes plus the Electron HUD, all in one Windows Job Object; Task Scheduler restarts the hub (D-40) | CORE-02 can only be shown honestly with separate crash domains; raw audio never leaves the voice process |
| Wire protocol | Loopback WebSocket on 127.0.0.1 with a per-launch 256-bit token in a `hello` message, Origin/Host checks, JSON messages from one Pydantic contract (`src/snow/contracts`) exported to `contracts/events.schema.json` and generated TypeScript types; snapshot first, then deltas | One typed contract for every view (HUD now, phone and history later); drift-gated in CI |
| Data layer | SQLite in WAL mode at `%LOCALAPPDATA%\Snow\data\snow.db`; `events` (durable typed events, speech text in a separate `content` column with 30-day retention) and `state` (mute and similar); numbered SQL migrations with `PRAGMA user_version` | Zero-ops, single user; every later view reads the event log (CORE-03) |
| Auth and secrets | No user accounts in v1; local components authenticate with the hub token; provider keys only in Windows Credential Manager via `keyring`, entered with `snow setup`, read at call time by the process that needs them (D-24) | SAFE-09; no `.env`, no keys in config, logs, events or the HUD |
| LLM access | Plain `openai` SDK with `base_url` per provider, `max_retries=0`, per-role ordered chains in `config/models.toml`, privacy routing by data class and provider trust (D-21 to D-28) | Swap by configuration, provider independence, free-tier resilience |
| Voice stack | Local wake (openWakeWord), Silero VAD and Smart Turn v3.2 driven by a plain-Python TurnEngine; Groq Whisper for final transcripts plus local Moonshine for live words and fallback; voice router Pocket TTS (CPU) everyday, Cartesia for big moments, Chatterbox (GPU, isolated env) when plugged in and idle, kokoro-onnx last (D-32 to D-39) | Least laptop load with emotion, free; Pipecat used only for its VAD and Smart Turn analyzers |
| HUD shell | Electron 44 + React 19 + Vite (electron-vite) + zustand + Tailwind 4 tokens; Canvas 2D ASCII glyph orb; dashboard and mini windows; tray | User decision 2026-10-13 (Electron, not Tauri); HUD is a WebSocket client so the shell stays swappable; Phase 6 swaps the orb renderer behind the same `Presence` props |
| Deployment | Local only in Phase 1: `uv run snow run` (dev) and `snow install-autostart` (Task Scheduler at logon, per-user, RunLevel Limited); no installer until Phase 7 | Session 0 services have no microphone or desktop; packaging is a Phase 7 concern |
| Quality gates | ruff, pyright strict, pytest (+ markers hardware/gpu/slow/network), Biome, tsc, Vitest, Playwright Electron, contract drift, gitleaks, pip-audit, npm audit; GitHub Actions on windows-latest plus a local pre-push hook (private repo, D-41) | QUAL-01 and the product quality bar |
| Directory layout | `src/snow/{contracts,hub,brain,voice,config,common}`, `config/*.toml` (snow, models, persona, voice, tts), `contracts/` (generated schema and golden samples), `hud/` (electron-vite: `src/main`, `src/preload`, `src/renderer`), `engines/chatterbox/` (isolated env), `training/wakeword/`, `tests/` (python), `hud/e2e/` (Playwright) | Ports-and-adapters by process; each subsystem owns its config file |

## Stack Touched in Phase 1

- [x] Project scaffold (uv + pyproject, electron-vite HUD, lint, type check, test runners) — plans 01-01, 01-07
- [x] Routing — WebSocket message routing by type and role in the hub (the app has no HTTP routes) — plans 01-01, 01-04
- [x] Database — real write (`EventLog.append`, `state` mute) and real read (snapshot replay at hub start) — plans 01-01, 01-04
- [x] UI — interactive element wired to the core (Mute button and orb send `cmd.mute.set`; the label flips on the confirmed event) — plans 01-09, 01-21
- [x] Deployment — documented local full-stack run (`npm --prefix hud run build` then `uv run snow run`) and logon autostart — plans 01-06, 01-14

## Out of Scope (Deferred to Later Slices)

- Coding agents, the safety gate, risk tiers, approvals, kill switch, speaker verification (Phase 2)
- Pinned running copy separate from the dev repo and approved self-upgrade (Phases 2 and 3)
- Activity stream, worktrees, task board, phone channel, Tailscale (Phases 3 and 4)
- PC control and live panels (Phase 5)
- 3D shader orb, spawn-on-demand dashboard, history view, phone HUD, silent mode, command bar (Phase 6)
- Installer, auto-update, code signing (Phase 7)
- Push-to-talk hotkey (removed by D-07), always-listening mode without a wake word, echo cancellation for laptop speakers, Hinglish

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2: drive Claude Code by voice behind the deterministic safety gate (new `agents` worker on the same hub protocol; approvals as new event types)
- Phase 3: steer and review agent work in worktrees; activity stream rendered from the event log
- Phase 4: hand off and walk away; Telegram bot and Tailscale as one more client of the same events and approval object
- Phase 5: PC control tools as adapters behind the same policy gate; live panels on the HUD
- Phase 6: 3D shader orb behind the same `Presence` props, spawn-on-demand panels, phone HUD, history, silent mode
- Phase 7: installer, approved auto-update with rollback, failure explanations, egress verification
