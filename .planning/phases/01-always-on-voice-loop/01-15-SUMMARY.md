---
phase: 01-always-on-voice-loop
plan: 15
subsystem: ui
tags: [electron, react, zustand, websocket, reconnect, csp, tailwind, design-tokens, playwright]

requires:
  - phase: 01-09
    provides: dashboard window, hub.json handoff, mock hub, smoke spec
provides:
  - connectHub() that reconnects with 0.5 s doubling to 8 s backoff, re-reading hub.json before every attempt
  - connection-lost banner and a visually hidden role="status" region announcing "Reconnected"
  - every UI-SPEC token as a --snow-* CSS variable (styles.css), Inter and JetBrains Mono bundled locally
  - locked-down renderer: navigation blocked, window.open denied, production CSP with connect-src ws://127.0.0.1:*
affects: [01-11, 01-12, 01-19, 01-21]

commits: 2
plan_head_before: d695b375aaf4bfab6bf9aa5c7241fe14310e1fb8
plan_head_after: cf427d5287d4476fb5de502f61e6cc49c7b7f66a

actuals:
  tokens: 14000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Components reference --snow-* variables only (Tailwind 4 var syntax such as text-(--snow-text-3)); the :root block in styles.css is the single token source"
    - "CSP is injected by a build-only Vite plugin in electron.vite.config.ts; dev keeps its HMR allowances"
    - "connectHub() returns a stop function; the reconnect loop owns the socket and ignores closes from superseded sockets"

key-files:
  created:
    - hud/src/renderer/src/styles.css
    - hud/src/renderer/src/env.d.ts
    - hud/e2e/connection.spec.ts
  modified:
    - hud/src/renderer/src/ws.ts
    - hud/src/renderer/src/App.tsx
    - hud/src/renderer/src/main.tsx
    - hud/src/renderer/src/store.test.ts
    - hud/src/main/index.ts
    - hud/electron.vite.config.ts
    - hud/biome.json
  deleted:
    - hud/src/renderer/src/index.css

key-decisions:
  - "Connection lost is announced by the banner's role=\"alert\"; the role=\"status\" region carries only \"Reconnected\" (the one new string the plan specifies)"
  - "No explicit cmd.snapshot request after reconnect: the hub already sends a full snapshot on every accepted hello and the reducer replaces state from it"

requirements-completed: [HUD-03]

coverage:
  - id: D1
    description: "Dashboard shows the Cannot reach Snow's core banner and Reconnecting when the hub drops, and recovers on a new port with Reconnected announced"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/connection.spec.ts (hub close, restart on new port with rewritten hub.json)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reducer is pure and covered: final transcript, delta/final reply, conversation.started clears rows, unknown type returns same object"
    requirement: HUD-03
    verification:
      - kind: unit
        ref: "hud/src/renderer/src/store.test.ts (5 new tests, 162 total pass)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every UI-SPEC token exists as a --snow-* variable; fonts are bundled locally (no CDN reference)"
    requirement: HUD-03
    verification:
      - kind: command
        ref: "grep of styles.css for --snow-bg: #0B0E14 and --snow-state-muted: #F87171; grep -rn fonts.googleapis hud/src returns nothing; no raw hex in .tsx"
        status: pass
    human_judgment: false
  - id: D4
    description: "Renderer blocks navigation and window.open; production CSP allows only ws://127.0.0.1 for connect"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/connection.spec.ts (CSP meta present in built page, location unchanged after navigation attempt, one window after window.open)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 15: Dashboard Reconnect, Design Tokens and Renderer Lockdown Summary

**The dashboard now survives hub restarts on its own (banner, "Reconnecting", backoff, hub.json re-read, "Reconnected" announcement), carries every UI-SPEC design token as a `--snow-*` variable with locally bundled fonts, and runs a renderer that cannot navigate, open windows or connect anywhere except the loopback hub**

## Accomplishments
- Reconnect (T1, tracer): `ws.ts` retries after 0.5, 1, 2, 4, 8, 8... s, calls `window.snow.hubInfo()` before each attempt (a restarted hub has a new port and token), resets the backoff only after a connection stayed up 60 s, and returns a stop function. `App.tsx` shows a full-width banner above the content (heading and body are the exact UI-SPEC copy, alert-hue border, `role="alert"`) and a visually hidden `role="status"` region that says "Reconnected" once the connection returns after a loss.
- Tests: 5 new reducer tests (final transcript adds You row and clears partial, snapshot then final appends, deltas build one Snow row replaced by the final, `conversation.started` clears rows, unknown type returns the same object). `connection.spec.ts` closes the mock hub, asserts banner plus "Reconnecting", restarts it on a new port with a rewritten hub.json, and asserts banner gone, status "Reconnected", state word back to "Listening".
- Tokens (T2): `styles.css` declares colors, orb state hues, spacing, radii, four type sizes and two weights, durations and easing as `--snow-*`; a `@theme inline` block points Tailwind's font and text scale at them. `@fontsource/jetbrains-mono/400.css` joins Inter Variable in `main.tsx` (both packages were already pinned; both bundled into `out/renderer/assets`).
- Lockdown (T2): `will-navigate` is prevented and `setWindowOpenHandler` denies; a build-only Vite plugin injects the CSP meta, and the built `out/renderer/index.html` contains `connect-src ws://127.0.0.1:*`. The e2e runs against that built page, so the CSP is proven not to break scripts, styles, fonts or the hub socket.
- Verified: `typecheck`, `lint` (biome ci), `test` (162 pass), `e2e -- smoke connection` (3 pass), `gen:types` leaves `src/generated` diff-clean. No packages added.

## Task Commits
1. **Task 1 (tracer): dashboard reconnects to a restarted hub** - `2048f15` (feat)
2. **Task 2: design tokens, local fonts and renderer lockdown** - `cf427d5` (feat)

Tracer gate: `test` and `e2e -- connection` green end to end before Task 2 started.

## Deviations from Plan

**1. [Plan-clarification] `styles.css` replaces `index.css`**
- **Found during:** Task 2. 01-09 created `index.css` as the Tailwind entry; the plan lists `styles.css`.
- **Fix:** `git mv index.css styles.css` and updated the single import in `main.tsx`; only one entry stylesheet exists. **Commit:** cf427d5

**2. [Rule 3 - Blocker] `hud/biome.json` gains `css.parser.tailwindDirectives: true`**
- **Issue:** Biome could not parse `@theme` and failed `lint` and `format`.
- **Fix:** enabled the Tailwind directive parser. **Commit:** cf427d5

**3. [Rule 3 - Blocker] `styles.css` opts out of Biome formatting (`biome-ignore-all format`)**
- **Issue:** Biome lowercases hex colors, but the plan's acceptance greps `--snow-bg: #0B0E14` verbatim and the UI-SPEC writes tokens uppercase.
- **Fix:** file-level format suppression with a stated reason; lint still runs on the file. **Commit:** cf427d5

**4. [Plan-clarification] No explicit `cmd.snapshot` after reconnect**
- The plan says "on success requests a fresh snapshot". `src/snow/hub/server.py` already queues a full snapshot as the first frame after every accepted hello, and `reduce` replaces the whole state from it, so a second request would only add a duplicate frame and a role-permission risk. Not implemented.

**5. [Plan-additive] `env.d.ts` moved the `window.snow` declaration out of `ws.ts`** (it was a `declare global` there), per the plan's file list; shipped with Task 1 because `ws.ts` depends on it. **Commit:** 2048f15

**6. [Plan-additive] A second e2e test in `connection.spec.ts`** exercising the CSP meta, a blocked `location.href` change and a denied `window.open`, so the lockdown is asserted rather than only grepped.

**7. `index.html` not modified:** it needed no change (the CSP is injected at build time).

**Total deviations:** 7 (2 blockers, 5 clarifications or additions). **Impact:** none on scope; no packages added.

## Issues Encountered
- The first Task 1 commit uses `text-(--snow-*)` classes before Task 2 defines the variables, so that intermediate commit renders with unresolved colors (functionally fine, e2e green). Task 2 closes it.
- Production CSP `style-src 'self'` blocks inline `style=` attributes. Nothing in the HUD uses them now; later plans (orb, cards) must use classes or CSS variables set via the CSSOM, not React `style` props.

## Known Stubs
- `App.tsx` still renders the plain row list; the full TranscriptView, orb, mute button and shared Banner arrive in plans 01-11, 01-19 and 01-21 as planned. The banner has no Mute button to disable yet.

## Threat Flags
None. T-01-09 mitigated (CSP, navigation and window.open locked, fonts local, transcript text only as React text nodes). T-01-SC: no packages added.

## Not run
- No live check against the real Python hub; the e2e uses the mock hub only, as instructed.

## Self-Check: PASSED
- Created and modified files exist (styles.css, env.d.ts, connection.spec.ts, ws.ts, App.tsx, main.tsx, main/index.ts, electron.vite.config.ts, biome.json); `index.css` removed.
- Commits `2048f15` and `cf427d5` are ancestors of HEAD; `git rev-list --count` from the plan base is 2.
- Acceptance: `--snow-bg: #0B0E14` and `--snow-state-muted: #F87171` in styles.css; `will-navigate` and `action: 'deny'` in main/index.ts; built index.html contains `connect-src ws://127.0.0.1:*`; `grep -rn fonts.googleapis hud/src` empty; App.tsx contains `Cannot reach Snow's core`.
