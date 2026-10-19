---
id: SEED-261019-mnj
status: dormant
planted: 2026-10-19
planted_during: Phase 01 (Always-On Voice Loop), plan 31/33
trigger_when: when planning Phase 2; again when planning Phases 3, 5 and 6
scope: medium
---

# SEED-261019-mnj: Ideas from the fullstack-agent gap study

The study compared Snow with jaredrhod/fullstack-agent (ai-memory-vault, backtalk, ai-visualizer and barehands). Those repos are AGPL-3.0, so take ideas only and never copy code. The full study is in [fullstack-agent-gap-study.md](./fullstack-agent-gap-study.md).

## Why This Matters

The study found two live Phase 1 bugs. It also found that long-term memory has no requirement ID and no phase, even though PROJECT.md promises replies built from "persona + situation + memory". The user chose to finish the current Phase 1 plan first and build these in later phases.

## When to Surface

**Trigger:** when planning Phase 2. Surface it again when planning Phases 3, 5 and 6.

## Items

1. **Bug (do early in Phase 2, or as a quick task):** after a barge-in, the brain keeps the full reply in its history. In `src/snow/brain/worker.py:292`, nothing listens for `reply.interrupted`. Trim the history to what was actually spoken.
2. **Bug (same timing):** there is no recovery from an audio device change. After a Bluetooth headset switch, Snow can stay deaf because PortAudio's device list is never refreshed. The fix:
   - restart the voice worker on a device change;
   - try an exact mic-name match first;
   - fall back to the WASAPI default.
3. **Long-term memory:** add a requirement ID and a phase for it.
   - Inject a short profile into every turn.
   - Snow updates that profile itself, with an audit trail and undo.
   - Write daily summaries.
   - Keep procedures that improve with each correction.
   - Markdown files are the source of truth, with an FTS5 index.
4. **Prompt rules:**
   - Put the current date and time in the prompt.
   - Never speak file paths or ids.
   - Speak numbers naturally.
   - Stop after asking a question.
5. **Lower other apps' audio:** turn other apps down while Snow listens and speaks, using pycaw, and restore them safely after a crash.
6. **Self-fix, before Claude Code edits Snow:**
   - a TROUBLESHOOTING.md written for Claude Code;
   - a "do not simplify" list in `.claude/CLAUDE.md`;
   - a `snow doctor` command.
7. **Phase 2:** guard the Claude Agent SDK against falling out of step after an interrupt (wait, interrupt, drain, rebuild). Flush speech before tool calls, so "on it" plays while the work runs.
8. **Phase 2, spoken approval rules:**
   - Code builds the summary, never the model.
   - Only an exact "yes" approves.
   - An answer counts only if it starts after the question.
9. **Phase 2, voice commands:** new chat, think harder, usage, and say that again. The replies stay LLM-written.
10. **Phase 3/6:** the brain puts things on the HUD in sync with speech and reads them back, through a fixed list of allowed commands.

**Skip:** webcam gestures, auto-approve, and push-to-talk as the default.

## Breadcrumbs

- `src/snow/brain/worker.py:292` (history.add with the full reply)
- `src/snow/brain/persona.py` (6-turn in-memory history)
- `src/snow/voice/sources.py` (`_wasapi_input`, MicSource reopen loop)
- `config/persona.toml` (prompt rules)
- `.planning/PROJECT.md` (memory promise)
