---
phase: 01-always-on-voice-loop
plan: 19
subsystem: ui
tags: [electron, react, canvas-2d, glyph-atlas, orb, performance, playwright, hud]

requires:
  - phase: 01-15
    provides: reconnect and connection state, --snow-* tokens, production CSP (style-src 'self')
  - phase: 01-09
    provides: dashboard window, mock hub, e2e harness
provides:
  - Presence component { state, size, alert, fpsCap?, onClick? } and OrbRenderer, reusable at 40 px by plan 01-25
  - levels.ts mutable mic/tts ref written by ws.ts, bypassing the React store
  - window.__snowTest hook (freezeOrb, orbStats) and evt:/paint: perf marks, only under SNOW_HUD_TEST=1
  - perf.spec.ts proving event-to-paint, draw cost and the alert marker
affects: [01-21, 01-23, 01-25]

commits: 1
plan_head_before: a6661b264be7f3de4f010da2f9a5e79d0beb24a6
plan_head_after: 1483fcf69d9cca2570789fe278519773986340e4

actuals:
  tokens: 21000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Orb draws by blitting a pre-rendered OffscreenCanvas glyph atlas (row = glyph, column = brightness level x tint); the frame loop never lays out text"
    - "Canvas CSS size is set through the CSSOM (allowed by style-src 'self'); no style attributes, colors read from --snow-* tokens"
    - "Per-frame inputs that must not re-render React (audio levels) live in a module-level ref (levels.ts) read by the render loop"

key-files:
  created:
    - hud/src/renderer/src/orb/atlas.ts
    - hud/src/renderer/src/orb/sphere.ts
    - hud/src/renderer/src/orb/renderer.ts
    - hud/src/renderer/src/orb/smoother.ts
    - hud/src/renderer/src/orb/orb.test.ts
    - hud/src/renderer/src/components/Presence.tsx
    - hud/src/renderer/src/levels.ts
    - hud/e2e/perf.spec.ts
  modified:
    - hud/src/renderer/src/ws.ts
    - hud/src/renderer/src/App.tsx
    - hud/src/main/index.ts

key-decisions:
  - "The state change paints the new state at full strength on the next frame; the cross-fade is the OLD state fading out over it for 120 ms (a ghost at 60%), so the new hue is never delayed"
  - "Perf marks and the test hook are gated on ?snowtest=1, so a production run never accumulates performance marks"
  - "paint:<seq> is marked for every event that changed the state since the last paint, so an event coalesced into a later frame is measured, not lost"

requirements-completed: [HUD-03]

coverage:
  - id: D1
    description: "Orb event-to-paint at most 50 ms p95 and 100 ms max over 200 presence events, draw under 4 ms per frame at 192 px"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/perf.spec.ts (200 events at 100 ms: median 2.9 ms, p95 5.7 ms, max 16.3 ms, avg draw 2.0 ms)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Alert marker appears while a language-model role is failing and clears when it recovers"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/perf.spec.ts (health.role failing then active, read through window.__snowTest.orbStats)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Smoother attack/release, scale = 1 + 0.18 x level, +6% reduced-motion cap, deterministic sphere geometry"
    requirement: HUD-03
    verification:
      - kind: unit
        ref: "hud/src/renderer/src/orb/orb.test.ts (12 tests; 174 total pass)"
        status: pass
    human_judgment: false
  - id: D4
    description: "The orb looks like the ASCII network orb of the reference (glowing glyph sphere, cyan to violet) and not the rejected plain circle"
    requirement: HUD-03
    verification: []
    human_judgment: true
    rationale: "Visual likeness to refs/snow-vision-ascii-orb-dashboard.png is a judgment call. I viewed screenshots of every state; it reads as a glyph network but is smaller and sparser than the reference, which is a full-height hero orb"

duration: 55min
completed: 2026-10-17
status: complete
---

# Phase 1 Plan 19: ASCII Network Orb Summary

**The dashboard now has Snow's face: a Canvas 2D ASCII network orb (about 1,300 glyph points blitted from a pre-rendered atlas) with a distinct motion signature per state, level-driven swell read from a ref, an alert dot, and a Playwright proof that an event reaches the screen in a median 2.9 ms (p95 5.7 ms, max 16 ms)**

## Accomplishments
- **Orb (T1, tracer):** `sphere.ts` builds a seeded Fibonacci sphere (220 nodes at 192 px, 36 at 40 px), links each node to its 3 nearest neighbours, and places 2-4 line glyphs along every edge on the sphere surface. Nodes use single characters plus the odd fragment (`for`, `{}`, `=>`, `0x`, `json`, `fn`, `if`); lines use single characters only. `atlas.ts` renders every glyph once per (state hue, brightness 0-3, tint) with glow baked into the brightest levels, colors blending from the state hue toward violet by depth and near-white at the nodes, hues read from the `--snow-state-*` tokens. `renderer.ts` only calls `drawImage`; it contains no `fillText`.
- **States, readable without color:** sleeping = dim 45%, 6 s breathing, 15 fps; listening = cyan with an outer ring that expands with the mic level; thinking = violet 2.4 s pulse plus a rotating brightness gradient; speaking = pink with a soft inner glow and no ring; muted = static desaturated red with a mic-slash drawn as paths; offline = dashed outline, no fill. The 8 px alert dot sits on the top edge in every state.
- **Levels and motion:** `smoother.ts` (attack 40 ms, release 200 ms, `reset()`), scale `1 + 0.18 x level`; speaking to listening resets the smoother and skips the cross-fade. `ws.ts` writes `audio.level` into `levels.ts` and returns before the reducer, so the store never sees it. A level older than 200 ms reads as silence. Reduced motion stops breathing, pulse, rotation, flicker and caps the swell at +6%. The rAF loop is cancelled outright when the window is hidden.
- **Wiring:** `Presence.tsx` (button with `aria-label="Snow, {state word}"`, one canvas, props `{ state, size, alert }` plus optional `fpsCap` and `onClick`); `App.tsx` puts the 192 px orb in a Presence card above the state word, computes `alert` (any subsystem down or restarting, any role failing) and shows the offline style until the first snapshot and while the socket is down.
- **Test hook:** `hud/src/main/index.ts` appends `?snowtest=1` only when `SNOW_HUD_TEST=1`; the renderer then exposes `window.__snowTest` (`freezeOrb(seed)`, `orbStats()`) and writes `evt:<seq>` and `paint:<seq>` marks. Without the flag none of it exists (T-01-57).

## Measured numbers (this laptop, Electron 44, 192 px, DPR 1)
- Event to first painted change over 200 `presence.state` events at 100 ms intervals, five runs of the final code: median 2.6-3.8 ms, p95 5.5-8.5 ms, max 8.9-51 ms (budget: p95 <= 50, max <= 100). The measured span is event received in the renderer to the rAF callback that drew it; it does not include compositor scan-out.
- Average draw time per frame 1.3-3.1 ms, depending on machine load (budget: under 4 ms). It measures CPU time recording the drawing commands, not GPU raster time.
- Each run was 2,500-2,700 frames. Thresholds were not changed.

## Task Commits
1. **Task 1 (tracer): the ASCII network orb reacts to Snow's state and both voices within the latency budget** - `1483fcf` (feat)

Tracer gate: `test` (174 pass) and the full e2e (perf, smoke, connection: 4 pass) were re-run green after the commit.

## Deviations from Plan

**1. [Rule 1 - Bug] Perf marks lost when two state changes landed in one frame**
- **Found during:** Task 1 verification (one failed run: `paint mark for seq 1140` missing).
- **Issue:** a single pending-seq slot was overwritten when a later event arrived before the next frame, so the earlier event had no `paint:` mark.
- **Fix:** the renderer keeps a list of pending seqs and marks all of them in the frame that paints. **Commit:** 1483fcf

**2. [Rule 3 - Blocker] The perf test measured the desktop when its window was throttled**
- **Found during:** Task 1 verification. In about 1 of 4 runs the page's requestAnimationFrame dropped to exactly 1 Hz for the rest of the run (an independent probe saw 1000 ms gaps), putting p95 near 800 ms. This is Chromium throttling a window the OS reports as covered, not the orb.
- **Fix, in the test only:** Electron is launched with `--disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-features=CalculateNativeWinOcclusion`; an independent rAF probe records frame gaps over 150 ms; events whose interval overlaps a host stall are excluded and the count is printed, and the test still fails if more than 10% of events are excluded, so a stall cannot hide a broken orb. The shipped app is unchanged. After this, 8 consecutive runs passed with 0 events excluded except one run with 6.
- **Files modified:** hud/e2e/perf.spec.ts. **Commit:** 1483fcf

**3. [Plan-clarification] `paint:` marks use `useHud.getState().last_seq` read inside Presence**
- The plan says the renderer marks the seq it paints. `setState(state, seq)` receives the seq from Presence, which reads the store's `last_seq` only when `?snowtest=1` is set. No store changes.

**4. [Plan-additive] `Presence` has optional `fpsCap` and `onClick` props; `STATE_WORDS` (including "Reconnecting" for offline) moved from App.tsx into Presence.tsx and App imports it.**

**5. [Plan-additive] The backslash glyph is not in the set** (Biome flagged an escape; `|` stays).

**Total deviations:** 5 (1 bug, 1 blocker, 3 clarifications or additions). **Impact:** none on scope; no packages added.

## Issues Encountered
- The orb is smaller and sparser than the hero orb in `refs/snow-vision-ascii-orb-dashboard.png`: the UI-SPEC fixes the dashboard orb at 192 px and the plan fixes about 220 nodes, so the reference's density is not reachable at that size. I iterated on glyph size, depth dimming and node/line weighting until nodes and lines read as a network; the final likeness call is the human-check in the plan, still to be done. Screenshots of all states were inspected and are not committed.
- Not verified visually: the 40 px mini size (36 nodes, one-per-edge density is a guess) and DPR above 1 (atlas is built at `devicePixelRatio`; a DPR change while running, for example dragging between monitors, is not handled).
- The host-stall behaviour above means perf.spec.ts can still report an unusually busy machine honestly rather than pass silently.

## Known Stubs
- `Presence` accepts `onClick`, but `App.tsx` does not pass one: the UI-SPEC says the dashboard orb toggles hard mute, and the mute command plumbing and Mute button arrive in plan 01-21.
- `window.__snowTest.freezeOrb` is wired but its visual-regression consumer is plan 01-23.

## Threat Flags
None. T-01-57 mitigated: the hook exists only under `?snowtest=1`, which the main process adds only when `SNOW_HUD_TEST=1`; it can freeze the orb and read frame counters, holds no data and no IPC. T-01-SC: no packages added.

## Not run
- No live check against the real Python hub; the e2e uses the mock hub only, as instructed. The "say the wake phrase" human-check was not done.
- No reduced-motion or hidden-window run in Electron; both are covered by unit tests and code reading only.

## Self-Check: PASSED
- Created files exist: atlas.ts, sphere.ts, renderer.ts, smoother.ts, orb.test.ts, Presence.tsx, levels.ts, perf.spec.ts. Modified: ws.ts, App.tsx, main/index.ts.
- Commit `1483fcf` is an ancestor of HEAD; `git rev-list --count` from the plan base is 1.
- Acceptance: renderer.ts has `drawImage` and no `fillText`; levels.ts exists and store.ts has no `audio.level`; Presence.tsx has `aria-label` and the `alert` prop; main/index.ts has `SNOW_HUD_TEST`; perf.spec.ts passes with p95 <= 50 ms.
- Verification: `npm --prefix hud run lint`, `typecheck`, `test` (174 pass) and `e2e` (4 pass) green; `gen:types` leaves `src/generated` diff-clean; no raw hex in .tsx; no Electron processes left running.
