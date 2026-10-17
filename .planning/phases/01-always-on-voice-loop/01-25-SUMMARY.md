---
phase: 01-always-on-voice-loop
plan: 25
subsystem: ui
tags: [electron, window-model, mini-indicator, click-through, react, playwright, hud]

requires:
  - phase: 01-23
    provides: final dashboard layout, visual baseline, StatusChip/Health/Voice cards
  - phase: 01-21
    provides: copy.ts strings, mute and banners
  - phase: 01-19
    provides: Presence orb (size, fpsCap, alert), window.__snowTest hook
  - phase: 01-15
    provides: production CSP, token styling, connectHub
provides:
  - WindowManager (dashboard and mini lifecycle, close/minimize hide, openDashboard, hideDashboard, showMini)
  - Frameless transparent floating non-focusable 320x56 mini window, click-through except the hovered orb
  - MiniIndicator (40 px orb at 30 fps, live caption pill, persistent Muted pill, alert dot, offline style)
  - Hidden-dashboard render budget (renders nothing while hidden, asks cmd.snapshot on show)
  - window.snow.chrome bridge (hover, click, drag, dragEnd, onVisibility, onCommand, sendState, setIcon) with validated arguments
  - mini.html second renderer entry with the same CSP
affects: [01-27, 01-31]

commits: 1
plan_head_before: e0bc743454ed56360ed99c7f0aa48ae2d4cd1fe7
plan_head_after: 14905bf18ec41ce42e5c9a249328a358b8af6e91

actuals:
  tokens: 8000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "The mini window is created the first time it is needed and then kept (hidden, not destroyed); a hidden window's renderer does no frame work because the orb loop stops on visibilitychange"
    - "Chrome-only IPC: preload validates every argument, main checks the sender is the mini webContents for mini:hover and mini:click"
    - "Caption comes from live store transitions only (partial, then a changed last user row while online both before and after), so the snapshot that brings the window online is never captioned"
    - "Click-through is verified in e2e by wrapping BrowserWindow.prototype.setIgnoreMouseEvents before the mini window exists"

key-files:
  created:
    - hud/src/main/windows.ts
    - hud/src/renderer/mini.html
    - hud/src/renderer/src/mini.tsx
    - hud/src/renderer/src/components/MiniIndicator.tsx
    - hud/e2e/mini.spec.ts
  modified:
    - hud/electron.vite.config.ts
    - hud/src/main/index.ts
    - hud/src/preload/index.ts
    - hud/src/renderer/src/App.tsx
    - hud/src/renderer/src/env.d.ts
    - hud/src/renderer/src/store.ts
    - hud/src/renderer/src/styles.css
    - hud/e2e/smoke.spec.ts

key-decisions:
  - "Mini window is created lazily on first need (not at startup): zero idle cost, and the dashboard stays the first window so existing specs' firstWindow() is unchanged"
  - "The dashboard renderer starts visible and is told false only on hide (and again on did-finish-load if it loads while hidden); using isVisible() at load time wrongly hid it because ready-to-show comes later"
  - "selectAlert lives in store.ts and is used by both App and MiniIndicator so the two orbs can never disagree"
  - "Muted pill is claimed only while the core confirms mute (connection online), same rule as the dashboard banner"

patterns-established:
  - "Transparent window pages use body.snow-mini in unlayered CSS to beat Tailwind's layered utilities"

requirements-completed: [HUD-03, VOIC-03]

coverage:
  - id: D1
    description: "Closing or minimizing the dashboard hides it and shows the mini; clicking the mini orb restores the dashboard (fresh cmd.snapshot) and hides the mini; never both visible"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (closing the dashboard shows the mini orb ...)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Hidden dashboard renders nothing (no orb canvas, transcript or state word) and orb loop is stopped"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (closing the dashboard shows the mini orb ...)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Mini window is frameless, transparent, always-on-top floating, non-focusable, 320x56 at the top-right of the primary work area; click-through at creation, off while the orb is hovered, on again at leave and at hide"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (closing the dashboard shows the mini orb ...; setIgnoreMouseEvents calls recorded)"
        status: pass
      - kind: manual_procedural
        ref: "01-25-PLAN.md human-check: real mouse clicks on the empty area and caption reach the window underneath"
        status: unknown
    human_judgment: true
    rationale: "Playwright dispatches pointer events through CDP, which bypass the OS ignore-mouse-events state, so real click-through under a physical mouse can only be proven by hand"
  - id: D4
    description: "Caption shows the user's words (partial then final), 120 ms in, holds 2.5 s, 400 ms out, single line max 256 px, 32 px high, left mask on overflow, window never resizes, never shown while sleeping"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (the mini caption shows what Snow heard ...)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Hard mute shows a persistent Muted pill and the muted orb in the mini form; a caption never replaces it"
    requirement: VOIC-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (hard mute shows a persistent Muted pill ...)"
        status: pass
    human_judgment: false
  - id: D6
    description: "A Down or Restarting subsystem (or Failing role) draws the 8 px alert dot on the mini orb until healthy"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (a Down subsystem draws the alert dot ...)"
        status: pass
    human_judgment: false
  - id: D7
    description: "Before the first snapshot and after the socket drops the mini orb is offline with no caption; the snapshot on reconnect captions nothing"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mini.spec.ts (until the first snapshot and after the socket drops ...)"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-10-17
status: complete
---

# Phase 1 Plan 25: Mini indicator and two-form window model Summary

**Closing or minimizing the dashboard now leaves a 40 px ASCII orb in the top-right corner (frameless, transparent, floating, non-focusable, click-through except the hovered orb) with a live caption, a persistent Muted pill and the alert dot; clicking the orb brings the dashboard back with a fresh snapshot**

## Accomplishments
- **WindowManager (`hud/src/main/windows.ts`):** dashboard `close` is prevented and `minimize` handled, both hide the dashboard and show the mini; `openDashboard()` shows, restores and focuses the dashboard and hides the mini (click-through is reset first, because a hidden window gets no pointerleave). `before-quit` lets a real quit through. Mini is `frame:false`, `transparent`, `alwaysOnTop` then `setAlwaysOnTop(true,'floating')`, `skipTaskbar`, `focusable:false`, `resizable:false`, 320x56, top-right of the primary work area with 16 px margins, shown with `showInactive()`, `setIgnoreMouseEvents(true, { forward: true })` at creation. IPC `mini:hover` and `mini:click` are accepted only from the mini's webContents and only with a boolean or no argument.
- **Preload `chrome` bridge:** `hover`, `click`, `drag`, `dragEnd`, `onVisibility`, `onCommand`, `sendState`, `setIcon` with finite-number, boolean, length-capped string and PNG data-URL validation. This plan wires `hover`, `click`, `onVisibility` in main and renderer; plan 01-27 adds main handlers for the rest without touching the bridge (channels `mini:drag`, `mini:dragEnd`, `chrome:command`, `chrome:state`, `chrome:icon`).
- **MiniIndicator:** `[caption pill][orb 40]` with the orb at the right (screen-side) edge, `Presence` at size 40 and `fpsCap` 30, the shared alert value, offline orb until the first snapshot and while the socket is down. Caption follows the UI-SPEC: first partial fades in 120 ms, updates in place, 2.5 s hold after the final, 400 ms fade then removed from the DOM, never while sleeping, single line, 256 px max, 32 px high, `px-4 py-2`, newest words visible with a 24 px left mask applied only when the text overflows. Muted pill replaces the caption while the core confirms hard mute.
- **Hidden dashboard budget:** `App` renders nothing while hidden (orb loop stops, transcript and health trees unmount); on show it sends `cmd.snapshot`.
- **mini.html** is a second renderer input in `electron.vite.config.ts`; the build-only CSP plugin covers it (verified in `out/renderer/mini.html`), and it has the same navigation and `window.open` lockdown as the dashboard.
- **Verification:** `npm --prefix hud run e2e` 42/42 (including the 12-turn visual baseline, unchanged, and `perf` at median 3.2 ms event to paint), `lint`, `typecheck` and `test` (181) pass, `gen:types` leaves no diff, no Electron processes left running. I viewed a screenshot of the mini page (caption pill plus 40 px orb on a transparent background).

Tracer gate: the full e2e suite was re-run end to end after the task and passed before any expansion (auto mode path, no human gate on this tracer).

## Task Commits
1. **Task 1 (tracer): two-form window model with click-through mini indicator** - `14905bf` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `hud/e2e/smoke.spec.ts` asserted the bridge was only `["hubInfo"]`**
- **Found during:** full e2e run
- **Fix:** the assertion now pins the new bridge shape (`hubInfo`, `chrome`) and the exact list of eight chrome functions, so any future addition is a visible, deliberate change.
- **Commit:** 14905bf

**2. [Rule 1 - Bug] Dashboard rendered nothing at startup**
- **Found during:** first full e2e run (37 failures)
- **Issue:** `did-finish-load` told the renderer `isVisible()`, which is false until `ready-to-show`, so the dashboard hid itself.
- **Fix:** main tracks `dashboardHidden` and only re-sends `false` when the dashboard really was hidden.
- **Commit:** 14905bf (found and fixed before the commit)

**3. [Rule 3 - Blocking] Files outside the plan's `files_modified`**
- `store.ts` gained `selectAlert` (shared by both orbs, replacing the inline computation in `App.tsx`), `styles.css` gained `body.snow-mini` (transparent background), `env.d.ts` the bridge types, and `smoke.spec.ts` as above. All inside `hud/`.

### Design choices worth knowing
- The mini window is created lazily rather than at startup. First show after a close therefore includes one page load (a few hundred ms); plan 01-27's `--autostart` path will create it at launch.
- The mini opens its own hub connection (role hud), so the hub sees two HUD clients while both pages exist. The mock hub accepts that; the real hub is untested with two HUD sockets in this plan (see Next Phase Readiness).

**Total deviations:** 3 auto-fixed. **Impact:** none on scope; all inside `hud/`.

## Known Stubs
None. `drag`, `dragEnd`, `onCommand`, `sendState` and `setIcon` exist in the bridge but have no main-process handler yet by design (plan 01-27); sending to them is a no-op.

## Issues Encountered
- Not verified: real-mouse click-through (Playwright bypasses the OS ignore state), `forward: true` delivering `pointerenter` from a physical mouse on Windows, behavior over a fullscreen game, and mixed-DPI or multi-monitor placement. The plan's human-check covers the first; the 40 px orb's look was checked only on a screenshot at the default display scale.
- The 40 px orb (36 nodes) reads as a small dense cluster in the screenshot; it is the 01-19 renderer unchanged, and a density tweak, if wanted, belongs there.

## Threat Flags
None. New IPC channels are mitigated as T-01-39 describes (named functions, validated arguments, sender check in main); the mini uses `focusable:false`, click-through and the floating level (T-01-41); no packages were added (T-01-SC).

## Next Phase Readiness
Plan 01-27 can add tray, drag, menus and the launch flags on `WindowManager` without editing the preload bridge. Before relying on two HUD sockets in the real run, confirm the real hub broadcasts to multiple `hud` clients (plan 01-31 smoke).

## Self-Check: PASSED
- Created files exist: windows.ts, mini.html, mini.tsx, MiniIndicator.tsx, mini.spec.ts (FOUND)
- Commit 14905bf is on the branch; `git rev-list --count` from the plan base is 1
- Acceptance greps: windows.ts has `setIgnoreMouseEvents(true, { forward: true })`, `'floating'`, `focusable: false`; `electron.vite.config.ts` lists `mini.html`; mini.spec.ts passes (5/5)
