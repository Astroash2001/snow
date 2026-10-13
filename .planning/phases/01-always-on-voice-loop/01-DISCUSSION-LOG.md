# Phase 1: Always-On Voice Loop - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-14
**Phase:** 01-always-on-voice-loop
**Areas discussed:** Snow's persona & replies, Conversation flow, Phase-1 HUD window, Fallback voice & privacy

---

## Snow's persona & replies

| Option | Description | Selected |
|--------|-------------|----------|
| Jarvis-calm | Composed, warm, quietly witty, competent | |
| Friendly buddy | Casual, chatty, more jokes and slang | ✓ (then refined) |
| Crisp operator | Minimal words, no small talk | |

**User's choice:** First "Friendly buddy", then refined in free text: talk like Jarvis, natural tone, sarcastic humor in normal use. Confirmed the guardrail (sarcasm off on errors or stress). Address the user as "sir", as close to Jarvis as possible.
**Notes:** User offered YouTube links of Jarvis. Claude explained it cannot watch video; links can serve as voice-audition references.

| Option | Description | Selected |
|--------|-------------|----------|
| Short by default | 1-2 sentences unless asked | |
| Match the question | LLM judges length per turn | ✓ |
| Chatty | Longer, conversational replies | |

| Option | Description | Selected |
|--------|-------------|----------|
| Pick together later | Audition Cartesia voices | |
| Male voice | Shortlist male voices | ✓ |
| Female voice | Shortlist female voices | |

| Option | Description | Selected |
|--------|-------------|----------|
| Natural, mostly upbeat | Small validated emotion set, warm default | ✓ |
| Very expressive | Wide range, laughter tags | |
| Subtle | Near-neutral | |

---

## Conversation flow

| Option | Description | Selected |
|--------|-------------|----------|
| Wake once, stay in conversation | Listen until "that's all" or 30-60 s silence; optional always-listening mode later | ✓ |
| Same, no later mode | Never plan always-listening | |
| Always listening from day one | No wake word | |

**Notes:** User first asked for "all awake like Jarvis". Claude explained the TV, privacy and cost risks before speaker verification. User misread "ambient mode" as a visual effect and clarified the orb vision (recorded as a Phase 6 deferred decision). Question re-asked with clearer wording.

| Option | Description | Selected |
|--------|-------------|----------|
| Hold to talk | Hotkey held while speaking | |
| Tap toggle | Tap to start and stop | |
| Both | Short press toggle, long press hold | |

**User's choice:** No key at all; wake by name only. Asked Claude to act like Jarvis does when Tony calls him. VOIC-02 dropped from Phase 1.

| Option | Description | Selected |
|--------|-------------|----------|
| Soft chime + orb reacts | Non-speech earcon | |
| Visual only | Silent | |
| Spoken acknowledgement | Short LLM-written line | |

**User's choice (via Jarvis reference):** No chime. Wake plus command acts directly; wake alone gets a short spoken "Sir?"-style acknowledgement; orb reacts instantly.

| Option | Description | Selected |
|--------|-------------|----------|
| Voice to mute, click to unmute | Hard mute | |
| Soft sleep instead | Mic stays on, wake word only | |
| Both | Soft sleep by voice plus hard mute by click | ✓ |

---

## Phase-1 HUD window

**User's free-text direction:** Full Jarvis dashboard when the app is open. When minimized, nothing heavy runs in the background; a small version stays on screen so the user knows Snow is watching and active.

| Option | Description | Selected |
|--------|-------------|----------|
| Simple voice-reactive orb | Moves with both voices, color by state | ✓ |
| Status dot + text only | Nothing moves until Phase 6 | |

| Option | Description | Selected |
|--------|-------------|----------|
| Top-right corner, draggable | Always on top, click-through, click opens dashboard | ✓ |
| Bottom-right, above taskbar | Out of the way | |
| Top-center | Notch-style | |

| Option | Description | Selected |
|--------|-------------|----------|
| Chat-style, current conversation | Live partials, clears when conversation ends | ✓ |
| Only the latest exchange | Minimal | |
| Full scrolling history of the day | Pulls Phase 6 work forward | |

| Option | Description | Selected |
|--------|-------------|----------|
| Orb only, caption while awake | One-line caption that fades | ✓ |
| Orb only, always | No text | |

---

## Fallback voice & privacy

| Option | Description | Selected |
|--------|-------------|----------|
| Cartesia until credits run out | Auto-switch to local voice | ✓ |
| Budgeted Cartesia | Daily budget, split by line type | |
| Local by default | Cartesia on request | |

| Option | Description | Selected |
|--------|-------------|----------|
| Snow says it once + HUD shows it | In-character mention, HUD badge with credits | ✓ |
| HUD only | Silent switch | |
| Nothing | No indicator | |

| Option | Description | Selected |
|--------|-------------|----------|
| Text transcripts, no audio | Local text only | ✓ |
| Text + audio clips | Keep audio per turn | |
| Metadata only | No words | |

| Option | Description | Selected |
|--------|-------------|----------|
| 30 days, then auto-delete | Configurable | ✓ |
| Forever | Keep everything | |
| 7 days | Short window | |

---

## Claude's Discretion

- Recognition of "mute", "go to sleep" and "that's all" (recommended: deterministic local phrase match)
- Keeping the wake-alone acknowledgement LLM-written without added latency
- Exact silence timeout within 30-60 s, orb colors and motion, dashboard layout, mini indicator size
- How credit balance and voice status reach the HUD
- Storage of any wake-word or enrollment recordings (explicit user action only, local)

## Deferred Ideas

- Phase 6: orb reacts to both voices exactly like Age of Ultron Jarvis; no ambient lighting, all effects on the orb
- Optional always-listening mode after speaker verification
- Push-to-talk hotkey, only if the wake word proves unreliable
