---
phase: 01-always-on-voice-loop
plan: 23
subsystem: ui
tags: [electron, react, health, voice-card, status-chip, playwright, visual-regression, hud]

requires:
  - phase: 01-21
    provides: copy.ts contract strings, TranscriptView, MuteButton, Banner, store with health/voice/stt state
  - phase: 01-19
    provides: Presence orb, window.__snowTest.freezeOrb, orbStats
  - phase: 01-15
    provides: --snow-* tokens, production CSP (style-src 'self'), reconnect
  - phase: 01-22
    provides: stt.status (source, status_reason, retry_after_ns)
provides:
  - StatusChip (24 px icon plus text pill, 13 kinds, 120 ms fade on change)
  - HealthPanel (Subsystems and Language models, Checking slots, role disclosures with chains, providers-not-configured summary)
  - VoiceCard (voice and engine chip, Cartesia credits, speech-to-text source with documented helpers)
  - Final dashboard layout (left rail Presence then Voice, right column Transcript then Health, Tab order per contract)
  - health.spec.ts (16 tests) and visual.spec.ts with a committed Windows baseline
affects: [01-25, 01-31]

commits: 2
plan_head_before: 971844ea0d304ed531cb9724bc4aef4a95241cf0
plan_head_after: 6534efd7c724d2bd5d7d1a9ddc486d4888af7b26

actuals:
  tokens: 15000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "A status that changes remounts its chip (key = kind and label) and the snow-fade CSS class fades it in over the 120 ms token; rows never move, so nothing shifts"
    - "Health rows come only from the snapshot; the one fixed list is the five Checking placeholder names held before the first snapshot so the card keeps its size when data lands"
    - "DOM order is the Tab order; flex order classes put each block where the layout wants it"
    - "Visual baseline is made independent of Windows display scaling with --force-device-scale-factor=1 and a frozen orb on a fixed seed"

key-files:
  created:
    - hud/src/renderer/src/components/StatusChip.tsx
    - hud/src/renderer/src/components/HealthPanel.tsx
    - hud/src/renderer/src/components/VoiceCard.tsx
    - hud/e2e/health.spec.ts
    - hud/e2e/visual.spec.ts
    - hud/e2e/visual.spec.ts-snapshots/dashboard-12-turns-win32.png
  modified:
    - hud/src/renderer/src/App.tsx
    - hud/src/renderer/src/copy.ts
    - hud/src/renderer/src/styles.css

key-decisions:
  - "Credits warn threshold is 2,000 (10% of the 20,000-credit Free plan) as a documented shortcut; until plan 01-31 confirms a balance source credits_remaining is null and the card says Unavailable"
  - "Down and Restarting helper is the supervisor's own detail when it sent one, else the contract line (Restarting: automatic restart; Down: could not restart)"
  - "The helper 'No key stored. Run `snow setup` to add one.' renders snow setup in a code element, so the on-screen text has no backticks"
  - "The visual baseline replays the fixture without its last two events (conversation.ended and the drop to sleeping), whose 2 s hold and fade would race the screenshot"

requirements-completed: [QUAL-03, CORE-10, HUD-03]

coverage:
  - id: D1
    description: "Subsystem rows render from the snapshot with Running, Starting, Restarting and Down chips; Down and Restarting show their chip plus helper line; deltas update in place without reordering"
    requirement: QUAL-03
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (subsystem rows from the snapshot; a delta updates the chip in place)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Three collapsed role rows show the active provider / model (mono, accent dot, ellipsis, full value in title) and the documented chips; expanding lists the ordered chain with per-entry chips and the not-configured helper"
    requirement: CORE-10
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (collapsed role rows and chain; remaining role chips; model IDs mono and ellipsis)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Unknown health renders the Checking chip in place before the first snapshot and the snapshot lands with no layout shift; zero subsystems reads No health data yet; a role missing from the snapshot reads Checking"
    requirement: QUAL-03
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (before the first snapshot ... without a shift; zero subsystems; role not carried yet)"
        status: pass
    human_judgment: false
  - id: D4
    description: "'{n} of 5 providers not configured' hides at zero and keeps its wording at one; the Health card grows to natural height; below 880 px the columns stack"
    requirement: QUAL-03
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (providers summary; below 880 px the two columns stack)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Voice card: active voice with chip, credits in mono tabular with thousands separators and warn under 2,000, speech-to-text source with Primary or Fallback; Checking before the first voice.status or stt.status; Unavailable with its helper on a null balance"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (Voice card Checking; active voice and credits; missing balance)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Cartesia out of credits or unreachable, and Groq speech-to-text unreachable or rate limited, each show the documented helper line; a long voice name is one line with end ellipsis and the full name in title"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (missing balance and helpers; speech-to-text fallback; long voice name)"
        status: pass
    human_judgment: false
  - id: D7
    description: "Tab visits Mute, the orb, the three role disclosures, then Jump to latest, with a visible focus ring on each stop"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/health.spec.ts (Tab visits Mute, the orb, the role disclosures, then Jump to latest)"
        status: pass
    human_judgment: false
  - id: D8
    description: "A screenshot of the dashboard replaying the 12-turn fixture (user, Snow, interrupted and system rows, Jump to latest pill) matches the committed baseline; stable across repeated runs"
    requirement: HUD-03
    verification:
      - kind: e2e
        ref: "hud/e2e/visual.spec.ts (dashboard-12-turns-win32.png, maxDiffPixelRatio 0.01); run three times, green each time"
        status: pass
    human_judgment: true
    rationale: "The test proves the dashboard has not changed since the baseline, not that the baseline matches 01-UI-SPEC. I viewed the image and it follows the contract, but the visual sign-off is the user's call; one visible compromise is that the Brain model text truncates to 'Googl...' beside the long 'Fallback in use (2 of 4)' chip (full value in title)"

duration: 50min
completed: 2026-10-17
status: complete
---

# Phase 1 Plan 23: Health, Voice Card and Visual Baseline Summary

**The dashboard is complete: subsystem and per-role language-model health, the Voice card (voice, Cartesia credits, speech-to-text source) and the final two-column layout render live from the hub snapshot with icon-plus-text chips, and a deterministic 12-turn screenshot baseline locks the look**

## Accomplishments
- **StatusChip (tracer, T1):** 24 px pill with a 16 px lucide icon (stroke 1.75) and a text label for every status (Running, Starting, Restarting, Down, Active, Ready, Fallback in use, Cooling down, Failing, Not configured, Not used yet, Checking, plus a neutral kind for Everyday / Primary). Only the icon takes the status hue where the label would lose contrast. A changed status remounts the chip and `snow-fade` (styles.css, 120 ms, off under reduced motion) fades it in place.
- **HealthPanel (T1):** Subsystems and Language models columns (`2fr / 3fr` from 880 px, stacked below). Subsystem rows follow the snapshot's own order and labels; Down and Restarting add a helper line. Before the first snapshot five Checking slots (the contract's Phase 1 set) hold the card's size; with zero subsystems after the snapshot it reads "No health data yet". Three role rows (Brain, Fast, Vision) are `aria-expanded` disclosures, collapsed by default: role, accent dot, `provider / model` in JetBrains Mono (ellipsis, title, selectable), chip from `health.role.status`; expanding lists the ordered chain with per-entry chips and the not-configured helper. "{n} of 5 providers not configured" comes from `health.provider` statuses and hides at zero; its slot is reserved so the card does not jump.
- **VoiceCard (T2):** three rows. Voice: engine (Pocket TTS, Cartesia, Chatterbox, Kokoro) plus voice name on one line, chip Everyday, Big moment, GPU or Fallback (Kokoro only). Cartesia credits: mono, `tabular-nums`, `en-US` thousands separators, warn colour under 2,000; "Unavailable" with "Cartesia did not report a balance." on a null balance; the out-of-credits and unreachable helpers. Speech-to-text: "Groq cloud" (Primary) or "Local (Moonshine)" (Fallback, warn) with the unreachable helper or the limit helper with a local HH:MM from `retry_after_ns`. Checking before the first `voice.status` / `stt.status`.
- **Layout (T2):** left rail 320 px (Presence card above the Voice card), right column Transcript (flex, min 240) above the Health card (natural height). DOM order is Mute, orb, role disclosures, Transcript, with flex `order` placing the cards; Tab therefore visits Mute, orb, the three disclosures, then Jump to latest.
- **Tests:** `health.spec.ts` has 16 tests (Checking-then-snapshot layout comparison, every chip, helpers, in-place deltas, disclosures, summary at 0/1/2, mono and ellipsis, stacking, Voice card states, STT fallback, long voice name, Tab order and focus ring). `visual.spec.ts` replays `conversation-12.jsonl` against the mock hub at 960x640 and compares to `hud/e2e/visual.spec.ts-snapshots/dashboard-12-turns-win32.png` (the default template wrote exactly the path the plan names).
- **Verification:** the full e2e suite (37 tests: connection, health, mute, perf, smoke, transcript, visual) passes; health and visual ran green three times in a row. `npm --prefix hud run lint`, `typecheck` and `test` (181 tests) pass; `gen:types` leaves no diff.

## Task Commits
1. **Task 1 (tracer): health from the snapshot** - `153eb54` (feat)
2. **Task 2: Voice card, layout, visual baseline** - `6534efd` (feat)

Tracer gate: `health` was re-run end to end after Task 1 and passed before expansion (auto mode path, no human gate on this tracer).

## Files Created/Modified
- `hud/src/renderer/src/components/StatusChip.tsx`, `HealthPanel.tsx`, `VoiceCard.tsx` - new components
- `hud/src/renderer/src/App.tsx` - two-column layout, Voice and Health cards, Tab order
- `hud/src/renderer/src/copy.ts` - health, chip and voice-card strings, `clockTime()`
- `hud/src/renderer/src/styles.css` - `snow-fade`
- `hud/e2e/health.spec.ts`, `hud/e2e/visual.spec.ts`, `hud/e2e/visual.spec.ts-snapshots/dashboard-12-turns-win32.png`

## Decisions Made
See `key-decisions` above. Planner assumption kept: until plan 01-31 confirms a Cartesia balance source, a null balance shows "Unavailable" and the helper; the 2,000 warn threshold is a flagged shortcut (`shortcut:` comment in VoiceCard.tsx) to revisit if 01-31 exposes the plan size.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] New strings went into copy.ts, which the plan does not list**
- **Found during:** Task 1
- **Issue:** copy.ts's own contract is "components write no copy inline"; the chip labels, section titles, "Checking" and "No health data yet" were not in it.
- **Fix:** added `copy.health`, `copy.chip`, `copy.voiceCard` and a `clockTime()` helper (also stays inside hud/).
- **Files modified:** `hud/src/renderer/src/copy.ts`
- **Commit:** 153eb54

**2. [Rule 2 - Missing critical] Tab order needed DOM reordering**
- **Found during:** Task 2
- **Issue:** with the orb above the Mute button and the Transcript above the Health card, natural DOM order tabbed orb, Mute, Jump to latest, role disclosures; the contract fixes Mute, orb, role disclosures, Jump.
- **Fix:** Mute first in the DOM and Health before Transcript, with flex `order` classes for the visual layout; a Tab test pins the sequence. Chromium also makes the scrolled transcript itself a Tab stop (between the disclosures and Jump to latest), which is kept so the keyboard can scroll the list.
- **Files modified:** `hud/src/renderer/src/App.tsx`, `hud/e2e/health.spec.ts`
- **Commit:** 6534efd

**3. [Rule 1 - Bug] Test-only adjustments found while running**
- A first layout probe matched the nested `role-active` span as a role row; the selector now names the three role rows. The stacking test uses 900 and 860 px content widths instead of 880 and 879: Chromium snaps fractional DPR widths, so the boundary pixel is not a stable assertion. The focus-ring test compares ring width to offset rather than `2px` because the computed width scales with the display (1.6 px at 125%).
- **Commit:** 153eb54, 6534efd

### Design choices worth knowing
- The visual replay stops before the fixture's last two events (`conversation.ended`, sleeping): the 2 s hold and 300 ms fade would race the screenshot. After the replay the list is scrolled to the interrupted reply so the picture contains the interrupted row, the provider-switch system row and the Jump to latest pill.
- `--force-device-scale-factor=1` is passed in the visual test so the baseline does not depend on Windows display scaling (this machine is at 125%). The baseline is Windows only, as the file name says.
- The pre-snapshot Checking test closes the mock hub, launches the HUD, then restarts the hub on the same port, so the HUD genuinely has no snapshot until its reconnect lands (the mock hub always answers hello with a snapshot).

**Total deviations:** 3 auto-fixed (1 blocking, 1 missing-critical, 1 test-only bug). **Impact:** none on scope; all inside hud/.

## Known Stubs
None. Credits show "Unavailable" until a balance arrives; that is data-driven behavior the plan specifies, not a stub.

## Issues Encountered
- On the default 960x640 window the Brain row's model text truncates ("Googl...") when the role is in fallback, because the "Fallback in use (2 of 4)" chip takes about 170 px of a roughly 320 px column. The full value is in `title` and selectable per contract; if the user wants the provider always readable the chip text or column split needs a design call.

## Threat Flags
None. The HUD still receives only provider labels and model IDs (T-01-32); no packages were added (T-01-SC).

## Next Phase Readiness
Dashboard complete for Phase 1. Plan 01-25 can build on the final layout; plan 01-31 will turn the credits "Unavailable" assumption into real balances.

## Self-Check: PASSED
- Created files exist: StatusChip.tsx, HealthPanel.tsx, VoiceCard.tsx, health.spec.ts, visual.spec.ts, dashboard-12-turns-win32.png (FOUND)
- Commits 153eb54 and 6534efd are on the branch; `git rev-list --count` from the plan base is 2
- Acceptance greps: HealthPanel.tsx has `aria-expanded` and `providers not configured`; VoiceCard.tsx has `tabular-nums` and `Local (Moonshine)`; StatusChip renders an icon and a label for every kind
- Plan verification: full e2e 37/37, lint, typecheck, vitest 181/181, gen:types clean
