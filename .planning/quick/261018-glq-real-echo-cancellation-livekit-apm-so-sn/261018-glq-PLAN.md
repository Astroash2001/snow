---
phase: quick-261018-glq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - uv.lock
  - src/snow/voice/aec.py
  - src/snow/voice/playout.py
  - src/snow/voice/pipeline.py
  - src/snow/voice/turn.py
  - src/snow/voice/config.py
  - src/snow/voice/tts/config.py
  - src/snow/voice/__main__.py
  - config/voice.toml
  - config/tts.toml
  - tests/voice/test_echo_cancel.py
  - tests/voice/test_bargein.py
  - tests/hardware/test_echo_cancel.py
autonomous: true
requirements: [VOIC-06]

estimate:
  tokens: 95000
  raw_tokens: 95000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "On laptop speakers, Snow's own voice reaching the mic is cancelled before the wake gate, VAD/turn engine, local STT, Groq STT and tone see it: once warm, the longest residual VAD run stays under barge_in_min_ms (250 ms), so Snow neither transcribes itself nor barges in on itself"
    - "The user talking over Snow on speakers still interrupts it: at least 70% of the user's VAD chunks survive the canceller and a barge-in-length run starts within 0.7 s of the user's onset"
    - "Until about 2 s of reference audio has played after start, barge-in needs barge_in_warmup_min_ms (600 ms) instead of 250 ms, so the cold-start residual (measured max 352 ms) cannot cut the first reply off"
    - "With echo_cancellation = true and assume_headphones = false in config/tts.toml, the live worker runs the canceller and no speakers warning is logged; if livekit fails to load or the APM errors, audio passes through unchanged, aec_unavailable or aec_failed is logged, and Snow keeps listening and speaking"
    - "A mic or reference frame that is not a whole number of 10 ms raises ValueError in Python and never reaches livekit's native call (a wrong size kills the interpreter with no exception)"
    - "Audio stays in memory (D-18): the canceller, its tests and the hardware test write nothing to disk and open no network connection"
  artifacts:
    - path: "src/snow/voice/aec.py"
      provides: "EchoCanceller: livekit AudioProcessingModule with echo cancellation only; render() tap, capture() cleaner, warming(), close(), pass-through on failure"
      contains: "class EchoCanceller"
    - path: "src/snow/voice/playout.py"
      provides: "on_render callback fed every output block (speech or zeros)"
      contains: "on_render"
    - path: "src/snow/voice/pipeline.py"
      provides: "echo_cancel flag; canceller built after the voice loads; mic frames cleaned first in _on_frame; warm-up wiring; closed on stop"
      contains: "echo_cancel"
    - path: "src/snow/voice/turn.py"
      provides: "echo_warming hook and the warm-up barge-in minimum on both barge-in paths"
      contains: "echo_warming"
    - path: "tests/voice/test_echo_cancel.py"
      provides: "Real-APM synthetic-echo tests, frame guards, thread stress, failure pass-through, wiring"
    - path: "tests/hardware/test_echo_cancel.py"
      provides: "Hand-run laptop speaker + mic test (marked hardware), memory only"
      contains: "pytest.mark.hardware"
  key_links:
    - from: "src/snow/voice/playout.py Playout._callback"
      to: "EchoCanceller.render"
      via: "on_render=self._aec.render passed in VoicePipeline._load_tts"
      pattern: "on_render"
    - from: "src/snow/voice/pipeline.py VoicePipeline._on_frame"
      to: "EchoCanceller.capture"
      via: "first statement of _on_frame, before _recent, local STT, wake and turn engine"
      pattern: "capture\\(frame\\)"
    - from: "src/snow/voice/__main__.py"
      to: "build_pipeline(echo_cancel=...)"
      via: "tts_cfg.playout.echo_cancellation"
      pattern: "echo_cancel="
    - from: "src/snow/voice/turn.py barge-in checks"
      to: "EchoCanceller.warming"
      via: "TurnEngine.echo_warming set in VoicePipeline._load_tts"
      pattern: "echo_warming"
---

<objective>
Real echo cancellation so Snow works on laptop speakers with the laptop mic without hearing itself (VOIC-06). Observed bug: on speakers Snow transcribes its own words and barge-in cancels its reply after 250 ms.

Add livekit 1.1.20 (user-approved) and wrap its WebRTC AEC3 `AudioProcessingModule` in `src/snow/voice/aec.py`. Snow's playout output is the reference stream (tapped in `Playout._callback`, at the playout's own 24 kHz, no resampling); every live mic frame goes through the canceller first in `VoicePipeline._on_frame`, so wake, VAD/turn, Moonshine, Groq and tone all hear cleaned audio. Barge-in keeps working on speakers, with a cold-start guard for the first ~2 s of reference. Then turn it on in config (`assume_headphones = false`, `echo_cancellation = true`) and leave a hardware test for the user.

Purpose: the user can use Snow without headphones (Core Value: voice alone, no keyboard), without Snow interrupting or answering itself.
Output: `src/snow/voice/aec.py`, wiring in playout/pipeline/turn/config, CI tests through the real APM with synthetic echo, a hand-run hardware test.
</objective>

<execution_context>
@C:/Users/avina/Desktop/asssistant/.claude/gsd-core/workflows/execute-plan.md
@C:/Users/avina/Desktop/asssistant/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@.planning/quick/261018-glq-real-echo-cancellation-livekit-apm-so-sn/261018-glq-RESEARCH.md
@src/snow/voice/playout.py
@src/snow/voice/pipeline.py
@src/snow/voice/turn.py
@src/snow/voice/config.py
@src/snow/voice/tts/config.py
@config/tts.toml
@config/voice.toml
@tests/voice/test_bargein.py
@tests/voice/test_tts_pipeline.py

Interfaces the executor needs (verified at planning time):
- `Playout(sample_rate, cfg: PlayoutConfig, *, on_first_audio, on_level, on_drained, stream_factory)`; `_callback(outdata, frames, time_info, status)` fills `out = outdata[:, 0]` (float32, 480 samples per 20 ms at 24 kHz) under `self._lock`, then fires callbacks outside the lock. The output stream is created on the first `start_utterance()` and stays open (zeros between utterances), so the callback runs continuously after that.
- `VoicePipeline.__init__(cfg, hub, source, wake, engine, stt, source_name="voice", local=None, tts=None, tts_cfg=None, stream_factory=None)`; `build_pipeline(...)` has the same tail. `_load_tts(router)` builds the Playout after `await router.wait_ready()` using `router.sample_rate`. `_on_frame(frame)` runs on the `snow-voice-audio` thread; `_Pump.deliver` already catches exceptions per frame. `stop()` closes the source (joins the thread), then the playout.
- Mic frames: int16 mono, 1280 samples at 16 kHz (8 x 160-sample 10 ms slices). `Frame = npt.NDArray[np.int16]` in `snow.voice.sources`; `read_wav(path, sample_rate)` there resamples fixtures.
- `TurnEngine.__init__(cfg: TurnConfig, vad, eot, events=None, sample_rate=16000, conversation=None)`; barge-in thresholds are `self._cfg.barge_in_min_ms` at `_listen_over` (turn.py ~273) and in `_chunk` (turn.py ~309), and the ring size at turn.py ~144. Config models are strict (`extra="forbid"`), fields without defaults are required, loaded from `config/*.toml` everywhere (tests use `load_config`).
- livekit 1.1.20 APM API (from research, executed): `rtc.AudioProcessingModule(*, echo_cancellation=False, noise_suppression=False, high_pass_filter=False, auto_gain_control=False)`; `process_reverse_stream(frame)` = reference, `process_stream(frame)` = mic, in place; `rtc.AudioFrame(data, sample_rate, num_channels, samples_per_channel)`, int16 interleaved, `frame.data` to read back. Frames must be a whole number of 10 ms (`rate // 100` samples). Reference and mic rates may differ (24 kHz reference vs 16 kHz mic verified).
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer - real APM on the live path (playout reference in, cleaned mic frames out)</name>
  <files>pyproject.toml, uv.lock, src/snow/voice/aec.py, src/snow/voice/playout.py, src/snow/voice/pipeline.py, tests/voice/test_echo_cancel.py</files>
  <behavior>
    - Raw mic (synthetic echo of fixture speech + -63 dBFS noise, no canceller) has a VAD run of at least CFG.turn.barge_in_min_ms: proves the fixture reproduces the bug.
    - Through the real EchoCanceller, warm (utt1, 2 s silence, utt2; seed 0, delay 120 ms, echo -26 dBFS): the longest VAD run during utt2 is under CFG.turn.barge_in_min_ms and ERLE over utt2 (from +1 s) is at least 20 dB.
    - capture() with 100 or 170 samples raises ValueError; EchoCanceller(render_rate=22050) raises ValueError.
    - Playout calls on_render once per pumped block with a float32 array of 480 samples, silent blocks included.
    - A VoicePipeline built with echo_cancel=True has an EchoCanceller after _tts_ready, and _on_frame passes every frame through its capture(); with echo_cancel=False it has none and frames are untouched.
  </behavior>
  <action>
1. Dependency: run `uv add livekit==1.1.20` (user-approved; pins it in `[project].dependencies` and hash-locks `uv.lock`; 1.1.20 predates the `exclude-newer` cutoff, so no per-package override). Then compare the `[[package]]` names in `git diff uv.lock`: the only new packages must be `livekit` and `types-protobuf`, and no existing package may change version. If anything else appears, stop and report instead of editing the lock by hand. Add nothing else (no scipy or soxr: the APM resamples the 24 kHz reference itself).

2. Create `src/snow/voice/aec.py`. Module docstring: VOIC-06, WebRTC AEC3 through livekit's AudioProcessingModule; `render()` runs on PortAudio's output thread and `capture()` on the mic thread (the intended WebRTC render/capture threading, stress-tested in research); audio only in memory (D-18). Use logger `logging.getLogger("snow.voice")`. Class `EchoCanceller(capture_rate: int = 16000, render_rate: int = 24000)`:
   - Constructor: raise ValueError if either rate is not a multiple of 100 (APM frames are 10 ms), before importing anything. Then import `from livekit import rtc` inside `__init__` (lazy: about 0.5 s and 21 native threads, paid only when enabled; use a `TYPE_CHECKING` import for annotations). Build `rtc.AudioProcessingModule(echo_cancellation=True)` and leave noise suppression, auto gain control and the high-pass filter off. Research measured that AGC lifts the user from -26 to -19 dBFS, which shifts the VAD, wake and tone levels; NS makes the cold start worse; AEC3 already has its own high-pass. Store the samples per 10 ms for each side (`rate // 100`), an empty int16 render tail, and `reference_s: float = 0.0`.
   - `render(block: npt.NDArray[np.float32]) -> None`: read `self._apm` into a local and return if it is None. Otherwise convert to int16 (`block * 32768` clipped to the int16 range), put the previous tail in front, send each whole 10 ms slice to `process_reverse_stream(rtc.AudioFrame(bytearray(slice.tobytes()), render_rate, 1, n))`, and keep the leftover as the new tail, so any PortAudio block size works. Add `len(block) / render_rate` to `reference_s` when the block's RMS is above -50 dBFS (module constant `_REF_FLOOR`). Wrap the whole body in try/except Exception that calls `_fail(e)`. An exception escaping a PortAudio callback stops Snow's voice, so this method must never raise. Do not log on the normal path.
   - `capture(frame: Frame) -> Frame`: first, outside any try, raise ValueError if `len(frame)` is not a multiple of the capture 10 ms size. Comment why in one line: a non-10 ms frame makes livekit's Rust side panic and kill the interpreter with no Python exception. Then read `self._apm` into a local and return the frame unchanged if it is None. Otherwise process each 10 ms slice through an `rtc.AudioFrame` built from `bytearray(slice.tobytes())`. It must be a bytearray: processing is in place, and a memoryview is copied so the result is lost. Call `process_stream`, copy `np.frombuffer(f.data, dtype=np.int16)` into a new output array, and return it. On any exception, call `_fail(e)` and return the input frame unchanged.
   - `warming() -> bool`: return `self.reference_s < WARMUP_S`, with `WARMUP_S = 2.0` as a module constant. One-line why: measured cold-start residual still passes VAD 0.64-1.38 s after the first reference energy. Task 2 uses it.
   - `_fail(e)`: the first time only, `log.error("aec_failed kind=%s", type(e).__name__)`. Then set `self._apm = None`, so both sides pass audio through from then on.
   - `close()`: set `self._apm = None`. Dropping the module avoids livekit's `FfiHandle.__del__` AssertionError traceback at interpreter exit. Make it idempotent.
   - Do not call `set_stream_delay_ms`. Add a one-line comment why: research measured identical ERLE with hint None/0/20/120 for true delays up to 500 ms, and PortAudio reports 2-3 ms latencies on this laptop, which understate the real path.
   - pyright strict: livekit ships `py.typed`. Add narrow `# pyright: ignore[...]` comments only where pyright actually complains.

3. `src/snow/voice/playout.py`: add a keyword parameter `on_render: Callable[[npt.NDArray[np.float32]], None] = lambda block: None` next to the other three callbacks and store it as `self.on_render`. In `_callback`, call `self.on_render(out)` exactly once per block. Place it right after the `with self._lock:` block (`out` now holds speech or zeros) and before the first-audio, level and drained callbacks. Call it every block, silent ones included, so the reference timeline has no gaps. Never delay or buffer the reference: research measured that a reference older than the echo path gives only about 3 dB. Update the module docstring's callback list.

4. `src/snow/voice/pipeline.py`:
   - Import `EchoCanceller` from `snow.voice.aec` at module level. The module itself is cheap; livekit loads only in the constructor.
   - Add a keyword argument `echo_cancel: bool = False` to `VoicePipeline.__init__` and to `build_pipeline`, and forward it. Store `self._echo_cancel` and `self._aec: EchoCanceller | None = None`. Only the worker's live mic turns it on. FileSource, dev replay and existing tests stay byte-identical.
   - In `_load_tts`, when `wait_ready()` is true and `self._echo_cancel` is set, build the canceller before the Playout: `self._aec = await asyncio.to_thread(EchoCanceller, self._cfg.audio.sample_rate, router.sample_rate)`. Use to_thread because the ~0.9 s import and construction must not block the loop. Use `router.sample_rate`, read after wait_ready: the playout rate comes from the first engine that loads. On any exception, `log.warning("aec_unavailable kind=%s barge_in_hears_snow", type(e).__name__)` and leave `_aec` None, so audio passes through. When `_aec` exists, pass `on_render=self._aec.render` to the Playout.
   - Make cleaning the first step of `_on_frame`: read `self._aec` into a local, and if it is not None, replace `frame` with `aec.capture(frame)`. Everything after it sees cleaned audio: `_recent`, local STT, the wake gate and the turn engine. Before the voice loads nothing plays, so pass-through then is correct.
   - In `stop()`, after `self._playout.close()`, call `close()` on the canceller if there is one.

5. Create `tests/voice/test_echo_cancel.py` with a module docstring: real APM and real Silero, nothing played, mic not opened, nothing written. Helpers:
   - `echo_of(far16, delay_ms, level_dbfs, seed)` as in research: a 60 ms decaying-noise room impulse, delayed and scaled to an absolute level.
   - The far-end signal comes from `read_wav(AUDIO / name, 24000)` (sent to `render()` as float32 / 32768) and the same file at 16000 (used to compute the echo). Use phrase_thats_all, tone_calm and phrase_go_to_sleep.
   - Mic = echo + seeded white noise at -63 dBFS.
   - A `drive()` loop: every 20 ms call `render()` with a 480-sample block, and every 80 ms call `capture()` with a 1280-sample frame. Render goes before capture, so the reference is never older than the echo.
   - `longest_run_ms()` runs `VadDetector().speech_prob` over 512-sample chunks against `CFG.turn.vad_threshold`.
   - An ERLE helper (raw echo RMS vs processed RMS in dB over a window).

   Tests, per the behavior block:
   - Precondition: the raw mic has a VAD run of at least barge_in_min_ms.
   - Warm residual and ERLE: seed 0, delay 120 ms.
   - Frame guards.
   - Playout wiring: `Playout` with the `Speaker`/`FakeStream` helpers from tests/voice/test_tts_pipeline.py; pump silent and speaking blocks and record the `on_render` calls.
   - Pipeline wiring: build like `make_rig` in tests/voice/test_bargein.py (StubSource, NoWake, scripted VAD TurnEngine, fake voice and speaker), passing `echo_cancel=True` to `VoicePipeline`. After `_tts_ready`, assert `_aec` is an EchoCanceller. Spy on its `capture` and call `_on_frame` with a zero 1280 frame to show the frame went through it. With `echo_cancel=False`, `_aec` is None.

   Mark nothing slow: the file runs in seconds. The research numbers are deterministic for this pin and a fixed seed. If a threshold fails, report the measured value; do not quietly loosen it.
  </action>
  <verify>
    <automated>uv run pytest -q tests/voice/test_echo_cancel.py tests/voice/test_tts_pipeline.py tests/voice/test_bargein.py tests/voice/test_no_egress.py</automated>
  </verify>
  <done>livekit==1.1.20 is in pyproject.toml and uv.lock, and the only new lock packages are livekit and types-protobuf. The real APM cancels a synthetic speaker echo so a warm residual never reaches a barge-in-length VAD run. Wrong frame sizes raise ValueError. Playout feeds the reference every block. The pipeline cleans live mic frames first when echo_cancel=True and is unchanged otherwise. Existing pipeline, barge-in and no-egress tests still pass.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Cold-start barge-in guard, double-talk, failure pass-through and thread-safety proof</name>
  <files>src/snow/voice/turn.py, src/snow/voice/config.py, config/voice.toml, src/snow/voice/pipeline.py, tests/voice/test_bargein.py, tests/voice/test_echo_cancel.py</files>
  <behavior>
    - With echo_warming returning True, a 352 ms speech run over Snow's reply does not barge in; a run of at least barge_in_warmup_min_ms does (via the make_rig flow in test_bargein.py), and the barged turn's audio keeps at least barge_in_warmup_min_ms of the interrupting speech (ring sized for the larger minimum).
    - With echo_warming returning False (the default), the existing 250 ms barge-in tests pass unchanged.
    - Warm residual across seeds 0-3 x delays 60/120/250 ms at -26 dBFS: longest VAD run during utt2 under barge_in_min_ms, ERLE at least 20 dB.
    - Double-talk: the user (mid_thought_pause.wav) starts 1.5 s into utt2 at -32 dBFS over -26 dBFS echo. At least 70% of the user-alone VAD chunks (at or above threshold) survive, and a run of barge_in_min_ms begins within 0.7 s of the user-alone first-run onset.
    - Thread stress: render() from one thread and capture() from another, 500 iterations each, raises nothing and the APM stays active.
    - Failure: with `_apm` replaced by a stub whose process methods raise, render() does not raise, capture() returns a frame equal to its input, `_apm` becomes None, and close() can be called twice. With `snow.voice.pipeline.EchoCanceller` monkeypatched to raise, the pipeline leaves `_aec` None, logs aec_unavailable (caplog), and a reply still plays to drained.
  </behavior>
  <action>
1. `src/snow/voice/config.py`: add `barge_in_warmup_min_ms: int` to `TurnConfig` as a required field. `config/voice.toml` `[turn]`: add `barge_in_warmup_min_ms = 600`, commented that it applies while the echo canceller has heard under ~2 s of Snow's voice (measured cold residual up to 352 ms). Keep `barge_in_min_ms = 250` for steady state (warm residual max 192 ms).

2. `src/snow/voice/turn.py`:
   - Add a public attribute `echo_warming: Callable[[], bool]` that defaults to `lambda: False` (set in `__init__` next to `events`). It keeps the engine framework-free and audio-time driven: the canceller counts reference audio seconds, not wall clock.
   - Add a small private helper that returns the barge-in minimum in samples: `barge_in_warmup_min_ms` while `self.echo_warming()` is true, otherwise `barge_in_min_ms`. Use it in both places that compare against `barge_in_min_ms`: `_listen_over` (reply audible, no turn open) and the short-voice/wake-ack branch in `_chunk`.
   - Size the barge ring from `max(barge_in_min_ms, barge_in_warmup_min_ms)` so a 600 ms barge-in keeps its onset.
   - Update the `set_speaking` docstring to mention the warm-up minimum.

3. `src/snow/voice/pipeline.py` `_load_tts`: when the canceller was built, set `self._engine.echo_warming = self._aec.warming`. A single attribute store is GIL-atomic; the audio thread reads it.

4. `tests/voice/test_bargein.py`: add the warm-up tests from the behavior block using the existing `make_rig`/`ask`/`start_reply`/`Rig.hear` helpers. Set `rig.turn.echo_warming = lambda: True` before the reply. `Rig.hear` feeds whole 512-sample chunks, so pick durations that land on or past the minimum (for example 640 ms for 600). Assert on `rig.aborts` and `rig.turn_pcm` as the existing tests do.

5. `tests/voice/test_echo_cancel.py`: widen the warm-residual test to the parametrized sweep, and add the double-talk, thread-stress and failure tests from the behavior block. For the pipeline fallback test, reuse the Task 1 pipeline-wiring construction with `echo_cancel=True` and play a reply to drained with the fake speaker. Keep thresholds as stated. If one fails, report the observed number in the SUMMARY rather than loosening it.
  </action>
  <verify>
    <automated>uv run pytest -q tests/voice/test_bargein.py tests/voice/test_turn_engine.py tests/voice/test_echo_cancel.py tests/voice/test_tts_pipeline.py</automated>
  </verify>
  <done>The first reply after start cannot be cut off by cold-start residual: barge-in needs 600 ms while warming, 250 ms after. Double-talk and the warm-residual sweep pass through the real APM. Concurrent render/capture is safe. A failing or missing livekit falls back to pass-through without stopping the voice.</done>
</task>

<task type="auto">
  <name>Task 3: Turn it on for the live worker, add the hand-run hardware test, run every gate</name>
  <files>src/snow/voice/tts/config.py, config/tts.toml, src/snow/voice/__main__.py, src/snow/voice/pipeline.py, tests/hardware/test_echo_cancel.py</files>
  <action>
1. `src/snow/voice/tts/config.py` `PlayoutConfig`: add the required field `echo_cancellation: bool`. Reword the `assume_headphones` comment, which currently says there is no echo cancellation in v1. New meaning: with headphones on, the echo canceller is not needed; with speakers, barge-in relies on it.

2. `config/tts.toml` `[playout]`: set `assume_headphones = false` and add `echo_cancellation = true`. Rewrite the stale VOIC-06 comment block above them. New text: WebRTC echo cancellation (livekit) removes Snow's own voice from the mic, so speakers work and barge-in does not hear Snow. A startup warning is logged only when both settings are false.

3. `src/snow/voice/__main__.py`: pass `echo_cancel=tts_cfg.playout.echo_cancellation` to `build_pipeline`. That call uses the live `MicSource`; devinput's FileSource path stays off.

4. `src/snow/voice/pipeline.py` `start()`: log the existing `speakers_without_echo_cancellation barge_in_hears_snow` warning only when `tts_cfg` is set, `assume_headphones` is false and `self._echo_cancel` is false.

5. Create `tests/hardware/test_echo_cancel.py` with `pytestmark = pytest.mark.hardware`. The executor must not run it: it opens the real mic and plays through the real speakers.
   - Header docstring in the style of tests/hardware/test_latency.py, covering:
     - Setup: run by hand on the laptop, speakers on (no headphones), normal volume, room quiet. Quit or mute Snow first, so its worker neither hears the test nor answers it.
     - Command: `uv run pytest -m hardware tests/hardware/test_echo_cancel.py -x -q -s`.
     - Data: nothing is written, all audio stays in memory.
     - Variants to report in the SUMMARY: FxSound Speakers as default vs FxSound effects off (or another output device).
   - Module-level or fixture setup: load `voice.toml`/`tts.toml` with `load_config`. Build a real `EchoCanceller(cfg.audio.sample_rate, 24000)`, a real `Playout(24000, tts_cfg.playout, on_render=aec.render)` on the default device, and a real `MicSource(cfg.audio.input_device, cfg.audio.sample_rate, cfg.audio.frame_samples)`. Its on_frame appends the raw frame and `aec.capture(frame)` to two in-memory Python lists. Nothing is opened at import time.
   - Test 1, Snow alone: play fixture speech (phrase_thats_all, tone_calm and phrase_go_to_sleep via `read_wav(..., 24000)`, float32 / 32768, repeated to about 12 s) with `start_utterance`/`push`/`end_utterance`, wait for it to drain, then close the playout and mic.
     - Print: the device stream latencies (read the private `_stream.latency` of Playout and MicSource with `# noqa: SLF001`), raw vs processed RMS per second, and the cold-start residual (longest VAD run in the first 3 s, informational).
     - Assert: ERLE after 3 s is at least 15 dB (looser than synthetic); the longest processed VAD run (real `VadDetector`, `CFG.turn.vad_threshold`) after 3 s is under `CFG.turn.barge_in_min_ms`.
     - On ERLE failure, the message tells the user to measure the real loopback delay and retry with FxSound effects off (research pitfalls 3 and 4).
   - Test 2, talk over Snow: start a new 10 s playback, warm the canceller for 3 s, then print a prompt asking the user to say a sentence over Snow now. Assert a processed VAD run of at least `CFG.turn.barge_in_min_ms` occurs within the next 6 s.
   - Every frame stays in Python lists in memory; nothing goes to disk.

6. Run every gate from the repo root and fix what fails:
   - `uv run pytest -q -m "not hardware and not gpu and not network"`. Known pre-existing failure: `tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env` errors while the user's real Snow hub is running (single-instance lock). Note it; do not fix it here.
   - `uv run ruff check src tests`
   - `uv run ruff format --check src tests`
   - `uv run pyright`
   - `uv run python -m snow.contracts.export --check`
   - `uv run pytest -q -m hardware tests/hardware/test_echo_cancel.py --collect-only`: collection only, opens no device.
   - `uv run pip-audit`: report the result. A network failure is reported, not treated as fatal.

   In the SUMMARY, list the new lock packages (expected: livekit 1.1.20 and types-protobuf 7.35.1.20260906) and give the user the hardware command. Never kill processes by image name. Never `cd`.
  </action>
  <verify>
    <automated>uv run pytest -q -m "not hardware and not gpu and not network" && uv run ruff check src tests && uv run ruff format --check src tests && uv run pyright && uv run python -m snow.contracts.export --check && uv run pytest -q -m hardware tests/hardware/test_echo_cancel.py --collect-only</automated>
    <human-check>End of task, run by the user (not the executor): with Snow quit or muted and the speakers on, run `uv run pytest -m hardware tests/hardware/test_echo_cancel.py -x -q -s`. Expect ERLE of at least 15 dB, no barge-in-length residual after 3 s, and the talk-over test passing. Then restart Snow on speakers: it should no longer transcribe itself or cut its own reply after 250 ms. Report the printed latencies and the FxSound on/off variant.</human-check>
  </verify>
  <done>The live worker runs echo cancellation on speakers by default, and the headphone warning is gone unless both settings are off. The hardware test exists, collects, and writes nothing. All CI gates pass, except the documented pre-existing hub-lock error if Snow is running. The SUMMARY lists the new lock packages, the pip-audit result and the hardware command.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| PyPI -> voice worker process | A new native library (`livekit_ffi.dll`, about 24 MB) is loaded into the process that holds the mic |
| Speaker -> microphone (acoustic) | Snow's own output and room/TV audio come back in as if they were the user's commands |
| Python -> native FFI | Frame buffers cross into Rust; a malformed size aborts the whole interpreter |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-glq-01 | Denial of service | `EchoCanceller.capture` / `render` (FFI) | high | mitigate | Size check raises ValueError before any native call (Rust panic otherwise kills the process); unit-tested with 100/170-sample frames and a 22050 Hz rate (Task 1) |
| T-glq-02 | Denial of service | `Playout._callback` (PortAudio output thread) | high | mitigate | `render()` catches every exception and switches to pass-through; an exception escaping a PortAudio callback would stop Snow's voice. Failure test in Task 2 |
| T-glq-03 | Denial of service | livekit import / APM construction | medium | mitigate | Built in `asyncio.to_thread` after the voice loads; any failure logs `aec_unavailable` and audio passes through unchanged (Task 1, tested in Task 2) |
| T-glq-04 | Information disclosure | mic / reference audio | medium | mitigate | Memory only (D-18): no file writers in aec.py or either test file; no livekit `Room` is created, so no network; `tests/voice/test_no_egress.py` stays in the Task 1 verify |
| T-glq-05 | Spoofing | Snow's own voice acting as the user (self-transcription, self-barge-in) | medium | mitigate | AEC3 on every live mic frame before wake/VAD/STT, plus the 600 ms warm-up barge-in minimum for the first ~2 s of reference. Residual risk (a cold-start residual during a wake acknowledgement could still open a short turn) is accepted until the hardware run; speaker verification is a later phase |
| T-glq-SC | Tampering | `uv add livekit==1.1.20` | high | mitigate | Package pre-approved by the user in this task's description and listed in the project stack (CLAUDE.md). The research seam verdict is SUS only because download data was missing and the *latest* release is new; 1.1.20 itself is 25 days old from github.com/livekit/python-sdks. Pin exact, hash-locked `uv.lock`; the executor stops if any new package other than livekit/types-protobuf or any version change appears; `pip-audit` runs in Task 3 |
</threat_model>

<verification>
- Task 1 and Task 2 automated commands pass, including tests/voice/test_no_egress.py.
- Full gate set passes: `uv run pytest -q -m "not hardware and not gpu and not network"`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pyright`, `uv run python -m snow.contracts.export --check` (pre-existing hub-lock error in tests/test_cli.py is acceptable only while the user's Snow hub runs).
- `git diff uv.lock` adds only livekit and types-protobuf.
- Hardware test collects with `-m hardware --collect-only` and is not executed by the executor.
</verification>

<success_criteria>
- Synthetic echo through the real APM: raw mic barges in (precondition), cleaned mic never reaches a 250 ms VAD run once warm across 12 seed/delay cases, ERLE at least 20 dB.
- User speech over echo still produces a barge-in-length VAD run within 0.7 s, keeping at least 70% of its VAD chunks.
- The first ~2 s of reference use the 600 ms barge-in minimum; steady state stays 250 ms.
- config/tts.toml ships `assume_headphones = false` and `echo_cancellation = true`; the worker enables the canceller; the canceller fails open to pass-through.
- The user has a one-command hardware test that writes nothing.
</success_criteria>

<output>
Create `.planning/quick/261018-glq-real-echo-cancellation-livekit-apm-so-sn/261018-glq-SUMMARY.md` with `status: complete` in its frontmatter. Include: the new lock packages, measured test numbers if any differ from research, the pip-audit result, and the hardware command for the user.
</output>
