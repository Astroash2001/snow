---
phase: 01-always-on-voice-loop
plan: 21
subsystem: ui
tags: [electron, react, zustand, transcript, mute, copywriting, playwright, hud]

requires:
  - phase: 01-19
    provides: Presence orb component with onClick, STATE_WORDS, test hook
  - phase: 01-15
    provides: reconnect, connection-lost banner, --snow-* tokens, production CSP (style-src 'self')
  - phase: 01-20
    provides: hard mute semantics (mute.changed, presence muted, unmute only via cmd.mute.set)
provides:
  - TranscriptView (chat list, live partial row, interrupted chip, system rows, auto-follow, Jump to latest, end-of-conversation fade)
  - copy.ts with every Copywriting Contract string plus systemRowText() for llm.* rows
  - MuteButton and toggleMute() (confirmed-state only), shared Banner, EmptyState
  - sendCommand() in ws.ts (no-op offline)
  - store: ended and streaming flags, clearTranscript action, system rows for llm.switch/blocked_privacy/exhausted
affects: [01-23, 01-25]

commits: 2
plan_head_before: 579add4d2dc907a7c9575e2a7553db05695bf75e
plan_head_after: 657a5406e62820e2084941f7079ad77492ae4310

actuals:
  tokens: 21000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "System rows are stored as the hub's key=value facts (role=brain to=groq/m reason=rate_limit) with system_event=type; copy.ts turns facts into the sentence, so snapshot rows and live rows render identically"
    - "Controls never flip optimistically: toggleMute() sends cmd.mute.set with the inverse of the CONFIRMED muted flag; label, banner and orb read only hub-driven state"
    - "One frozen 16 px orb is painted once and copied onto every Snow row avatar (no atlas per row)"
    - "A conversation end is data (ended flag); the 2 s hold, 300 ms fade and the clear are timers in the view calling the clearTranscript action"

key-files:
  created:
    - hud/src/renderer/src/copy.ts
    - hud/src/renderer/src/copy.test.ts
    - hud/src/renderer/src/components/TranscriptView.tsx
    - hud/src/renderer/src/components/MuteButton.tsx
    - hud/src/renderer/src/components/Banner.tsx
    - hud/src/renderer/src/components/EmptyState.tsx
    - hud/e2e/transcript.spec.ts
    - hud/e2e/mute.spec.ts
  modified:
    - hud/src/renderer/src/store.ts
    - hud/src/renderer/src/store.test.ts
    - hud/src/renderer/src/ws.ts
    - hud/src/renderer/src/App.tsx
    - hud/src/renderer/src/styles.css

key-decisions:
  - "The hard-mute banner shows only while the core is online; offline the connection banner speaks and the HUD makes no claim about the mic (stale state could lie either way)"
  - "The Mute button is disabled whenever connection is not online, including before the first snapshot, so a command can never be sent before the hub has accepted the hello"
  - "The two banners carry no live role; the single visually hidden role=status region announces muted, unmuted, subsystem down, connection lost and Reconnected"
  - "A reply streaming in is marked aria-busy so the polite log does not announce half-written sentences"

requirements-completed: [VOIC-08, VOIC-03, CORE-10]

coverage:
  - id: D1
    description: "Live partial replaced wholesale in text-2 with accent underline and caret, becoming a text-colored final row; a turn with no speech leaves no partial and no row"
    requirement: VOIC-08
    verification:
      - kind: e2e
        ref: "hud/e2e/transcript.spec.ts (partial replaced then finalized; turn ending without speech)"
        status: pass
      - kind: unit
        ref: "hud/src/renderer/src/store.test.ts (a turn with no speech leaves no partial and no row)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Snow's row appears only with the first reply delta (no placeholder while thinking), grows, and an empty fallback final adds no row; interruption keeps heard text, dims it and adds the Interrupted chip"
    requirement: VOIC-08
    verification:
      - kind: e2e
        ref: "hud/e2e/transcript.spec.ts (first delta; silent fallback; interrupted reply)"
        status: pass
    human_judgment: false
  - id: D3
    description: "llm.switch, llm.blocked_privacy and llm.exhausted render as centered system rows with the documented copy (live and from a snapshot), never a modal"
    requirement: CORE-10
    verification:
      - kind: e2e
        ref: "hud/e2e/transcript.spec.ts (system rows; snapshot system rows)"
        status: pass
      - kind: unit
        ref: "hud/src/renderer/src/copy.test.ts (template, reason mapping incl. bad_key and config_error)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Scroll container follows within 24 px of the bottom; scrolling up pauses follow and shows Jump to latest, which resumes it; long text wraps; zero turns shows the empty state for standing by, asleep or muted"
    requirement: VOIC-08
    verification:
      - kind: e2e
        ref: "hud/e2e/transcript.spec.ts (scroll/jump; overflow-wrap anywhere; empty state by presence)"
        status: pass
    human_judgment: false
  - id: D5
    description: "After conversation.ended rows stay 2 s, fade over 300 ms, then the empty state shows; a new conversation inside the window clears at once and survives the old timers"
    requirement: VOIC-08
    verification:
      - kind: e2e
        ref: "hud/e2e/transcript.spec.ts (end-of-conversation fade; new conversation inside the window)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Hard mute is unmistakable (red banner with Unmute button, muted orb, label flip) and the control never lies: label, banner and orb change only on mute.changed; 120 ms pressed state; disabled offline"
    requirement: VOIC-03
    verification:
      - kind: e2e
        ref: "hud/e2e/mute.spec.ts (confirmed-state flow; banner and orb unmute; voice mute; offline; soft sleep)"
        status: pass
    human_judgment: false
  - id: D7
    description: "No transcript, reply or provider text is ever rendered as HTML"
    requirement: VOIC-08
    verification:
      - kind: e2e
        ref: "hud/e2e/transcript.spec.ts (literal characters test: <b>, <i>, <img onerror> render as text, zero such elements)"
        status: pass
      - kind: other
        ref: "grep -rn 'dangerouslySetInnerHTML|innerHTML' hud/src/renderer returns nothing"
        status: pass
    human_judgment: false
  - id: D8
    description: "The dashboard looks like the UI contract (card layout, spacing, bubble styling, banner tint, Snow avatar)"
    requirement: VOIC-08
    verification: []
    human_judgment: true
    rationale: "Behavior and computed colors are asserted, but I did not review screenshots of the new layout; the visual match to 01-UI-SPEC is a judgment call still to be made by the user"

duration: 50min
completed: 2026-10-17
status: complete
---

# Phase 1 Plan 21: Transcript, Mute Controls and Banners Summary

**The dashboard now shows the conversation the way the UI contract describes (live words, streamed replies, interruptions, provider-switch and error rows, a 2 s hold then fade on conversation end) and a mute control that never lies: label, red banner and muted orb change only when the hub's mute.changed arrives**

## Accomplishments
- **Transcript (T1, tracer):** `TranscriptView` renders user bubbles (right, `--snow-bg` fill, 1 px border, max 80%), Snow rows (left, 16 px orb avatar, "Snow" label), the partial row outside the `role="log"` region (text-2, accent underline and caret, replaced wholesale), the Interrupted chip with dimmed text, and centered system rows with an icon (`RotateCw` switch, `AlertTriangle` privacy hold, `XCircle` exhausted). Auto-follow within 24 px of the bottom, "Jump to latest" pill, timestamps on hover or focus-within, `overflow-wrap: anywhere`. Everything is a React text node.
- **Store:** `conversation.ended` no longer clears rows; it sets `ended` and the view runs the 2 s hold, 300 ms fade, then `clearTranscript()`. `conversation.started` still clears at once and flips `ended` back, which cancels the view's timers. A partial is dropped when presence leaves `listening`, on `turn.cancelled`, and on a blank final. `streaming` marks the Snow row still receiving deltas (`aria-busy`). `llm.*` events become system rows in the hub's key=value shape.
- **Copy:** `copy.ts` holds every Copywriting Contract string (including the voice, speech-to-text, credits, subsystem and not-configured lines that plan 01-23 will use) and `systemRowText()` builds the switch sentence, mapping `bad_key` and `config_error` to "service error" and looking up the provider's display label from health data (falling back to the id).
- **Mute (T2):** `MuteButton` (40 px, accent while live, alert while muted, 120 ms pressed state via `data-pressed`, disabled unless online), `toggleMute()` shared by the button, the banner button and the dashboard orb, `sendCommand()` in `ws.ts` (no-op unless the socket is open and has sent its hello), shared `Banner` (tint token `--snow-alert-tint`), `EmptyState` (standing by, asleep, muted), and the Asleep chip with the `Moon` icon in soft sleep.
- **Status region:** one `role="status"` region announces only muted, unmuted, subsystem down, connection lost and "Reconnected"; the first snapshot announces nothing.

## Task Commits
1. **Task 1 (tracer): transcript with system rows** - `6c8d9d2` (feat). Also carries Banner, EmptyState, MuteButton, `sendCommand` and the token, because the App wiring this task needs depends on them (see Deviations).
2. **Task 2: mute controls, banners, empty states** - `657a540` (test). The mute e2e spec; the components it covers landed in Task 1's commit.

Tracer gate: `e2e -- transcript` (11 pass) re-run green with the rest of the suite; full e2e is 20 passed (connection, smoke and perf included, perf median 3.0 ms, p95 5.8 ms). `lint`, `typecheck` and `test` (181) green; `gen:types` leaves no diff.

## Deviations from Plan

**1. [Plan-clarification] Task 2's components are in Task 1's commit**
- App.tsx has to render the Mute button, banners and empty state for the transcript e2e to run at all, so Banner, EmptyState, MuteButton, `sendCommand` and the `--snow-alert-tint` token were committed with Task 1. Task 2's commit holds only `mute.spec.ts` (which found no bugs; one test-timing fix, below).

**2. [Rule 2 - Missing critical functionality] Reducer changes the plan implies but does not spell out**
- The plan says to move the clear out of the reducer; doing so also required the `ended` flag, and "removed if the turn has no speech" required dropping the partial on presence change, `turn.cancelled` and a blank final. System rows for `llm.*` events had no reducer support at all, so they were added. The one existing store test that asserted rows were cleared by `conversation.ended` was rewritten for the new behavior. **Files:** store.ts, store.test.ts.

**3. [Plan-additive] `streaming` and `aria-busy`**
- The UI-SPEC says only finalized lines are announced; without a marker the polite log would re-announce a reply on every delta.

**4. [Plan-additive] `copy.test.ts`** covers the switch template and the reason mapping at unit level.

**5. [Plan-additive] The connection banner lost its `role="alert"`** when it moved onto the shared Banner, because the status region now announces "Connection to Snow's core lost" (as the UI-SPEC specifies) and both would double-announce. connection.spec still passes.

**6. [Plan-additive] The hard-mute banner is hidden while offline.** While the socket is down the HUD cannot know the mic state, so only the connection banner shows.

**7. [Test timing] The mute-colors assertion polls**, because the button colors transition over 120 ms and a single read caught the midpoint.

**8. Layout:** the Presence card is now a 320 px rail (was 256) beside the transcript card, per the UI-SPEC layout; Health and Voice cards are left to plan 01-23.

**Total deviations:** 8 (1 Rule 2, 7 clarifications or additions). **Impact:** none on scope; no packages added.

## Issues Encountered
- `biome check --write` cannot be run from the repo root (the root biome.json and hud/biome.json both claim to be roots), so formatting was applied by running biome with `hud` as its working directory; `npm run lint` is unaffected.
- Not verified: how the new dashboard layout looks (no screenshot review), the Windows high-contrast or forced-colors rendering of the banner tint, and the Snow avatar at DPR above 1.

## Known Stubs
None. `copy.ts` contains voice, speech-to-text, credits, subsystem and not-configured strings that no component uses yet; they are the Copywriting Contract for plan 01-23's Voice and Health cards, not placeholders.

## Threat Flags
None. No new endpoints, auth paths or schema changes; T-01-30 (confirmed-state mute) and T-01-31 (no HTML injection) are covered by e2e, T-01-SC by adding no packages.

## Self-Check: PASSED
- All 8 created files exist; commits 6c8d9d2 and 657a540 are ancestors of HEAD.
