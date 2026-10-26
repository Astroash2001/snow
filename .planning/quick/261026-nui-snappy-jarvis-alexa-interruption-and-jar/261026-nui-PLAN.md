---
phase: quick-261026-nui
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/snow/voice/turn.py
  - config/persona.toml
  - tests/voice/test_turn_engine.py
  - tests/voice/test_bargein.py
  - src/snow/voice/config.py
  - config/voice.toml
  - tests/voice/conftest.py
  - src/snow/voice/playout.py
  - src/snow/voice/pipeline.py
  - tests/voice/test_playout.py
autonomous: true
requirements: [VOIC-06, SPCH-01]

estimate:
  tokens: 75000
  raw_tokens: 75000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Saying the wake phrase while Snow's reply is audible stops the speaker on the same call that delivers the wake hit (no extra microphone audio needed), cancels the reply in progress (turn.cancelled barge_in, reply.interrupted), shows listening and opens a fresh wake turn. If nothing follows, the user gets the usual wake-alone acknowledgement."
    - "A wake hit while a reply is pending but not yet audible (thinking) is still ignored, as before."
    - "Talking over Snow lowers its voice to duck_gain within about 30 ms once duck_after_ms of speech is heard. Quiet stretches up to barge_gap_ms inside the user's words do not reset the count. barge_in_min_ms of speech (live 400; barge_in_warmup_min_ms 600 while the echo canceller warms) stops Snow."
    - "A noise that is not confirmed as a barge-in within duck_release_s of its first speech brings Snow's voice back to full level, and the reply carries on uninterrupted."
    - "The barge-in turn carries the user's speech run plus at most 0.3 s of audio before it, not the whole ring buffer of Snow's echo."
    - "Bad duck settings in voice.toml (duck_gain outside (0, 1], or duck_release_s shorter than either barge-in minimum) fail at load."
    - "The persona tells the LLM to put the number first when the answer is a number, to announce actions in the present tense as they start, and after being cut off to answer the new words directly, without apologising and without finishing the old sentence. These are instructions only. No phrase is hard-coded (SPCH-01)."
  artifacts:
    - path: "src/snow/voice/turn.py"
      provides: "_cut() shared stop path; on_wake barges in while Snow speaks; gap-tolerant _listen_over with duck and release; seed slice; duck hook attribute"
      contains: "def _cut"
    - path: "src/snow/voice/playout.py"
      provides: "Playout.set_gain(gain) thread-safe target; per-sample gain ramp in _callback before on_render; gain reset per utterance"
      contains: "def set_gain"
    - path: "src/snow/voice/config.py"
      provides: "TurnConfig barge_gap_ms, duck_after_ms, duck_gain, duck_release_s and an after-validator"
      contains: "duck_release_s"
    - path: "config/voice.toml"
      provides: "[turn] barge_in_min_ms = 400 and the four new keys"
      contains: "duck_gain"
    - path: "config/persona.toml"
      provides: "Answering and interruption rules in system_prompt"
      contains: "apologise"
  key_links:
    - from: "TurnEngine.on_wake"
      to: "VoicePipeline.on_barge_in -> Playout.abort"
      via: "TurnEngine._cut() -> events.on_barge_in()"
      pattern: "self\\._cut\\(\\)"
    - from: "TurnEngine._listen_over"
      to: "Playout.set_gain"
      via: "TurnEngine.duck hook, assigned in VoicePipeline._load_tts next to echo_warming"
      pattern: "self\\._engine\\.duck = "
    - from: "Playout._callback gain ramp"
      to: "on_render (echo canceller reference)"
      via: "gain applied to out inside the locked section, before on_render"
      pattern: "self\\.on_render\\(out\\)"
    - from: "config/voice.toml [turn]"
      to: "TurnConfig"
      via: "load_config('voice.toml', VoiceConfig); extra keys are forbidden"
      pattern: "duck_after_ms"
---

<objective>
Make interrupting Snow feel like Alexa and Jarvis (UAT gap G-01-5, the user's request of 2026-10-26: "Snow keeps on speaking for a while and then it stops. I want that snappy response like Alexa.").

1. The wake phrase is the interrupt. "Hey Snow" while Snow is speaking stops it at once, cancels the reply and listens. This uses the same path as a voice barge-in.
2. Duck, then stop. When speech is heard over Snow, its voice drops to duck_gain within about 30 ms. A gap-tolerant run of barge_in_min_ms (live 400) confirms the barge-in and stops Snow. An unconfirmed noise releases the duck after duck_release_s.
3. Jarvis speech style, through persona instructions only: the number first, actions announced in the present tense, and no apology or old-sentence finish after an interruption.

Purpose: today a barge-in needs 500 ms of unbroken VAD speech. Any single quiet 32 ms chunk resets the count, so real speech takes 1 to 2 s to cut Snow off, and "Hey Snow" over Snow does nothing. The user wants the instant cut-off of a real assistant.
Output: changes to turn.py, playout.py, pipeline.py, config.py, voice.toml, persona.toml and conftest.py, plus unit tests in tests/voice at every threshold edge.

Re-read `src/snow/voice/turn.py`, `src/snow/voice/playout.py` and `src/snow/voice/pipeline.py` fresh before editing. Keep these intact:
- `Playout.abort()` stays instant: stream abort plus start, and the tail is at most one block.
- `Playout.on_render(out)` is still called exactly once per callback block, after the locked fill. The new gain is applied to `out` inside the locked section, before `on_render`, so the echo canceller's reference equals what is played.
- `_on_frame` keeps `aec.capture(frame)` first.
- `_load_tts` keeps building the EchoCanceller before the Playout and keeps assigning `echo_warming`.
- The `_chunk` path that cuts a wake acknowledgement (`t.speech_run >= self._barge_min()`) is not changed.

Project rules: never `cd` (run every command from the repo root); no new packages; audio and transcripts are never written to disk or logs, and the new code logs nothing. Another quick task (261026-nvh) is editing `src/snow/brain/` and `tests/brain/` in parallel, so do not edit any file there. `config/persona.toml` is the only file in that area that this plan touches.
</objective>

<execution_context>
@.claude/gsd-core/workflows/execute-plan.md
@.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@src/snow/voice/turn.py
@src/snow/voice/playout.py
@src/snow/voice/pipeline.py
@src/snow/voice/config.py
@config/voice.toml
@config/persona.toml
@tests/voice/conftest.py
@tests/voice/test_turn_engine.py
@tests/voice/test_bargein.py
@tests/voice/test_playout.py

Facts verified at planning time (use them as given):
- CHUNK = 512 samples = 32 ms at 16 kHz. Every engine threshold is counted in samples of audio time, never the wall clock.
- `TurnEngine.on_wake` currently returns early when `self._turn is not None or self._waiting`. While a reply is audible, `_waiting` and `_speaking_out` are both True, so a wake hit during speech is dropped today. During a wake acknowledgement, a follow-on `_turn` (with `speaking` False) is open and `_speaking_out` is True.
- `VoicePipeline._on_frame` calls `self._engine.on_wake(hit)` instead of `feed(frame)` on a hit frame, and both run on the audio thread. `VoicePipeline.on_barge_in` aborts the playout on that thread, sets `_pending = None` and hops `_interrupt` to the loop. `_interrupt` emits TurnCancelled(barge_in) and ReplyInterrupted. `VoicePipeline.on_presence("listening")` clears `_pending` and publishes PresenceState.
- The pipeline registers itself with `engine.events = self` (pipeline.py:138). It sets `self._engine.echo_warming = aec.warming` in `_load_tts`. The new `duck` hook follows that same callable-attribute pattern, so the EngineEvents Protocol, NullEvents and the test Log classes do not change for it.
- The ring (`self._ring`) is cleared on every `set_speaking` message. Today it is sized from max(barge_in_min_ms, barge_in_warmup_min_ms) plus `_BARGE_LEAD_S` (0.3 s), and `_barge_in` seeds the new turn with the whole ring.
- `Playout._reset_utterance` runs in `__init__`, `start_utterance`, `abort`, `close`, and in `_callback` when an ended utterance drains. That makes it the natural place to reset the gain to 1.0.
- tests/voice/conftest.py `voice_cfg()` pins barge_in_min_ms=250 and stop_secs=0.2 for the fixtures. tests/voice/test_turn_engine.py, test_bargein.py and test_echo_cancel.py all use it. Existing barge-in fixtures: a continuous 320 ms run fires on the 8th chunk (256 ms). 192 ms of speech followed by 300 ms of quiet must not fire. While the canceller warms, 352 ms must not fire and a 640 ms run fires on the 19th chunk (608 ms, the live barge_in_warmup_min_ms = 600). All of these still hold under the new rule.
- tests/brain/test_persona.py asserts that the substrings "sir" and "no tools" are in `system_prompt`. tests/brain/test_no_scripts.py requires every persona key except `system_prompt` and `ack_prompt` to be a short identifier or a number.
- The brain keeps its own history and is not told about interruptions (src/snow/brain has no ReplyInterrupted handling, and it is out of bounds here). The persona rule must therefore work from the new user words alone.
- tests/voice/test_echo_cancel.py and tests/hardware/test_echo_cancel.py measure the echo residual as a run of consecutive VAD chunks. That proxy is not changed in this plan (see the output section).
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer - "Hey Snow" over Snow stops it at once and listens, plus the Jarvis speech rules</name>
  <files>src/snow/voice/turn.py, config/persona.toml, tests/voice/test_turn_engine.py, tests/voice/test_bargein.py</files>
  <behavior>
    - Engine (tests/voice/test_turn_engine.py, with the existing make/wake/speak helpers): wake, speak (the turn ends and a reply is pending), `engine.set_speaking(True)`, then feed one CHUNK of quiet so the inbox drains. A second `wake(engine)` then appends, in this order, ("barge_in", None), ("presence", "listening"), ("wake", None) to the log. After that, `feed_s(engine, 1.5)` of quiet logs exactly one "wake_alone", because a fresh wake turn was opened.
    - Engine: wake and speak (a reply is pending, but `set_speaking(True)` has not been sent). A second `wake(engine)` changes nothing: `log.count("wake") == 1` and there is no "barge_in".
    - Pipeline (tests/voice/test_bargein.py, with make_rig, ask, start_reply(blocks=10) and HoldEngine(hold_from=2)): note `rig.mic`, then call `rig.turn.on_wake(WakeHit(1.0, "t", [np.zeros(1280, dtype=np.int16)], 1280))`. Right after that synchronous call, `rig.aborts == [mic_before]`: the speaker was aborted with no further microphone audio. Then wait for ReplyInterrupted. TurnCancelled is [(turn_id, "barge_in")], two WakeDetected events exist, `rig.pipeline._reply is None`, `rig.pipeline._pending is None` and the last PresenceState is "listening". Then `rig.hear(320, speech=True)` and `rig.hear(500, speech=False)` produce a second TranscriptFinal whose turn_id differs from the first.
    - Persona: tests/brain/test_persona.py and tests/brain/test_no_scripts.py still pass, unedited.
  </behavior>
  <action>
In src/snow/voice/turn.py, factor the stop half of `_barge_in` into a new private method `_cut(self) -> None`, with a one-line docstring ("Snow's voice is cut off: stop waiting, drop the barge-in state, tell the pipeline."). It does exactly what `_barge_in` does today before it builds the turn, in this order:
- clear `self._ring`
- set `self._speaking_out = False` and `self._barge_run = 0`
- set `self._waiting = False` and `self._idle = 0`
- call `self._eot.clear()`
- call `self.events.on_barge_in()`, then `self.events.on_presence("listening")`

`_barge_in` then becomes four steps:
- take `seed = list(self._ring)`
- call `self._cut()`
- build the follow-on `_Turn` from the seed exactly as today, and append each seed chunk to `self._eot`
- call `self.events.on_turn_start(t.id)`

The event order stays on_barge_in, on_presence("listening"), on_turn_start, so the existing barge-in tests are unchanged.

Change `on_wake` to apply Amazon's rule that the wake word is the interrupt (VOIC-06):
- After `self.drain()`, return if `self.state is State.MUTED`.
- If `self._speaking_out` is True and no open turn has confirmed speech (`self._turn is None or not self._turn.speaking`), call `self._cut()` then `self._close_turn()`. Add the one-line comment "the wake phrase is the interrupt (Alexa rule): stop now, then listen".
- Keep the existing guard `if self._turn is not None or self._waiting: return`, with its comment, and the rest of the wake path unchanged. A cut wake therefore opens a normal wake turn whose boundary is the pre-roll, and the D-09 wake-alone acknowledgement works as usual.
- A wake while a reply is pending but not audible (`_waiting` True, `_speaking_out` False) still returns: Snow is not speaking yet, so there is nothing to interrupt.

Update the `set_speaking` docstring to say that the wake phrase also interrupts.

In tests/voice/test_turn_engine.py, add `on_barge_in(self) -> None` to the `Log` class, recording ("barge_in", None). Add the two engine tests from the behavior block. Feed CHUNK-sized zero frames where single chunks matter: each `engine.feed(np.zeros(CHUNK, dtype=np.int16))` yields exactly one chunk.

In tests/voice/test_bargein.py, add the pipeline test from the behavior block, named in the file's style (e.g. `test_the_wake_phrase_over_snow_stops_it_at_once_and_listens`). Import WakeDetected from snow.contracts.events.

In config/persona.toml `system_prompt`, add a section headed "Answering and being interrupted:" between "Personality and manner" and "Reading the user". It has three bullets, written as instructions to the model (per SPCH-01, give no example lines to copy, no quotation marks and no exclamation marks):
- First bullet: when the answer is a number (a time, a count, an amount, a distance, a date), say the number in the first few words and put any context after it.
- Second bullet: when you begin doing something for the user, say what you are doing in the present tense as it starts, in a few words, and report the result when it is done. You have no tools yet, so until you do, the rule above against claiming to have done or started anything still holds.
- Third bullet: the user may talk over you or say your wake phrase while you speak. Your voice stops at once and whatever you were saying is over. Never apologise for stopping, never finish or repeat the sentence that was cut off, and never remark on the interruption. Answer the new words directly, and go back to the earlier answer only if the user asks.

Keep every existing line, including the "sir" and "You have no tools yet" bullets.
  </action>
  <verify>
    <automated>uv run pytest -q tests/voice/test_turn_engine.py tests/voice/test_bargein.py tests/brain/test_persona.py tests/brain/test_no_scripts.py</automated>
  </verify>
  <done>
- A wake hit while Snow's voice is audible aborts the speaker in the same call. The reply is cancelled and reported, presence goes to listening, and a fresh wake turn is open, so silence after it yields one wake-alone acknowledgement.
- A wake hit while thinking is still ignored.
- All earlier barge-in tests pass unchanged.
- The persona has the three new rules, and the brain tests pass unedited.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Gap-tolerant barge-in at 400 ms with a duck decision and release in the engine</name>
  <files>src/snow/voice/config.py, config/voice.toml, tests/voice/conftest.py, src/snow/voice/turn.py, tests/voice/test_turn_engine.py</files>
  <behavior>
    These tests use the pinned test values: barge_in_min_ms 250 (8 chunks), barge_gap_ms 150 (a 4-chunk gap is tolerated, a 5-chunk gap breaks the run), duck_after_ms 150 (the 5th speech chunk), duck_gain 0.25, duck_release_s 1.0 (the 32nd chunk of an episode; 31 chunks = 15872 samples is still short of it). Setup: wake, speak, `engine.set_speaking(True)`, `gains: list[float] = []`, `engine.duck = gains.append`, then CHUNK-sized frames with the scripted VAD.
    - 4 speech, 2 quiet, 4 speech: exactly one "barge_in" (on the 8th speech chunk) followed by a "turn_start", and `gains == [0.25]`. The old consecutive rule would never have fired here.
    - 4 speech, 5 quiet, 4 speech: no "barge_in" and `gains == []`. The run broke, and it never reached 150 ms of speech.
    - 5 speech, then quiet: `gains == [0.25]` after the 5th speech chunk and not after the 4th. After 26 more quiet chunks (31 in the episode) it is still [0.25]. One more quiet chunk gives `gains == [0.25, 1.0]`, and there is no "barge_in".
    - 8 speech: `gains == [0.25]` and one "barge_in". There is no 1.0, because the abort resets the playout.
    - Seed: 40 quiet chunks, 8 speech, then quiet until "turn_end". The ended turn's bytes equal (8 speech + 10 lead + 7 closing) * CHUNK * 2 = 25600. The lead is ceil(0.3 s * 16000 / 512) = 10 chunks, and the closing chunks are where stop_secs 0.2 is first reached. The turn does not carry the whole 41-chunk ring.
    - Config: `TurnConfig` built from CFG.turn's fields with duck_release_s 0.5 (below the 600 ms warm-up minimum) raises pydantic.ValidationError. So do duck_gain 0.0 and duck_gain 1.5 (parametrized).
    - Every existing test in tests/voice/test_bargein.py and tests/voice/test_echo_cancel.py still passes.
  </behavior>
  <action>
In src/snow/voice/config.py `TurnConfig`, add four required fields after barge_in_warmup_min_ms, each with a one-line comment:
- `barge_gap_ms: int`: a quiet stretch up to this long inside the user's words does not break a barge-in run
- `duck_after_ms: int`: this much speech over Snow lowers its voice
- `duck_gain: float`: Snow's playout gain while ducked
- `duck_release_s: float`: an unconfirmed barge-in releases the duck this long after its first speech

Add a `model_validator(mode="after")` method, following the style of src/snow/brain/config.py (returns Self; import `Self` from typing and `model_validator` from pydantic). It raises ValueError when `duck_gain` is not in the range 0 < duck_gain <= 1, or when `duck_release_s * 1000 < max(barge_in_min_ms, barge_in_warmup_min_ms)`, because then a barge-in could never be confirmed. This is validation at the config trust boundary.

In config/voice.toml [turn]:
- Set `barge_in_min_ms = 400` and replace its comment with one line: was 500 after a 0.42 s Kokoro echo residual run (2026-10-24); 400 now that Snow ducks about 12 dB after 150 ms of speech, so its echo has dropped before a barge-in can confirm (G-01-5, 2026-10-26).
- Keep `barge_in_warmup_min_ms = 600` and its comment (the warming-canceller minimum stays).
- Add `barge_gap_ms = 150`, `duck_after_ms = 150`, `duck_gain = 0.25` (about -12 dB) and `duck_release_s = 1.0`, each with a short trailing comment.

In tests/voice/conftest.py `voice_cfg()`, extend the turn `model_copy` update to also pin barge_gap_ms 150, duck_after_ms 150, duck_gain 0.25 and duck_release_s 1.0, so the fixtures do not move when the live values are tuned. Add one clause to the docstring saying so.

In src/snow/voice/turn.py `TurnEngine.__init__`:
- Next to `echo_warming`, add `self.duck: Callable[[float], None] = lambda gain: None`, with the comment "Sets Snow's playout gain (audio thread); set by the pipeline."
- Replace `self._barge_run` with the episode state: `_barge_span` (samples since the episode's first speech chunk, 0 when there is no episode), `_barge_run` (speech samples in the current run), `_barge_gap` (quiet samples since the last speech chunk) and `_ducked` (bool).
- Size the ring from `cfg.duck_release_s + _BARGE_LEAD_S`. The validator guarantees this covers both barge-in minimums, so the `longest` line goes.
- Add `_reset_barge()`, which zeroes span, run and gap and clears `_ducked`. Call it wherever `self._barge_run = 0` is written today (the "speaking" branch of `drain`, and `_cut`).

Rewrite `_listen_over(chunk)`. For each chunk:
1. Append it to the ring. Speech means `speech_prob >= cfg.vad_threshold`.
2. With no episode open (span 0), a quiet chunk returns at once.
3. Otherwise add CHUNK to span.
4. On speech, add CHUNK to run and zero the gap. On quiet, add CHUNK to gap, and when the gap is greater than `barge_gap_ms` in samples, zero the run (the run broke, but the episode goes on).
5. If run >= `self._barge_min()`, call `self._barge_in()` and return. `_barge_min` is unchanged, so the warming-canceller minimum still applies.
6. If not ducked and run >= `duck_after_ms` in samples, set ducked and call `self.duck(cfg.duck_gain)`.
7. If span >= `duck_release_s` in samples, call `self.duck(1.0)` if ducked, then `_reset_barge()`.

Give the docstring one line explaining why gaps are tolerated: real speech has short quiet chunks, and a reset on each one made a barge-in take 1 to 2 s (G-01-5).

In `_barge_in`, take the seed as only the last `ceil((self._barge_span + self._samples(_BARGE_LEAD_S)) / CHUNK)` chunks of the ring, read before `_cut()` resets the state. The turn then gets the run plus 0.3 s of lead, not up to 1.3 s of Snow's echo (G-01-5 root cause (a)).

In tests/voice/test_turn_engine.py, add the tests from the behavior block. Use small helpers: one that sets Snow speaking and hooks `engine.duck`, and one that feeds n CHUNK frames with `vad.speech` set. Assert exact chunk boundaries, both the last chunk before a threshold and the first chunk at it.
  </action>
  <verify>
    <automated>uv run pytest -q tests/voice/test_turn_engine.py tests/voice/test_bargein.py tests/voice/test_echo_cancel.py</automated>
  </verify>
  <done>
- The engine confirms a barge-in on accumulated speech that tolerates gaps up to barge_gap_ms. It requests a duck after duck_after_ms and a release after duck_release_s when the barge-in is not confirmed. It seeds the barge-in turn with the run plus 0.3 s only.
- The live barge_in_min_ms is 400, the four new keys are in voice.toml and TurnConfig, and bad values fail at load.
- All existing voice tests pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Snow's voice actually ducks - playout gain ramp and pipeline wiring</name>
  <files>src/snow/voice/playout.py, src/snow/voice/pipeline.py, tests/voice/test_playout.py, tests/voice/test_bargein.py</files>
  <behavior>
    - Playout (tests/voice/test_playout.py `rig()` and `block_of`, RATE 24000, 480-sample blocks): push a 0.5 tone of 1 s and play one block at full level. Then `playout.set_gain(0.25)`. The next block falls monotonically (non-increasing) from below 0.5. By sample 720 of the duck, 30 ms at 24 kHz (index 240 of the second block), the level is 0.125, and the third block is entirely 0.125 (approx). `rendered[-1]` equals each played block: the echo reference equals the speaker.
    - Playout: from ducked, `set_gain(1.0)` rises monotonically back to 0.5 within 30 ms.
    - Playout: duck, play a block, then `abort()`, `start_utterance()` and push a tone. The first block is at full 0.5, so the gain was reset. A drained utterance also resets it: the next utterance after `end_utterance` plus drain starts at full level.
    - Pipeline (tests/voice/test_bargein.py, with make_rig, ask and start_reply(blocks=10)): `rig.turn.duck == rig.pipeline._playout.set_gain` (bound-method equality: wired in `_load_tts`). Wrap `rig.turn.duck` with a spy that records the gain and calls through. Then `rig.hear(192, speech=True)` gives gains [0.25], and `rig.hear(900, speech=False)` gives [0.25, 1.0]. There are no aborts, and the reply is still playing (`rig.pipeline._reply is not None`).
  </behavior>
  <action>
In src/snow/voice/playout.py:
- Add the module constant `_DUCK_RAMP_S = 0.03`, commented "a full 1.0 gain swing takes 30 ms: fast enough to feel instant, slow enough not to click".
- In `__init__`, compute the per-sample gain step as `1.0 / (sample_rate * _DUCK_RAMP_S)`.
- In `_reset_utterance`, set the current gain `self._gain` and the target `self._gain_to` to 1.0, so every new utterance, abort, close and drain starts at full level.
- Add the public method `set_gain(self, gain: float) -> None`, docstring "Thread-safe: ramp Snow's voice toward `gain` (barge-in duck); `abort` and the next utterance reset it to 1.0". It sets `_gain_to` under `self._lock`.

In `_callback`, inside the locked section, right after the fill loop (so before the fade-in, the underrun fade and the drained reset), when `filled` is nonzero and either `_gain` or `_gain_to` is not 1.0, multiply `out[:filled]` by a per-sample ramp:
- The ramp starts one step from `_gain` and moves toward `_gain_to` by the step per sample, clamped at the target. Use one numpy expression, for example the current gain plus sign(delta) times the minimum of arange(1, filled+1)*step and abs(delta), as float32.
- Afterwards, store the last ramp value as `_gain`.
- When the target is already reached, the same expression gives a constant gain.

Add one line to the module docstring: the barge-in duck gain is applied with the fades, before `on_render`. `abort()` is unchanged apart from inheriting the reset through `_reset_utterance`.

In src/snow/voice/pipeline.py `_load_tts`, right after the Playout is built, add `self._engine.duck = self._playout.set_gain` with the comment "the user talking over Snow lowers its voice (audio thread -> playout lock)". This matches the existing `echo_warming` assignment. Nothing else in the pipeline changes: a confirmed barge-in still goes through `on_barge_in` and `playout.abort()`, and that abort resets the gain.

In tests/voice/test_playout.py and tests/voice/test_bargein.py, add the tests from the behavior block. In test_bargein, take the spy's call-through target from the value read before wrapping, so the real playout still ducks.
  </action>
  <verify>
    <automated>uv run pytest -q tests/voice/test_playout.py tests/voice/test_bargein.py tests/voice/test_tts_pipeline.py tests/voice/test_echo_cancel.py</automated>
  </verify>
  <done>
- Speech over Snow lowers its playout gain to 0.25 within 30 ms, and the echo canceller reference matches.
- An unconfirmed noise brings the gain back to 1.0 after duck_release_s.
- Abort, a new utterance and a drain all reset the gain.
- The engine's duck hook is wired to `Playout.set_gain` in `_load_tts`.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| room audio -> wake gate / VAD | anyone (a TV, another person, Snow's own echo) can produce speech or the wake phrase while Snow talks |
| config/voice.toml -> TurnConfig | a user-edited file sets the barge-in and duck thresholds |
| audio thread -> PortAudio output thread | set_gain crosses threads into the playout callback |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-nui-01 | Denial of service | TurnEngine._listen_over (gap-tolerant 400 ms on speakers) | medium | mitigate | Duck to 0.25 after 150 ms, so Snow's echo is about 12 dB down before 400 ms can accumulate. The 600 ms warming-canceller minimum is kept. A noise that is not confirmed releases after 1.0 s. The user re-tests self-interruption on laptop speakers in UAT (output section). |
| T-nui-02 | Spoofing | TurnEngine.on_wake (wake phrase from a TV or another person stops Snow) | low | accept | It only stops speech and opens a listening turn. No action runs, and the wake threshold and model are unchanged. Speaker verification arrives in Phase 2. |
| T-nui-03 | Tampering | TurnConfig duck keys | low | mitigate | An after-validator refuses duck_gain outside (0, 1] and a duck_release_s shorter than either barge-in minimum, and extra keys stay forbidden, so a bad file fails at load instead of silently disabling barge-in. |
| T-nui-04 | Information disclosure | new engine and playout code | low | mitigate | No logging is added. Audio stays in the in-memory ring and turn buffers (D-18), and nothing is written to disk. |
| T-nui-05 | Tampering (race) | Playout.set_gain from the mic thread | low | mitigate | The target is written under the existing playout lock, which the callback already holds when it reads it. The ramp state is only touched inside the callback's locked section. |
| T-nui-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package is installed or added by this plan. uv.lock does not change. |
</threat_model>

<verification>
Run from the repo root, in this order (the project's prior gate commands):
- uv run ruff check src tests
- uv run ruff format --check src tests
- uv run pyright
- uv run pytest -q tests/voice tests/brain

Hand checks for the user on the real laptop (record them in the SUMMARY; they are not run by the executor):
1. While Snow is mid-reply, say "Hey Snow". The voice stops within about a tenth of a second, the HUD shows listening, and Snow answers what you say next. If you say nothing, it gives a short acknowledgement.
2. Talk over a long reply. Snow's voice drops at once and stops within about half a second.
3. Cough or tap the desk while Snow speaks. The voice dips briefly, comes back, and the reply continues.
4. On laptop speakers, let Snow speak several long replies without talking. It must never cut itself off.
5. Ask for the time or a count. The number comes first. Interrupt a reply with a new question. Snow answers the new question without apologising or finishing the old sentence.
</verification>

<success_criteria>
- The wake phrase interrupts audible speech in the same call as the hit (test asserts the speaker abort before any further mic audio).
- The barge-in confirms on 400 ms (live) of gap-tolerant speech, ducks after 150 ms and releases after 1.0 s unconfirmed, with every threshold edge pinned by a unit test.
- The playout duck ramps within 30 ms, the echo reference matches it, and it resets on abort, a new utterance and a drain.
- The persona carries the three speech rules as instructions, and the no-scripts and persona tests pass unedited.
- All four gate commands pass.
</success_criteria>

<output>
Create `.planning/quick/261026-nui-snappy-jarvis-alexa-interruption-and-jar/261026-nui-SUMMARY.md` with `status: complete` in its frontmatter. Include:
- the gate results
- the five hand checks above, verbatim
- a note that tests/voice/test_echo_cancel.py and tests/hardware/test_echo_cancel.py still measure the residual as consecutive VAD runs. The engine now accumulates across gaps of up to 150 ms, and the live minimum (400 ms) is below the 0.42 s residual run seen on 2026-10-24, so the hardware echo suite and hand check 4 must be run on speakers before G-01-5 is closed.
- a note that the wake-acknowledgement cut-off in `_chunk` still uses the consecutive run (out of scope)
</output>
