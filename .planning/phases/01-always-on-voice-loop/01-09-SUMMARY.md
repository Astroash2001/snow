---
phase: 01-always-on-voice-loop
plan: 09
subsystem: ui
tags: [electron, electron-vite, react, zustand, websocket, playwright, mock-hub]

requires:
  - phase: 01-06
    provides: hub.json handoff and SNOW_HUB_URL/SNOW_TOKEN env for the hud worker
  - phase: 01-07
    provides: HUD toolchain, generated contract types, golden samples
provides:
  - Electron dashboard window (sandboxed, contextIsolation on) built to hud/out
  - preload bridge window.snow.hubInfo() over IPC channel hub:info
  - renderer store: pure reduce(state, msg) plus zustand useHud, fed by connectHub()
  - scripted mock hub startMockHub() with send(), received, close(), restart()
  - Playwright Electron smoke spec
affects: [01-11, 01-12, 01-13, 01-14, 01-15, 01-19, 01-21]

commits: 1
plan_head_before: 62dbaed2c1c007559a90b3d76695a48c6d409ef9
plan_head_after: 2b782e3

actuals:
  tokens: 14000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "HUD views derive only from hub snapshot plus events; Electron IPC carries window chrome and the hub URL/token handoff"
    - "Specs drive the mock hub through a script argument or send(); the mock file is never edited per spec"
    - "Rows are keyed by kind plus turn_id, so live deltas, finals and snapshot rows for one turn collapse into one row"

key-files:
  created:
    - hud/electron.vite.config.ts
    - hud/playwright.config.ts
    - hud/src/main/index.ts
    - hud/src/main/hubinfo.ts
    - hud/src/preload/index.ts
    - hud/src/renderer/index.html
    - hud/src/renderer/src/main.tsx
    - hud/src/renderer/src/App.tsx
    - hud/src/renderer/src/index.css
    - hud/src/renderer/src/store.ts
    - hud/src/renderer/src/store.test.ts
    - hud/src/renderer/src/ws.ts
    - hud/e2e/mockHub.ts
    - hud/e2e/smoke.spec.ts
  modified:
    - hud/tsconfig.json

key-decisions:
  - "No \"type\": \"module\": electron-vite emits CommonJS main and preload, which the sandboxed preload needs; the vitest ESM-as-CJS warning from 01-07 stays"
  - "Snow rows are stored in rows (row key snow:<turn>) rather than a separate per-turn map, so reply.final replaces the live text in place"
  - "Empty reply.final (silent all-providers-down case) removes the live row instead of showing an empty Snow row"

requirements-completed: [HUD-03, VOIC-08]

coverage:
  - id: D1
    description: "Dashboard connects to the hub with the token from the preload bridge and shows the state word and snapshot rows"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/smoke.spec.ts (Electron against mock hub)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Live events add a You row and a Snow row and move the state word without a reload"
    requirement: VOIC-08
    verification:
      - kind: e2e
        ref: "hud/e2e/smoke.spec.ts"
        status: pass
      - kind: unit
        ref: "hud/src/renderer/src/store.test.ts (3 tests, golden conversation replay)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Renderer runs with contextIsolation, sandbox on, nodeIntegration off; bridge exposes only hubInfo"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "smoke.spec.ts asserts Object.keys(window.snow) equals [hubInfo] and window.require is undefined"
        status: pass
    human_judgment: false
  - id: D4
    description: "Live check against the real Python hub: snow run, then snow dev say shows the You and Snow rows"
    requirement: VOIC-08
    verification:
      - kind: manual
        ref: "01-09-PLAN.md human-check"
        status: untested
    human_judgment: true

duration: 25min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 09: Electron Dashboard Window Summary

**A sandboxed Electron dashboard that is a pure WebSocket client of the hub: it takes the token over the preload bridge, renders the state word and You/Snow rows from snapshot plus live deltas, and is proven by a Playwright Electron spec against a scripted mock hub**

## Accomplishments
- Walking skeleton closes on the HUD side: `hub snapshot + events -> useHud reducer -> state word and rows`. `reduce(state, msg)` is pure and ignores unknown event types, so a newer hub never breaks an older HUD.
- Security (T-01-07, T-01-08): `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`; preload exposes only `snow.hubInfo()`; the token travels only in the IPC result and the first WebSocket frame, never a URL or a log. The smoke spec asserts the bridge keys and that `window.require` is undefined.
- `getHubInfo()` re-reads env or `run/hub.json` on every call, so a restarted hub (new port and token) is picked up by the next `connectHub()`.
- Mock hub: Node `ws` on 127.0.0.1 port 0, rejects a wrong token with 4401, sends the snapshot then the script, records every inbound frame in `received`, and supports `send()`, `close()` and `restart(port?)`. Default script is `conversation-12.jsonl`.
- Verified: `npm run typecheck`, `lint` (biome ci), `test` (157 pass), `npm run e2e -- smoke` (1 passed), `gen:types` leaves the generated file diff-clean. No Electron process left running.

## Task Commits
1. **Task 1 (tracer): dashboard window connects to the hub and shows the live conversation** - `2b782e3` (feat)

Tracer gate: single-task plan, nothing to expand; `<verify>` (e2e and typecheck) green, lint and unit tests green.

## Deviations from Plan

**1. [Rule 3 - Blocker] `hud/tsconfig.json` gains `"node"` in `types`**
- **Found during:** Task 1 (main process, mock hub and Playwright config use `node:fs`, `node:path`, `process`, `__dirname`)
- **Fix:** `types: ["vite/client", "node"]`. `@types/node` is present as a dependency of the user-approved `@types/ws` pin; no package added.
- **Files modified:** hud/tsconfig.json. **Commit:** 2b782e3

**2. [Rule 2 - Missing critical] `store.test.ts` reducer unit test added** (not in the plan's file list): replays the golden conversation, checks row replacement and unknown-event handling. **Commit:** 2b782e3

**3. [Plan-additive] `src/renderer/src/index.css`**: the Tailwind plugin needs a CSS entry with `@import "tailwindcss"` plus the dark body background (no white flash). **Commit:** 2b782e3

**4. [Plan-clarification] Smoke spec uses `script: []` and drives turn 1 with `hub.send()`** instead of the 50 ms default replay, so "Listening" is asserted deterministically from the snapshot (the full default replay ends in "Standing by" with rows cleared by `conversation.ended`). It also exercises `send()` and `received`.

**Total deviations:** 4 (1 blocker config, 1 missing-critical test, 2 additive). **Impact:** none on scope; no packages added.

## Issues Encountered
- Electron binary was not present; fetched once with `node hud/node_modules/electron/install.js` as approved.
- `conversation-12.jsonl` has no snapshot line (all 116 lines are events); the snapshot comes from `events.json` key `snapshot`.
- The vitest ESM/CJS config warning from 01-07 is unchanged (left because the electron-vite CJS output needs no `type: module`).

## Known Stubs
- `App.tsx` renders a plain row list with plain "You"/"Snow" labels; the orb, mute button, cards and TranscriptView arrive in plans 01-11, 01-12, 01-19 and 01-21 as planned.
- `connectHub()` does not reconnect; on close the HUD shows "Reconnecting" and stays there until reload. Backoff and re-handshake land in plan 01-15.
- Main process: closing the window quits the app; hide-to-mini, tray, single instance and `--autostart`/`--restarted` flags land in plans 01-11 to 01-14.

## Threat Flags
None. Navigation blocking and CSP are deferred to plan 01-15 as the threat model states.

## Not run
- The plan's human-check (real `snow run` plus `snow dev say "Good evening"`) was not performed: it starts the real Python hub, which reads the user's keyring, and this plan's constraints forbid that.

## Self-Check: PASSED
- All 14 created files and the modified tsconfig exist under hud/; commit `2b782e3` is an ancestor of HEAD.
- Acceptance greps: `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false` in main/index.ts; preload exposes exactly `hubInfo`; mockHub exports `startMockHub` and `received`; smoke spec passes.
