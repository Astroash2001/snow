# Gap study: jaredrhod/fullstack-agent vs Snow

Date: 2026-10-19. Method: shallow clones of all five repos (fullstack-agent, ai-memory-vault, backtalk, ai-visualizer, barehands), read only and never run. I read every code file except the 3,157-line `barehands/stage.html` (grepped) and the face HTML files (grepped for state handling). On the Snow side I read the planning set (PROJECT, ROADMAP, REQUIREMENTS, STATE, the Phase 1 CONTEXT, research ARCHITECTURE) and the relevant code under `src/snow/` and `hud/src/`.

Licence note: everything they ship is AGPL-3.0. This study takes only ideas and techniques. Every "implementation idea" below is our own design for Snow's stack, and none of it copies their code.

---

## 0. TL;DR

- **The one big hole is memory.** Snow has no long-term memory requirement at all. There is no REQ-ID and no roadmap phase for it. Research `ARCHITECTURE.md` drew a Memory Store, but it was lost on the way into REQUIREMENTS and ROADMAP. Today the brain keeps 6 turns in RAM (`src/snow/brain/persona.py` `History`). ai-memory-vault is a full, thought-through memory *design*: a two-layer boot, a living profile with edit permissions, daily episodes, a single priorities queue, and "Jobs" (procedures that improve with each correction). Snow should take that design.
- **backtalk is a field manual for Snow's Phase 2.** It drives Claude Code through the same Agent SDK Snow will use. It documents a stream-desync bug after interrupts, the pre-tool filler flush, live permission-mode limits, and a fully worked spoken-approval UX: plain words built by code, "details" on request, an exact-match yes, deny-with-reason, and answer routing by speech start time. Each of these will cost days to rediscover.
- **Product polish Snow lacks.** Every repo has a TROUBLESHOOTING.md written *for the agent*, a "land mines, do not simplify" list, and a rule that the agent is the mechanic. Snow is about to have Claude Code edit Snow (dogfooding from Phase 2), and it has no README, no troubleshooting doc and no doctor command.
- **Small Phase 1 bugs and gaps found by comparison:**
  - Brain history keeps the full reply after a barge-in, even the words the user never heard.
  - The prompt has no date or time.
  - File paths would be spoken aloud.
  - PortAudio is never re-initialised after a device change, so Snow can go permanently deaf after a Bluetooth headset switch.
  - Other apps' audio is not ducked.
  - The orb level uses a fixed dB scale, so the user's quiet mic barely moves it.
- **Skip:** barehands' webcam gestures, auto-approve, the file-based signal bus, a hard Obsidian dependency, push-to-talk as the default, and the macOS-only bits.

---

## 1. What the target actually is

| Repo | What it is (in their words, verified in code) | Key files |
|---|---|---|
| fullstack-agent | A Claude-Code *conversation* as the installer. It interviews once, runs each piece's wizard with the answers pre-filled, wires config paths, makes desktop shortcuts and says the first hello. It has no runtime code beyond the launch and update scripts. | `fullstack-agent.md` (the wizard), `CLAUDE.md` (installer persona), `start.bat/.sh`, `update.sh`, `TROUBLESHOOTING.md` |
| ai-memory-vault | Pure instructions, no code. The agent builds an Obsidian vault of markdown that serves as its memory, plus a boot `CLAUDE.md` with identity and rules. | `ai-memory-vault.md` (860-line builder), `templates/CLAUDE.md`, `templates/VAULT-INDEX.md`, `templates/DAILY-NOTE.md`, `templates/MEMORY.md` |
| backtalk | A Python voice loop: push-to-talk → local faster-whisper → a warm `ClaudeSDKClient` session in the agent's folder → Kokoro or ElevenLabs TTS. It adds spoken permission prompts, a voice console and a file signal bus. | `backtalk/main.py` (1,117 lines), `brain.py`, `mouth.py`, `ears.py`, `signals.py`, `ducking.py`, `ptt.py`, `config.py`, `TROUBLESHOOTING.md` |
| ai-visualizer | A stdlib Python server plus four canvas "faces" (board, radial, rain, neural). They poll `/state` at ~8 Hz, which reads `.voice_*` files. | `core.js` (the shared bus/envelope/demo/shot plumbing), `server.py`, `faces/*/index.html` |
| barehands | A webcam hand-tracking glass board (MediaPipe + three.js). The agent drives it through an allowlisted `/cmd` channel and reads it back through `/state`. | `server.py`, `stage.html`, `bin/board.sh`, `bin/board-state.sh`, `TROUBLESHOOTING.md` (the "tuning clinic") |

Architecture in one line: **Claude Code is the brain, a CLAUDE.md is the identity, a markdown vault is the memory, and pieces talk through tiny files on disk.** It runs only on Claude Code and has no provider independence.

---

## 2. Gaps by area

Format for each gap: **They** (with paths in their repo) · **Snow today** · **Value** · **Effort** · **Phase** · **Idea for Snow**.

### A. Memory ("the mind")

**A1. Long-term memory does not exist in Snow's requirements or roadmap**
- **They:** `ai-memory-vault/ai-memory-vault.md` ("How This System Actually Works", Part 2). The vault *is* the memory: it is external, has no size ceiling, and is loaded on demand. Indexes, wikilinks and Jobs make each lookup take one hop.
- **Snow today:** missing.
  - `persona.py` `History` keeps the last 6 pairs within a token budget of 1200 and is reseeded from the hub snapshot.
  - The memory store in research `ARCHITECTURE.md` ("SQLite + FTS5 + vectors", "minimal memory with FTS5" in SUMMARY) never got a REQ-ID or a phase.
  - PROJECT.md still promises replies built from "persona + situation + memory".
- **Value:** High · **Effort:** L overall (M for a first slice) · **Phase:** add MEM-xx requirements now, build a minimal slice in Phase 2 (profile and facts), episodes in Phase 4, procedures in Phase 5.
- **Idea:**
  - The source of truth is plain markdown under `%LOCALAPPDATA%\Snow\memory\`, so the user can read, edit and git-back it. It stays Obsidian-compatible, but Snow never requires Obsidian.
  - The hub keeps an FTS5 index of those files.
  - Reads are synchronous and fast (under 50 ms, no LLM) and run before the brain call.
  - Writes happen in an async job after the turn, using the brain role with `data_class="private"`.
  - Every write is a typed `memory.*` event, so the HUD and audit log see it.

**A2. Two-layer boot: a short pinned identity plus a larger index read on demand**
- **They:** `templates/CLAUDE.md` holds identity and "the rules that can't lapse". It survives context compaction. `VAULT-INDEX.md` holds the user profile and the vault map, which can be compacted away, so anything essential stays in the boot file.
- **Snow today:** `config/persona.toml` describes who Snow is. Nothing describes who the user is: no name, no form of address beyond "sir", no preferences.
- **Value:** High · **Effort:** S · **Phase:** 2.
- **Idea:** split the system prompt into `persona.toml` (Snow's character, unchanged) and a compact `profile.md` digest (about 150 tokens: name, address form, working style, current projects). Inject the digest every turn and retrieve the rest only when a turn needs it.

**A3. A living profile with edit permissions and an audit trail**
- **They:** VAULT-INDEX "Living Profile":
  - The AI *may* update Key People, How I Think, Health, Interests, Beliefs and Routine.
  - It *must not* touch the bio, projects, preferences or rules.
  - "A passing mention is not a personality trait."
  - A new fact that contradicts an old one updates the old entry instead of adding a second one.
  - Every update is logged under "Profile Updates" in the daily note.
- **Snow today:** missing.
- **Value:** High · **Effort:** S-M · **Phase:** 2-4.
- **Idea:**
  - Store the profile as typed sections, each with an `editable_by` of `snow` or `user`.
  - A post-turn extractor proposes a `memory.profile_update` event with the reason and the source turn_id.
  - The HUD shows "Snow learned: ..." with one-tap undo, which fits the glass-box goal.
  - Duplicates and contradictions are resolved by section key, never by appending.

**A4. Daily episodes with a fixed template and backfill of yesterday**
- **They:** `templates/DAILY-NOTE.md`. Each day has an Index plus sections: What Got Done, Still In Progress, Decisions, Notes Touched, Profile Updates. On a wrap-up signal ("goodnight") the agent offers to write the day. At session start it checks yesterday's note, backfills it if missing and says "reconstructed".
- **Snow today:** the durable event log (`hub/eventlog.py`, 30-day retention) is richer raw material, but it is never summarised. HAND-08 ("what happened?") is planned for Phase 4.
- **Value:** Med · **Effort:** M · **Phase:** 4.
- **Idea:** when the user says "go to sleep" or "that's all", or at local midnight, a background job turns the day's events into one `episodes/YYYY-MM-DD.md` with those five headings. "What happened while I was away", "what did we do yesterday" and the morning brief read episodes, not raw events.

**A5. One queue of open work as the system of record**
- **They:** a single `Active Priorities.md`. A daily note's "In Progress" is a frozen snapshot, "never treat it as current truth", so the agent verifies before acting.
- **Snow today:** the HAND-09 task board is planned for Phase 4. It does not yet say where the truth lives.
- **Value:** Med · **Effort:** S (design rule) · **Phase:** 4.
- **Idea:** the durable task table is the only truth for open work. Memory notes and episodes link to task ids and never copy their status.

**A6. "Jobs": procedures that get better with each correction**
- **They:** VAULT 4.7 and the boot rule "Bank the working method". A Job is one note per recurring task with a boot chain (exactly the notes the task needs), the procedure, a quality bar and a Lessons list where each user correction is folded in. When an approach fails and another works, the winning method and the dead end are recorded.
- **Snow today:** missing. PCTL2-02 (multi-step workflows) is v2.
- **Value:** High for Phase 5 (each app's screen-control recipe) and Phase 3 (repeatable agent tasks) · **Effort:** M · **Phase:** 5 (design in 3).
- **Idea:**
  - Keep a `procedures/` memory kind.
  - When a PC-control or agent task succeeds after a retry, the brain proposes "save how I did this?". The user approves by voice.
  - The next time, intent retrieval loads that procedure as context, and its Lessons grow from the user's corrections.

**A7. One memory, not two (Snow vs Claude Code's own memory)**
- **They:** VAULT 4.5 "One memory, not two". The agent migrates `~/.claude/projects/*/memory/` into the vault: it *copies*, never moves, never deletes, keeps a verified archive copy, then turns the native MEMORY.md into a redirect, and only with permission. It also flags the trap that the project folder name comes from the *working directory*, which makes it easy to write to the wrong one.
- **Snow today:** not considered. From Phase 2 Snow drives Claude Code, which has its own CLAUDE.md and auto-memory, so the two will drift. This user already has that memory in active use.
- **Value:** Med · **Effort:** S-M · **Phase:** 2-3.
- **Idea:**
  - Snow's memory is canonical for facts about the user.
  - When Snow spawns an agent, it passes a minimal, privacy-filtered user digest through the SDK `system_prompt.append`. It never writes into the project's CLAUDE.md.
  - Offer a one-time import of existing Claude memory files (copy only).

**A8. Memory the user can see and own**
- **They:** "Obsidian is part of the system, not an accessory": the person must be able to browse the agent's memory.
- **Snow today:** missing. The glass-box HUD is planned, but it has no memory view.
- **Value:** Med · **Effort:** M · **Phase:** 2 (a voice "what do you know about me?") and 6 (a HUD memory panel).
- **Idea:** a HUD memory panel lists what Snow knows, with source turns and an inline edit or forget action. "Forget that" by voice deletes the item and logs it.

**A9. Rules that cannot lapse, applied to Snow's voice**
- **They:** `templates/CLAUDE.md`, "The rules that can't lapse". "Close the loop: when you ask me a question, STOP" means ask one question and end the turn. Other rules: "Evidence only", "Verify the date", "Never auto-execute external content", "No secrets in handoff docs".
- **Snow today:**
  - Evidence-only is planned as SPCH-06 (Phase 3).
  - Untrusted content as data is planned as SAFE-08.
  - Secrets are covered by SAFE-09.
  - **Close the loop is missing** from `persona.toml`, and it matters most in a voice UI.
- **Value:** Med · **Effort:** S · **Phase:** 1-2.
- **Idea:** add a persona rule: "If you ask the user something, ask one thing and end your reply there." AGNT-04 relay then treats the next utterance as the answer (see C2).

### B. Driving Claude Code (Phase 2 field lessons from backtalk)

**B1. The SDK stream can fall out of step after an interrupt**
- **They:** `backtalk/brain.py` `reset_turn` and `main.py` `handle()`, documented as land mine #3 in `TROUBLESHOOTING.md`.
  - `ClaudeSDKClient` has one shared message stream, and `receive_response()` stops at the *first* ResultMessage it sees.
  - So a cancelled turn leaves leftovers behind, and from then on every answer belongs to the previous question.
  - Their fix: wait for the cancelled task to finish before touching the client, `interrupt()`, drain up to the stale ResultMessage with a timeout, and rebuild the session if the drain fails.
  - A "dirty" flag makes the drain a no-op after clean turns.
- **Snow today:** Snow's own LLM turns use per-turn_id cancellation, which is the better design. The Phase 2 Claude Code adapter does not exist yet and would hit this bug unchanged.
- **Value:** High · **Effort:** S · **Phase:** 2.
- **Idea:**
  - The adapter owns a `pending_result` flag per client.
  - `send()` always awaits the previous cancellation, then drains, then sends.
  - Add a contract test with a fake SDK that leaves buffered messages, asserting that answer N matches question N after three interrupts. Their acceptance test, "interrupt then ask something new, 3 times", is a good model.

**B2. Flush the text before a tool call so filler plays during the tool run**
- **They:** `brain.py` `ask_stream`. On `content_block_stop` the sentence buffer is flushed at once. Otherwise a line like "On it, let me grab that" sits silent through the whole tool run and then plays glued to the answer.
- **Snow today:** `voice/tts/text.py` flushes at clause and sentence ends only. The adapter event model has no "message block ended" signal.
- **Value:** High · **Effort:** S · **Phase:** 2.
- **Idea:** AgentEvent gets a `block_end` kind, and the voice chunker calls `flush()` on it. Pair this with a persona rule: before a long action, say one short line about what you are about to do.

**B3. SDK operating facts**
- **They:** `brain.py` `start`, `main.py` header comments:
  - Pin the *full* model id, never an alias, because an alias can silently resolve to an older model.
  - The CLI refuses a live switch *into* `bypassPermissions`. The safe direction works live.
  - The permission callback is wired at connect in every mode, so a mode flip needs no reconnect.
  - Every control request gets a timeout, so a hung CLI cannot make the voice loop deaf.
  - A hidden warm-up query runs behind the greeting to hide the prompt-cache cost.
  - When the brain cannot connect, the failure is reported out loud with the likely causes instead of failing silently.
- **Snow today:** not built.
- **Value:** Med · **Effort:** S · **Phase:** 2.
- **Idea:**
  - Never use bypass; that is already out of scope. Run the SDK in `default` mode and route every gated call through `can_use_tool` to Snow's policy gate.
  - Model ids in config must be full ids, enforced by a validator.
  - Start and warm the agent session while Snow speaks its acknowledgement of "start Claude Code on X".
  - Put `asyncio.wait_for` on every SDK call.
  - A failed connect becomes a `Fact(error=True)`, so the LLM explains it (this respects SPCH-01).

**B4. Claude Code plan usage readout**
- **They:** `brain.py` `_pull_rate_limits`, `signals.set_rate_limit`, `core.js` `U.usageRows`. Each turn asks the CLI for the 5-hour and 7-day usage windows. The call goes past the public SDK surface on purpose, so it is bounded to 5 s and every failure is swallowed. It is off by default because a face may be on a shared screen. A window known to exist but with no number yet still shows a row with a dash.
- **Snow today:** missing. Snow tracks its own providers (`brain/limits.py`) and Cartesia credits, not the Claude Code plan. The account is borrowed, which raises the stakes.
- **Value:** Med · **Effort:** S · **Phase:** 3-4.
- **Idea:** add a "Claude Code plan" health row with 5h and 7d percentages and reset times, and an 80% warning fact the LLM voices once. Mark it as a best-effort probe that is allowed to go quiet.

**B5. Control what the agent session is told about**
- **They:** `config.py` `visible_skills` limits the skill descriptions in the system prompt, as a screen-share privacy filter ("a context filter, not a sandbox").
- **Snow today:** not considered.
- **Value:** Low · **Effort:** S · **Phase:** 2.
- **Idea:** a per-project `agent_skills` allowlist in Snow's adapter config.

**B6. Resume the last agent session, fresh on failure**
- **They:** `brain.py` `_remember_session` and resume. The session id is saved after each *completed* turn. A failed resume falls back to a fresh session and logs it. A rebuild after a desync always starts fresh.
- **Snow today:** CORE-05 resume is planned for Phase 4.
- **Value:** Med · **Effort:** S · **Phase:** 2 (store the id) and 4 (resume flow).
- **Idea:** persist the agent session id per task in SQLite after each ResultMessage, and treat resume failure as a fact, not a crash.

### C. Spoken approvals (Phase 2; backtalk `main.py` `make_permission_gate`, `_human_what`, `_full_detail`, `_YES`, `handle`)

**C1. Plain words built by code, details on request**
- **They:**
  - The spoken "what" is built *by code from the tool and its input*, never by the model, "so it cannot understate". Examples: "create or change a note in your vault called Recipes", "run a git command in the terminal, with several chained parts".
  - Saying "details" reads the literal form.
  - Chained shell operators are always called out.
  - Truncation is disclosed ("and 340 more characters, check the log").
  - The full command always goes to the log.
- **Snow today:** SAFE-01..05 and HUD-07 are planned. The spoken form is not specified.
- **Value:** High · **Effort:** S-M · **Phase:** 2.
- **Idea:**
  - The policy engine produces `ApprovalRequest.facts` deterministically per tool kind: action verb, target name (never a path), chained yes/no, truncation, risk tier and reason.
  - The LLM phrases the spoken sentence from those facts, which keeps SPCH-01. A deterministic check makes sure every required fact appears. If one is missing, Snow shows the request on the HUD and says only that an approval is waiting.
  - The HUD shows the literal command, and the audit log gets it whole.

**C2. Route the next utterance to the pending question by when the speech started**
- **They:**
  - A pending question takes the next utterance only if that speech *started after* the question was asked. Earlier speech means the user is interrupting, so the question resolves as a silent deny.
  - A quit phrase wins only as an exact match, so "No! Don't hang up, skip it" stays a deny reason.
  - A question is always denied when its turn is interrupted, so it can never hijack a later utterance or stall the drain.
- **Snow today:** not designed. The turn engine already has the timestamps to do this.
- **Value:** High · **Effort:** S · **Phase:** 2.
- **Idea:** the approval object stores `asked_at` (audio time of the last played sample of the question). The turn engine tags each transcript with `speech_start`. The router compares the two and runs the barge-in rule first.

**C3. An exact-match consent set; anything else is a deny with a reason**
- **They:**
  - Approval needs an *exact* match after normalisation, never a prefix. "yesterday", "yes or no" and "yes, but do not overwrite" must all fail.
  - The set includes the words the prompt itself puts in the user's head ("permission granted").
  - Any other answer denies, and the user's own words go back to the agent as the reason, so "no, put it in drafts" actually steers the agent.
- **Snow today:** not designed.
- **Value:** High · **Effort:** S · **Phase:** 2.
- **Idea:** a deterministic consent classifier with an exact set in `voice.toml` and a speaker-verified voice required (VOIC-07). Any other answer becomes `PermissionResultDeny(message=<user words>)`. Tier 3 still needs a second factor, as research already says.

**C4. Asking for details resets the timeout**
- **They:** silence for 75 s means deny, said out loud. Asking for "details" restarts the clock, because engagement is not silence.
- **Snow today:** SAFE-05 times out to deny *and* keeps the request pending on the HUD and phone, which is better.
- **Value:** Low-Med · **Effort:** S · **Phase:** 2.
- **Idea:** adopt only the reset rule.

**C5. Say once per session how to change the setting**
- **They:** the first question of a session mentions the off switch.
- **Snow today:** n/a.
- **Value:** Low · **Effort:** S · **Phase:** 2.
- **Idea:** on the first approval each day, attach a one-time fact: "you can say 'show approvals' to review them on screen".

### D. Voice loop

**D1. Brain history keeps words the user never heard** *(found by comparison: the same failure class as their off-by-one bug)*
- **They:** design the whole interrupt path so the model's view of the conversation matches what really happened.
- **Snow today:** a bug.
  - `brain/worker.py` `_answer` calls `self._history.add(heard.text, text)` with the *full* generated reply.
  - The `reply.interrupted` event (`spoken_text`) is consumed only by `hub/projections.py`, never by the brain.
  - So after a barge-in the model believes it said things the user never heard. After a brain restart the snapshot reseed gets this right, so live and restored history disagree.
- **Value:** Med-High · **Effort:** S · **Phase:** 1 (adopt now).
- **Idea:** the brain subscribes to `reply.interrupted` and rewrites the last history pair to `spoken_text` plus an "(interrupted)" note. Add a unit test.

**D2. No date or time in the prompt**
- **They:** "Verify the date. Check the actual system date before writing a date into anything permanent."
- **Snow today:** missing. `persona.build_messages` adds no clock, so "what day is it", "late-night care" and anything the user schedules all fail.
- **Value:** Med · **Effort:** S · **Phase:** 1.
- **Idea:** add one system-note line per turn: local weekday, date, time and part of day. Add the user's name too once A2 lands.

**D3. Never speak file paths, URLs, long ids or raw numbers**
- **They:** `config.py` `DISCIPLINE`. "NEVER SPEAK A FILE PATH: say the file, not its address." Say numbers the way a person would. Write for the ear.
- **Snow today:** partial. `persona.toml` bans markdown, URLs and code, and `tts/text.py` `sanitize` strips URLs and code. File paths like `C:\Users\...` or `src/snow/x.py` and hashes pass through and would be read out. This becomes common in Phase 2-3, when agent output feeds replies.
- **Value:** Med · **Effort:** S · **Phase:** 1-2.
- **Idea:** in `sanitize`, replace path-like tokens with their basename and long hex or ids with "an id". Add the persona rule "name the file, not its location; round numbers as a person would".

**D4. Recovery after an audio device change**
- **They:** `ears.py` `_reopen_after_device_change`, `_mic_index`, `explain_audio_failure`, and `mouth.py` `_get_out`.
  - PortAudio caches its device list when it starts, so after a Bluetooth headset flips mode every open fails *silently forever*.
  - Their fix is to rebuild PortAudio. The speaker detects that its stream died and rebuilds it.
  - The mic is pinned by *name*: exact match first, then substring. If nothing matches, they fall back to the default and log every input they found.
  - The startup pre-flight checks that a mic exists before the greeting.
- **Snow today:** partial. `voice/sources.py` `MicSource._loop` retries the open with exponential backoff but never re-initialises PortAudio. `_wasapi_input` uses substring match only, and when nothing matches it returns `None` and drops to PortAudio's *MME* default without listing the devices it saw.
- **Value:** Med-High · **Effort:** S · **Phase:** 1.
- **Idea:** after N failed reopens, the voice worker exits with reason `audio_device_changed`, and the supervisor restarts it. A fresh process is the cleanest PortAudio reset, and the mic and playout share that process anyway. Also use exact-then-substring matching, fall back to the *WASAPI* default, and log the device list once per disappearance.

**D5. Duck other apps' audio while listening and speaking**
- **They:** `backtalk/ducking.py` (Spotify on macOS only):
  - Duck relative to the current volume, and only when it is above a threshold.
  - Duck when the user *starts* talking, not only while the agent speaks.
  - Debounce the restore (0.5 s) so gaps between sentences do not bounce the volume.
  - Restore quickly when the key is released, and restore synchronously on exit so the music is never left quiet.
- **Snow today:** missing. `pycaw` is already in the stack.
- **Value:** Med (it also helps STT and the echo canceller) · **Effort:** S-M · **Phase:** 1 polish or 5.
- **Idea:** duck every other app's audio session with pycaw (never Snow's own) to about 40% during listening and speaking, with a debounced restore. Keep the original volumes in hub state, so a crash or kill is repaired at the next start.

**D6. Filling silence during long work**
- **They:** `assets/thinking.wav` plays while the agent works (`signals.static_start/stop`). The face's own player defers to it through `.voice_loading_pid`, so it never plays twice. The model is prompted to say a filler line before tools (B2).
- **Snow today:** by decision, the orb shows thinking, and D-09/D-41 say no earcon. Phase 2 agent runs will create silences of several seconds to minutes.
- **Value:** Med-High · **Effort:** S · **Phase:** 2 (needs a user decision).
- **Idea:**
  - Default: an LLM-written pre-action line, the B2 flush, and the orb's "acting" state.
  - Offer the user an *optional* non-speech "working" ambience, off by default and toggled by voice. It is not a spoken phrase, so SPCH-01 holds, but it does reopen D-09, so ask the user.

**D7. Voice console verbs for session control**
- **They:** `main.py` `CONSOLE_VERBS`, `console_match`, `_run_console_inner`.
  - The verbs: clear or compact the session, deep or fast model, set the reasoning effort, usage report, mic mode, and permission prompts.
  - Each phrase must be spoken *exactly and alone*.
  - Risky flips need "confirm" within 120 s.
  - Settings are saved with a write that refuses to rewrite a config file that does not parse ("rewriting from {} would wipe every other setting").
  - Switching to the deep model comes with a spoken latency warning and lasts one session.
- **Snow today:** `[phrases]` in `voice.toml` has end, sleep and mute only (`voice/phrases.py`, the whole utterance, at most 6 words), which is the same discipline.
- **Value:** Med · **Effort:** S · **Phase:** 1-2.
- **Idea:** add these verbs:
  - "new conversation" clears History.
  - "think harder" sends the next N turns to the `brain` role, with a latency fact; "back to normal" returns.
  - "usage report" gives facts from `limits.snapshot`, Cartesia credits and B4.
  - "say that again".
  The replies stay LLM-written from facts.

**D8. Pace the later chunks for prosody**
- **They:** `main.py` `speak_reply` sends the first sentence alone for a fast start, then two sentences per TTS request ("single short sentences come out flat").
- **Snow today:** an 8-word first clause, then one sentence per chunk (`tts/text.py`).
- **Value:** Low · **Effort:** S · **Phase:** 1 tuning.
- **Idea:** an A/B test of pairing sentences with Pocket TTS through `snow dev audition-voices`.

**D9. A guaranteed way to be heard**
- **They:** the talk key works in *both* mic modes: it interrupts, and holding it always gets you heard over room noise. After 3 open-mic failures the mode falls back to push-to-talk automatically.
- **Snow today:** push-to-talk was removed (D-07). The SAFE-06 kill hotkey is planned for Phase 2.
- **Value:** Low-Med · **Effort:** S · **Phase:** 2.
- **Idea:** holding the SAFE-06 hotkey also opens a turn without the wake word, as a reliability fallback for noisy rooms. Revisit D-07 with the user.

**D10. Stage cues timed to the moment the audio is heard**
- **They:** `main.py` `_DIRECTION_TAG`, `signals.direction`, `mouth._play_stream`. The agent writes `<<cue>>` inline. The cue is never spoken, and it is published *when the audio carrying it starts playing*, so a screen change lands on the spoken word rather than seconds early.
- **Snow today:** only the emotion header exists. HUD panels spawn on events, not in sync with speech.
- **Value:** Med · **Effort:** S-M · **Phase:** 3/6.
- **Idea:** the brain may emit `[[show:<artifact_id>]]`. The chunker strips it and attaches it to the chunk, and playout, which already knows where each chunk starts, emits `speech.cue` → HUD opens the panel on the word "here".

**D11. Typed input is a first-class turn**
- **They:** typing in the terminal joins the same conversation, gets a spoken reply, and interrupts speech. Pastes are joined into one message.
- **Snow today:** VOIC-09 is planned for Phase 6. `snow dev say` is dev-only.
- **Value:** Low-Med · **Effort:** S · **Phase:** 6 (already planned).
- **Idea:** keep it as planned, and make sure a typed turn interrupts speech.

### E. Face / HUD

**E1. Adaptive level normalisation**
- **They:** `core.js` `tick`. The level is normalised against a decaying peak and then eased (attack 50 ms, release 350 ms), so a quiet voice moves the face as much as a loud one. The waveform ring is normalised against its own decaying peak too.
- **Snow today:** `playout.level_of` and `turn.mic_level` map a fixed -60..0 dBFS range, and `orb/smoother.ts` eases it (40/200 ms). `voice.toml` notes the mic sits 12-18 dB below reference, so the orb barely reacts to the user.
- **Value:** Med · **Effort:** S · **Phase:** 1 (or 6).
- **Idea:** keep a per-channel decaying peak in the HUD Smoother, with a floor so silence stays flat.

**E2. What each state means as motion**
- **They:** `faces/board/index.html`.
  - Listening *reverses the flow*: signals converge inward on the core.
  - Thinking eases in slowly and *resolves fast*.
  - Speaking emits a ring per syllable above a threshold.
  - Each state fades in with an exponential ease of about 380 ms.
  - A label "descrambler" makes text resolve out of glyph noise (`core.js` `U.Descrambler`).
  - All luminous elements get a single bloom pass, never per element ("bloom applied per-element reads as pencil lines").
- **Snow today:** per-state spin and alpha, a 120 ms cross-fade, a listening ring, and reduced-motion support (`orb/renderer.ts`). The full shader orb is planned for Phase 6.
- **Value:** Low-Med · **Effort:** M · **Phase:** 6.
- **Idea:** write "listening = inward", "thinking resolves fast" and "one bloom pass" into the Phase 6 UI-SPEC, and use the descrambler idea for captions and panel titles in the ASCII style.

**E3. Privacy defaults for a screen others may see**
- **They:** usage is off by default ("the faces are frequently on a stream or a shared screen"). The sound toggle stays hidden until the mouse moves, so it never shows on camera. `visible_skills` (B5) does the same for the agent's context.
- **Snow today:** the HUD shows the live transcript, and the phone HUD comes later. There is no notion of a shared screen.
- **Value:** Med · **Effort:** S · **Phase:** 6 (an S slice now).
- **Idea:** call Electron's `BrowserWindow.setContentProtection(true)` on transcript and memory panels by default, which keeps them out of screen captures and screen shares. Add a voice "privacy mode" that hides personal panels.

**E4. Waveform bins instead of one scalar level**
- **They:** a 64-sample waveform at about 15 Hz drives spectrum-like motion.
- **Snow today:** one scalar level at about 31 Hz.
- **Value:** Low-Med · **Effort:** S · **Phase:** 6.
- **Idea:** send 16 band energies alongside the level for the Phase 6 orb.

**E5. Self-healing state**
- **They:** a fresh waveform means "speaking", whatever the state file says (`server.py` `read_bus`). barehands treats a non-idle state older than 10 minutes as idle (`state_timeout_s`).
- **Snow today:** heartbeats, `LEVEL_STALE_MS` and snapshot-on-reconnect already cover this. **Snow is equal or better.**
- **Value:** — · **Effort:** — · **Phase:** —.
- **Idea:** no action.

### F. Hands (barehands)

**F1. Webcam gesture board**
- **They:** a webcam hand-tracking board.
- **Snow today:** not relevant. Snow replaces the keyboard *by voice*. A webcam adds privacy risk and a CPU/GPU load the 6 GB budget cannot spare.
- **Value:** — · **Phase:** skip.

**F2. The "present" verb and looking before you talk**
- **They:** `barehands.md` 4b and `server.py` `/cmd`. When the person asks to SEE something, the agent puts it centre stage, spotlit, with everything else dimmed, instead of answering in text. `board-state.sh` lets the agent read what is on screen before commenting, because the user moves things by hand ("never trust memory").
- **Snow today:** HUD-04 and HUD-06 (spawned panels) and SPCH-05 (show, don't read) are planned, but the brain cannot *ask* for a panel or *read* what is on screen.
- **Value:** Med · **Effort:** M · **Phase:** 3/6.
- **Idea:** two brain tools. `hud.show(artifact_id, focus=true)` spotlights the artifact and dims the rest. `hud.state()` returns the open panels, so the brain refers to what is actually visible. This pairs with D10.

**F3. An allowlist and a path jail for UI commands the agent sends**
- **They:** `server.py` keeps `_ALLOWED` actions. Only files that resolve inside the media root can be staged. Escapes return 400. Notes are read-only and jailed to their orb root.
- **Snow today:** SAFE-08 covers this in general, but the brain-to-HUD command channel has no design yet.
- **Value:** Med · **Effort:** S · **Phase:** 3.
- **Idea:** HUD commands are a closed union in `contracts/events.py`, and artifact paths resolve only inside Snow's artifact store.

**F4. Mirror Claude Code sessions Snow did not start**
- **They:** `barehands.md` 4a. The `UserPromptSubmit` and `Stop` hooks write the state. They are scoped to the *agent folder's* `.claude/settings.json`, never the home-level file, so unrelated sessions do not drive the face. A stale-state timeout covers a session that crashed. On Windows the hooks run through bash, so they are written with forward slashes and no `cmd /c`.
- **Snow today:** Snow sees only the sessions it spawns.
- **Value:** Low-Med · **Effort:** S · **Phase:** 3.
- **Idea:** offer optional per-project hooks that POST to the hub's loopback endpoint with a token, so the HUD's activity stream also shows Claude Code sessions the user started by hand.

**F5. The calibration method ("tuning clinic")**
- **They:** `barehands/TROUBLESHOOTING.md`. Sample the correct pose and the impostor, find a metric whose ranges do not overlap, set the cut in the middle of the gap, write the evidence into the code comment, and retest both.
- **Snow today:** the wake threshold already uses FA/hour and recall (plan 01-30), which is equal or better.
- **Value:** Low-Med · **Effort:** S · **Phase:** 2.
- **Idea:** reuse the "own voice vs TV and other voices, cut mid-gap, record the evidence" protocol for the speaker-verification threshold (VOIC-07), and as a tuning guide for Claude Code.

### G. Product and UX polish

**G1. A troubleshooting doc for the agent, a land-mines list, and the agent as mechanic**
- **They:** every repo's `TROUBLESHOOTING.md` ("Written for humans AND for AI assistants... diagnose from the log, not from guesses").
  - backtalk has "the architecture in six lines" and "Three land mines with warning signs... do not simplify these away" (it actually lists five).
  - fullstack-agent Phase 4 adds a "You are the mechanic" section to the agent's CLAUDE.md.
- **Snow today:** missing. No README, no TROUBLESHOOTING. `AGENTS.md` covers process only. Pitfalls live in scattered code comments, and Claude Code will start editing Snow in Phase 2.
- **Value:** High · **Effort:** S · **Phase:** now (before Phase 2 dogfooding).
- **Idea:** `docs/TROUBLESHOOTING.md` (symptom → which log line → fix), a 10-line architecture brief, and a "Load-bearing code, do not simplify" section in `.claude/CLAUDE.md`. Candidates for that section:
  - PortAudio callbacks only copy and return.
  - The echo canceller's reference is the post-fade played block.
  - One turn_id cancellation token fans out to everything.
  - The no-literal-speech test (`tests/brain/test_no_scripts.py`).
  - Privacy routing via `data_class`.
  - The mute rule that the mic never opens by itself after a restart.
  - The supervisor's sleep-gap forgiveness.

**G2. A diagnosis command (`snow doctor`)**
- **They:** log-first diagnosis and startup pre-flights:
  - Check a mic exists before the greeting.
  - Prove the GPU with a tiny inference before claiming ready, falling back to CPU with a log line.
  - Detect the Microsoft Store "python" decoy (`run.bat`).
  - When package install fails, say it failed *before* the voice ran, so nobody hunts through an empty log.
- **Snow today:** health rows exist, but there is no single command that dumps a diagnosis.
- **Value:** Med · **Effort:** S · **Phase:** 1-2.
- **Idea:** `snow doctor` prints:
  - the health snapshot,
  - the device list with the chosen mic and speaker,
  - provider reachability and key *presence* (never values),
  - autostart task status, model checksums,
  - and the last 50 error lines across workers.
  Claude Code runs it first, every time.

**G3. A first-run onboarding conversation**
- **They:** `fullstack-agent.md` and `ai-memory-vault.md` Phase 4.0.
  - Collect every answer once and order the questions so each depends on the last.
  - Show *what will be created* before doing it, and get a clear yes.
  - Adopt what already exists instead of duplicating it. Never delete or move the user's things; copy instead.
  - Verify each write by reading it back.
  - End with a "first hello" finale, and test every launcher with the person.
  - A "this is a test" shortcut builds the full structure with placeholder content.
  - Ask one question at a time.
- **Snow today:**
  - `snow setup` handles keys only.
  - `snow dev audition-voices` exists.
  - Wake training is a human action (01-30).
  - Speaker enrollment comes in Phase 2.
  - The installer comes in Phase 7.
- **Value:** Med now, High for "others later" · **Effort:** M · **Phase:** pieces in 2, the whole flow in 7.
- **Idea:** `snow onboard`, voice-first after keys:
  1. Mic pick and level check.
  2. Voice audition.
  3. Wake test with live score.
  4. Speaker enrollment.
  5. The user's name and form of address (seeds A2).
  6. Privacy choices explained in one line each.
  7. It ends with Snow's first LLM-written greeting by name.

**G4. Show the changes before applying an update**
- **They:** `update.sh` shows the incoming commits ("new: ...") before pulling, and a fast-forward-only pull keeps local edits. The user's config is untracked by design. A legacy tracked config is stashed and restored. A zip download is wired to git on its first update. The script runs from `main()`, so updating the script itself mid-run cannot garble it.
- **Snow today:** CORE-07 (approved self-upgrade with rollback) is planned for Phase 3, QUAL-02 for Phase 7.
- **Value:** Med · **Effort:** S · **Phase:** 3/7.
- **Idea:** the upgrade approval includes an LLM summary of the commit list between the running and the candidate build, shown on the HUD and spoken in two sentences. User config stays outside the versioned copy.

**G5. Naming discipline**
- **They:** two axes never share a word. "Hands-free" is about the mic and "auto-approve" is about permissions, called out in the README, the config comments and the troubleshooting doc.
- **Snow today:** mute, sleep, "that's all" (end) and silent mode (SPCH-07) are close cousins.
- **Value:** Low · **Effort:** S · **Phase:** 1/6 copy.
- **Idea:** a glossary in `copy.ts` and the UI-SPEC. One word per axis: *mute* is the mic, *sleep* is the conversation, *silent* is the voice output.

**G6. Self-repair at launch**
- **They:** each launch runs `uv sync --inexact` (healing a half-installed environment), and the window holds on error so it stays readable. The launcher is visible, never hidden ("a hidden background launcher looks like malware to antivirus").
- **Snow today:** the supervisor and logon autostart are in place. The installer `uv sync --frozen` is planned.
- **Value:** Low-Med · **Effort:** S · **Phase:** 7.
- **Idea:** the hub checks that the lockfile is in sync at start (fast when current) and raises a clear health error otherwise. Watch the antivirus heuristics for the hidden logon task when "others later" arrives, and sign binaries.

**G7. Desktop shortcuts per mode**
- **They:** "Chat", "Talk" and "Barehands" shortcuts, each tested with the user by double-click.
- **Snow today:** autostart plus tray. Snow is always on, so this barely applies.
- **Value:** Low · **Phase:** skip.

**G8. One identity in every channel**
- **They:** the same CLAUDE.md is the agent in terminal, voice and board ("Always Jarvis... every channel").
- **Snow today:** `persona.toml` is config-driven.
- **Value:** Low · **Effort:** S · **Phase:** 4.
- **Idea:** make sure the Telegram (Phase 4) and phone HUD texts are written from the same persona and profile digest.

**G9. Several assistants from one install**
- **They:** an environment variable (`BACKTALK_CONFIG`) points at a different config, so one code copy can run a second assistant.
- **Snow today:** "others later" is planned through per-user data dirs.
- **Value:** Low · **Phase:** later.
- **Idea:** no action now.

---

## 3. What Snow already does better (do not regress)

| Area | Snow | fullstack-agent |
|---|---|---|
| Waking | Local "Hey Snow" wake word, stays in conversation (D-08), 4-frame RAM pre-roll, threshold calibrated by FA/hour and recall (01-30) | Push-to-talk key by default. Open-mic mode uses webrtcvad with no wake word, so any speech in the room triggers it |
| Barge-in | livekit APM echo cancellation with a warm-up guard, so it works on laptop speakers | Barge-in "requires headphones", or it interrupts itself |
| End of turn | Silero VAD plus Smart Turn v3.2 | Fixed 480 ms silence |
| Interrupt correctness | A turn_id cancellation token through the brain, TTS and playout. Barge-in events carry the heard text | A drain-the-stream workaround for a shared SDK stream |
| STT | Groq whisper-large-v3-turbo with a deadline, plus local Moonshine partials and fallback, plus a silence-rejection rule | Local faster-whisper small.en only |
| TTS | Router with mid-reply failover (Pocket → Cartesia big moments → Chatterbox → Kokoro), emotion header, polish stage, RTF-adaptive rebuffer with fades | Kokoro or ElevenLabs, with a single fallback |
| Tone | Local prosody tone tag with deterministic calm override (D-36) | None |
| Speech authenticity | Every spoken word is LLM-generated, enforced by test | Many hard-coded spoken lines (greeting, permission prompts, console replies) |
| Providers | Five OpenAI-compatible providers with per-role fallback chains, rate-limit cooldowns, privacy routing (SAFE-12) | Claude Code only |
| Secrets | Windows Credential Manager, a canary test, redacting logs | Windows: a plaintext environment variable |
| Safety | Deterministic tiers, speaker verification, kill switch outside the LLM, timeout-deny that stays pending on HUD and phone, audit log, "no auto-approve" (out of scope) | An exact "yes" from *any* voice in the room approves. "Stop asking for permission" plus "confirm" turns approvals off |
| Robustness | Supervisor with Job Object, heartbeats, hang kill, sleep-gap forgiveness, logon autostart, named-mutex single instance | Manual launch; socket-mutex single instance |
| Contracts and quality | Typed event contract, durable SQLite event log, projections, generated TS types, contract samples, CI, hardware suites, visual and perf e2e | Hand-tested; no tests in the repos |
| Privacy | No idle audio leaves the PC, audio never on disk, hard mute closes the mic | Local by default, fine, but less strict |
| HUD engineering | Levels outside React state, reduced motion, visibility throttle, sleep fps cap, perf budget tests | Canvas faces; nice look, no tests |

**Rules for adopting anything from this study without regressing:**
- (a) Never add auto-approve.
- (b) Never add hard-coded spoken lines. Console replies, approval prompts and errors are LLM-written from facts.
- (c) Never replace the typed WebSocket events with a file bus.
- (d) Keep loopback-only plus Tailscale.
- (e) Memory writes are private-class data and never go to untrusted providers.

---

## 4. Skip list (with reason)

- **barehands gestures, OBS/streaming modes, the face gallery:** off-mission for a voice-first keyboard replacement, and they cost privacy, CPU and GPU.
- **Auto-approve / the `bypassPermissions` voice flip:** explicitly out of scope for Snow.
- **The file-based signal bus (`.voice_state` and similar):** Snow's typed WebSocket events are strictly better.
- **Obsidian as a *required* app:** keep memory as Obsidian-compatible markdown, but never require Obsidian.
- **Push-to-talk as the default:** D-07 stands. Only the hotkey fallback (D9) is worth considering.
- **Spotify/AppleScript ducking, macOS `.command` launchers, the Keychain path:** platform-specific. Snow has Windows equivalents.
- **The marketing-skills upsell and the community/Discord prompts:** not product features.
- **ElevenLabs:** Snow's Cartesia, Pocket and Chatterbox plan already covers the role.

---

## 5. Ranked top 10

| # | Verdict | Item | Why | Effort |
|---|---|---|---|---|
| 1 | **Adopt now (add requirements); build in Phase 2+** | Long-term memory: profile digest, living profile with edit rights and an undo-able audit, episodes, procedures ("Jobs"), markdown source of truth plus FTS5 (A1-A8) | The biggest real gap. "Persona + situation + memory" is promised and has no requirement or phase | L (M for the Phase 2 slice) |
| 2 | **Adopt now** | `docs/TROUBLESHOOTING.md` written for the agent, a land-mines section in `.claude/CLAUDE.md`, and `snow doctor` (G1, G2) | Claude Code starts editing Snow in Phase 2; this protects the load-bearing code and makes self-repair possible | S |
| 3 | **Adopt in Phase 2** | Claude SDK interrupt guard (wait, interrupt, drain, rebuild) plus the pre-tool text flush and the SDK operating facts (B1-B3) | Each one is a known, field-proven bug the Phase 2 adapter would otherwise ship | S |
| 4 | **Adopt in Phase 2** | Spoken approval UX: code-built plain-words facts plus "details", an exact consent set, deny-with-reason, routing the answer by speech start time, details resetting the timeout (C1-C4) | Fills in the voice half of SAFE-01..05 and HUD-07, the riskiest UX in v1 | S-M |
| 5 | **Adopt now** | Truncate brain history to the spoken text on barge-in (D1) | A live correctness bug in `brain/worker.py`; one subscriber plus a test | S |
| 6 | **Adopt now** | A date and time context line, speakable-text rules (no paths or ids, natural numbers), a "close the loop" persona rule (D2, D3, A9) | Cheap, and each one prevents a visibly dumb moment | S |
| 7 | **Adopt now** | Audio device recovery: restart the worker to reset PortAudio after repeated failures, exact-then-substring mic matching, WASAPI-default fallback with a device list log (D4) | Prevents "Snow is silently deaf after I connected my headset" | S |
| 8 | **Adopt in Phase 1 polish (or 5)** | Duck other apps' audio during listening and speaking, with crash-safe restore through pycaw (D5) | Feels Jarvis-like, and helps STT and the echo canceller | S-M |
| 9 | **Adopt in Phase 2** | Voice console verbs: new conversation, think harder / back to normal, usage report (including Claude Code plan usage, B4), say that again (D7) | Session control without a keyboard is the core value; replies stay LLM-written | S |
| 10 | **Adopt in Phase 3/6** | Speech-synced HUD cues plus a `hud.show` "present" verb plus a `hud.state` readback, through an allowlisted command union (D10, F2, F3) | Makes "show, don't read" (SPCH-05) and spawned panels (HUD-04) feel directed, with no new attack surface | M |

**Next in line:**
- Adaptive orb level normalisation (E1, S, Phase 1).
- Screen-capture protection for personal HUD panels (E3, S).
- The `snow onboard` first-run conversation (G3, Phase 7, pieces in 2).
- Changelog-in-approval for self-upgrade (G4, Phase 3).
- The silence-filling decision for long agent runs (D6, ask the user).

**Skip:** barehands gestures (F1), auto-approve, the file bus, a hard Obsidian requirement, push-to-talk by default, macOS-only pieces.
