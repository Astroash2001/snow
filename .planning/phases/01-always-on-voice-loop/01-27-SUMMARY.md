---
phase: 01-always-on-voice-loop
plan: 27
subsystem: ui
tags: [electron, tray, single-instance, mini-indicator, drag, autostart, playwright, hud]

requires:
  - phase: 01-25
    provides: WindowManager, mini window, chrome bridge (drag, dragEnd, onCommand, sendState, setIcon)
  - phase: 01-14
    provides: hub passes --autostart and --restarted, handles cmd.app.quit
  - phase: 01-19
    provides: orb sphere, atlas tokens and hues
provides:
  - Tray with a tiny orb icon per state (16 and 32 px), tooltip "Snow: {state word}" plus " (attention)", menu Open Snow / Mute or Unmute microphone / Quit Snow
  - Mini orb right-click menu (same template)
  - Mini drag (4 px threshold), remembered position at <userData>/mini-position.json, clamped into a visible work area at start and on display changes, mirrored row on the left half
  - Single instance, --autostart and --restarted quiet start (mini only), clean Quit
  - renderOrbIcon(state, size, muted) for tray and window icons
affects: [01-31]

commits: 1
plan_head_before: ad9efa3def190a4b809927c91053f3ab5d5241df
plan_head_after: a159d968790cc1b02cc8998bdf546753ba728ee5

actuals:
  tokens: 14000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Tray, mini menu and quit never talk to the core: the dashboard renderer owns the one hub socket, main sends it chrome:command strings (mute, unmute, quit) and it emits cmd.mute.set (by tray) / cmd.app.quit"
    - "Main trusts nothing from renderers: chrome:state and chrome:icon are accepted only from the dashboard webContents and re-validated in main"
    - "Drag deltas are the pointer's total screen movement since the press, anchored on the window origin at the first message, so no message depends on the previous one; setBounds with fixed size (not setPosition) so mixed-DPI moves cannot stretch the window"
    - "Test hook globalThis.__snowChrome in main (SNOW_HUD_TEST=1 only) reads tray tooltip, menu template, icon fingerprint and clicks menu items without opening a native menu"

key-files:
  created:
    - hud/src/main/tray.ts
    - hud/src/main/position.ts
    - hud/src/main/position.test.ts
    - hud/src/renderer/src/orb/icon.ts
    - hud/e2e/windows.spec.ts
  modified:
    - hud/src/main/index.ts
    - hud/src/main/windows.ts
    - hud/src/preload/index.ts
    - hud/src/renderer/src/App.tsx
    - hud/src/renderer/src/components/MiniIndicator.tsx
    - hud/src/renderer/src/env.d.ts

key-decisions:
  - "The mirror side travels as chrome:command strings 'side:left' / 'side:right' over the existing onCommand bridge, so no new preload function was needed; the mini registers its listener at module load because the shell sends the first value at did-finish-load, before React mounts"
  - "Quit waits for the core to close the socket (or 3 s) after sending cmd.app.quit, then quits locally; offline it quits at once. The shell never relies on the hub killing it"
  - "In test mode userData defaults to a fixed temp scratch directory (and SNOW_HUD_USER_DATA overrides it), so tests never touch the real instance lock or the real mini position"
  - "Tray icon is drawn directly (nodes and a few line points of the sphere, slash when muted) rather than from the glyph atlas: glyphs are unreadable at 16 px"

requirements-completed: [VOIC-03, CORE-01]

coverage:
  - id: D1
    description: "Tray icon and window icons are tiny orb renderings in the current state hue; tooltip is 'Snow: {state word}' with ' (attention)' while a subsystem is Down; menu is Open Snow, Mute/Unmute microphone, separator, Quit Snow"
    requirement: VOIC-03
    verification:
      - kind: e2e
        ref: "hud/e2e/windows.spec.ts (tooltip, menu, orb icon and the confirmed mute label follow the core)"
        status: pass
      - kind: manual_procedural
        ref: "01-27-PLAN.md human-check: tray icon looks like an orb in the state color with a slash when muted; right-click menu"
        status: unknown
    human_judgment: true
    rationale: "Playwright cannot see the real notification-area icon or open the native tray menu; the icon's look at 16 px and the menu on screen need eyes"
  - id: D2
    description: "Mute from the tray or mini menu sends cmd.mute.set by 'tray'; the label and icon change only after mute.changed; mute is disabled offline"
    requirement: VOIC-03
    verification:
      - kind: e2e
        ref: "hud/e2e/windows.spec.ts (tooltip, menu, orb icon ...; with the core unreachable mute is disabled ...)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Under 4 px between press and release is a click that opens the dashboard; 4 px or more drags the mini, saves the position and never opens the dashboard"
    requirement: CORE-01
    verification:
      - kind: e2e
        ref: "hud/e2e/windows.spec.ts (a click under 4 px opens the dashboard; 4 px or more drags ...)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Saved position is clamped fully inside a display work area (pure function), snaps back when dropped past an edge, resets to the top-right when its display is gone, and is restored on the next launch; row mirrors on the left half"
    requirement: CORE-01
    verification:
      - kind: unit
        ref: "hud/src/main/position.test.ts"
        status: pass
      - kind: e2e
        ref: "hud/e2e/windows.spec.ts (dropped past a screen edge ...; the row mirrors ...; a saved position on a display that is gone ...)"
        status: pass
      - kind: manual_procedural
        ref: "01-27-PLAN.md human-check: unplug a second monitor, mixed-DPI crispness"
        status: unknown
    human_judgment: true
    rationale: "A real unplugged monitor and a mixed-DPI setup cannot be produced in CI; the clamp logic and a fake missing display id are tested, the OS behavior is not"
  - id: D5
    description: "--autostart and --restarted show only the mini; a manual launch shows the dashboard; a second launch exits and the first shows and focuses its dashboard"
    requirement: CORE-01
    verification:
      - kind: e2e
        ref: "hud/e2e/windows.spec.ts (launched with --autostart / --restarted ...; a manual launch ...; a second launch exits ...)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Quit Snow sends cmd.app.quit and the app exits; with the core unreachable it quits locally and at once"
    requirement: CORE-01
    verification:
      - kind: e2e
        ref: "hud/e2e/windows.spec.ts (Quit Snow sends cmd.app.quit ...; Quit Snow quits locally and at once ...)"
        status: pass
    human_judgment: false

duration: 70min
completed: 2026-10-17
status: complete
---

# Phase 1 Plan 27: Tray, mini drag, single instance, logon mode and quit Summary

**Snow now lives in the tray as a tiny state-colored ASCII orb (slashed when muted) with an Open / Mute / Quit menu, the mini orb drags and remembers a display-clamped position, a logon or restart launch shows only the mini, a second launch focuses the dashboard, and Quit sends cmd.app.quit then exits cleanly**

## Performance

- **Duration:** about 70 min
- **Tasks:** 1 (tracer)
- **Files modified:** 11 (5 created, 6 modified), all inside `hud/`

## Accomplishments
- **Tray (`tray.ts`):** tooltip `Snow: {state word}` plus ` (attention)`, left click opens the dashboard, one shared `menuTemplate` used by the tray and by the mini orb's native right-click menu. Mute/Unmute label and enabled state come from the confirmed state the dashboard renderer reports, so the label flips only after `mute.changed`; Mute is disabled while the core is unreachable, Quit never is.
- **Icons (`orb/icon.ts`):** `renderOrbIcon(state, size, muted)` draws the orb's nodes and near-side line points in the state hue (muted hue plus a dark-underlaid slash when muted, dashed outline when offline) on an OffscreenCanvas; the dashboard renderer sends 16 and 32 px on every state change, main builds a two-scale tray image and uses the 32 px for the window icons (D-31). I looked at the 32 px render: a cyan dotted sphere that reads as the orb.
- **Dashboard renderer as the only socket owner (`App.tsx` `useChromeBridge`):** sends `chrome.sendState` and icons, and turns `mute` / `unmute` / `quit` commands into `cmd.mute.set` (by `tray`) and `cmd.app.quit`. It keeps working while the dashboard is hidden or never shown.
- **Drag (`MiniIndicator.tsx`, `windows.ts`):** pointer-event click versus drag with a 4 px threshold on screen coordinates, no CSS drag region (`grep app-region hud/src` is empty). Main places the window with fixed-size `setBounds`, snaps it back inside the display it landed on at drag end, saves `{x, y, displayId}` to `mini-position.json`, and re-clamps on `display-removed` and `display-metrics-changed` (a missing saved display resets to the default top-right corner).
- **Mirror:** main tells the mini which half of its display it is on; on the left the row is `[orb][caption]`.
- **Launch modes (`index.ts`):** `requestSingleInstanceLock`, `second-instance` opens the dashboard, `--autostart` / `--restarted` create the dashboard hidden and the mini at launch.
- **Quit:** sends the command, then quits when the core closes the socket or after 3 s; offline it quits at once. The tray is destroyed on `will-quit`.
- **Verification:** `npm --prefix hud run test` 190 passed (position.test.ts adds 9), `lint`, `typecheck` clean, `gen:types` leaves `src/generated` unchanged, full `e2e` 54/54 including the unchanged `dashboard-12-turns-win32.png` baseline, the mini spec and the 12 new windows specs; no snapshot was regenerated. The mini caption fade spec did not flake in either full run.

Tracer gate: the full e2e suite was re-run end to end after the task and passed before returning (auto-mode path, no human gate on this tracer).

## Task Commits
1. **Task 1 (tracer): tray, menus, drag with remembered position, single instance, logon mode and quit** - `a159d96` (feat)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `online` added to `chrome.sendState`**
- **Found during:** Task 1 design
- **Issue:** the plan needs "Mute stays disabled" and "Quit quits locally when the hub is unreachable", but the 01-25 bridge only carried `{stateWord, muted, attention}`, so main could not know the socket was down.
- **Fix:** `sendState` takes a fourth boolean, `online`, validated in the preload and again in main. The bridge's function list is unchanged (the smoke spec's pinned list still passes).
- **Files modified:** `hud/src/preload/index.ts`, `hud/src/renderer/src/env.d.ts`

**2. [Rule 2 - Missing critical] Test isolation for user data**
- **Found during:** Task 1 design
- **Issue:** the single-instance lock and the saved mini position live in the Electron user-data directory; e2e runs would collide with a real Snow and with a position the user dragged.
- **Fix:** with `SNOW_HUD_TEST=1` main uses `SNOW_HUD_USER_DATA` if given, otherwise a fixed `%TEMP%\snow-hud-test-default`. Existing specs are unchanged and use the scratch directory; the new specs use their own temporary directories and remove them.
- **Files modified:** `hud/src/main/index.ts`

**3. [Rule 1 - Bug] Mirror side lost on a fresh launch (found by the new spec)**
- The shell sends the first `side:*` value at `did-finish-load`, which can arrive before React has mounted, so a `useEffect` listener missed it. The mini now registers its listener at module load and reads it with `useSyncExternalStore`.

### Plan-vs-implementation notes (no behavior change)
- `ws.ts` was not modified: `sendCommand` already existed and was enough. `hud/src/renderer/src/store.ts`, `styles.css` and `smoke.spec.ts` were not touched either.
- The mini's native right-click menu is wired through the page's `context-menu` event in main (no preload change); the e2e checks the same menu template through the test hook rather than popping a native menu up on the user's screen.

**Total deviations:** 3 auto-fixed (1 blocking, 1 missing critical, 1 bug). **Impact:** none on scope; all inside `hud/`.

## Issues Encountered
- Playwright pointer input cannot drive a window-drag deterministically (the pointer's screen position depends on where the window is), so the specs dispatch `PointerEvent`s in the mini page with chosen `screenX/screenY`; the real mouse path is in the pending human-check.
- `biome check --write` cannot run from the worktree root (a root biome.json exists); I ran it through a small scratch script with `cwd` set to `hud`. No file in the repo was added for this.
- No real login item was written: the shell never calls `setLoginItemSettings`, and the hub (plan 01-14) is the only thing that registers logon start. Nothing needed removing.

## Known Stubs
None.

## Pending human checks (not performed, per instructions)
- Tray icon is a tiny orb in the state color and shows a slash when muted; right-click shows Open Snow / Mute microphone / Quit Snow; left click opens the dashboard.
- Right-click the mini orb and confirm the native menu (the `context-menu` wiring is not exercised by e2e).
- Drag the mini orb to the left side of the screen (row mirrors), to a second monitor, unplug that monitor, and confirm the mini returns inside the visible screen; on a mixed-DPI setup the window stays crisp and inside the work area. Known limit: the tray image carries 16 px and 32 px, so 125% and 150% scaling interpolate (shortcut: add a 24 px rendition if it looks soft).
- Reboot or logon test that the hub-launched `--autostart` run shows only the mini.
- Real Quit with the real hub: confirm the hub exits cleanly and the HUD process does not respawn.

## Threat Flags
None beyond the plan's register: the new IPC (`mini:drag`, `mini:dragEnd`, `chrome:state`, `chrome:icon`, `chrome:command`) validates arguments in the preload and again in main, and each handler checks which window sent it (T-01-39 pattern); no packages were added (T-01-SC).

## Next Phase Readiness
Plan 01-31 can smoke the real hub with `--autostart`/`--restarted` and Quit. Two things to confirm there: the real hub broadcasts to two `hud` sockets (dashboard and mini), and that the hub does not respawn the HUD during its own shutdown after `cmd.app.quit` (the shell quits within 3 s of sending it, or sooner when the socket closes).

## Self-Check: PASSED
- Created files exist: tray.ts, position.ts, position.test.ts, orb/icon.ts, windows.spec.ts (FOUND)
- Commit a159d96 is on the branch; `git rev-list --count` from the plan base is 1
- Acceptance: tray.ts contains `Open Snow`, `Quit Snow`, ` (attention)`; index.ts contains `requestSingleInstanceLock` and `--autostart`; position.ts exports `clampToWorkArea`; `grep -rn "app-region" hud/src` returns nothing; position.test.ts and windows.spec.ts pass
