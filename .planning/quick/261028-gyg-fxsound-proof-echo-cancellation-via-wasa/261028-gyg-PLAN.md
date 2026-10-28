---
phase: quick-261028-gyg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - uv.lock
  - src/snow/voice/aec.py
  - src/snow/voice/loopback.py
  - src/snow/voice/config.py
  - config/voice.toml
  - src/snow/voice/pipeline.py
  - src/snow/voice/turn.py
  - src/snow/voice/playout.py
  - tests/voice/conftest.py
  - tests/voice/test_loopback.py
  - tests/hardware/test_bargein_loopback.py
autonomous: true
requirements: [VOIC-06]

estimate:
  tokens: 110000
  raw_tokens: 110000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "With FxSound (or any output enhancer) on, Snow's own voice no longer pauses Snow. The echo canceller's reference is a WASAPI loopback of the speaker endpoint the audio finally reaches (the Realtek speakers behind FxSound), so the reference is the post-enhancer signal the mic hears."
    - "Snow logs which reference it uses at start and on every change: `aec_reference=loopback device=... rate=... channels=...` or `aec_reference=render reason=...`. When the loopback is unavailable, lost, ambiguous or silently dead, Snow switches to the render reference (Playout.on_render) at once and retries the loopback in the background."
    - "Loopback audio stays in memory only. It is never written to disk, never logged and never sent anywhere. Logs carry device names, rates and reasons only."
    - "Loopback audio is downmixed to mono and resampled to the canceller's render rate. When nothing plays, the reference keeps flowing as zeros. A stalled mic cannot build a reference backlog over 200 ms. Switching the reference re-warms the canceller."
    - "Every other sound the PC plays (videos, music) is in the loopback reference too, so it is also cancelled from the mic."
    - "With `[audio] enhancer_disables_bargein = true` (default false), an output enhancer as the default output and no live loopback, plain speech over Snow never pauses it. Saying 'Hey Snow' still interrupts."
    - "The hardware loopback suite has an FxSound-style scenario: EQ, dynamic gain and saturation are applied after the render reference. It either ran, or it is recorded SKIPPED-PENDING because Snow was running."
  artifacts:
    - path: src/snow/voice/loopback.py
      provides: "is_enhancer, pick_endpoint, LoopbackReference (PyAudioWPatch loopback, downmix, soxr resample, supervisor with fallback and retry)"
    - path: src/snow/voice/aec.py
      provides: "EchoCanceller.use_loopback / loopback_block / loopback_stale, public render_rate and loopback flag, mic-thread drain with zero fill"
    - path: src/snow/voice/config.py
      provides: "AudioConfig.aec_reference, aec_reference_device, output_enhancers, enhancer_disables_bargein"
    - path: config/voice.toml
      provides: "aec_reference = \"loopback\", output_enhancers = [\"FxSound\"], enhancer_disables_bargein = false"
    - path: tests/voice/test_loopback.py
      provides: "fake-PyAudio tests: FX echo cancelled via loopback, switching, downmix/resample, silence, device loss, no disk writes, pipeline wiring, wake-only gate"
    - path: tests/hardware/test_bargein_loopback.py
      provides: "FxSound-style scenarios (loopback asserts, render recorded); room scenarios pinned to the render reference"
  key_links:
    - from: src/snow/voice/pipeline.py _load_tts
      to: LoopbackReference(aec, cfg.audio.aec_reference_device, cfg.audio.output_enhancers).start()
      via: "only when echo_cancel is on, the canceller loaded and cfg.audio.aec_reference == \"loopback\""
    - from: LoopbackReference stream callback (PortAudio thread)
      to: EchoCanceller.loopback_block
      via: "float32 frames -> mean over channels -> soxr.ResampleStream to aec.render_rate"
    - from: EchoCanceller.capture (mic thread)
      to: apm.process_reverse_stream
      via: "drains the queued 10 ms loopback frames (or zero frames when none) before cleaning the frame"
    - from: Playout.on_render -> EchoCanceller.render
      to: "ignored while EchoCanceller.loopback is True"
      via: "early return, after it notes Snow's own loudness for the liveness check"
    - from: src/snow/voice/turn.py _listen_over episode start
      to: TurnEngine.speech_barge_in
      via: "a new episode starts only if speech_barge_in() is True; on_wake is untouched"
---

<objective>
FxSound-proof echo cancellation (ROADMAP backlog 999.2, promoted by the user on 2026-10-28; the new package PyAudioWPatch is user-approved).

FxSound is a virtual default output. It processes all audio and forwards it to "Speakers (Realtek(R) Audio)". Snow's WebRTC AEC3 takes its reference from Playout.on_render, which is Snow's audio before FxSound, so the reference no longer matches what the mic hears. Measured on 2026-10-28: 5 self-triggered barge-in pauses in 3 minutes with FxSound on, 0 with it off. The speaker-verification margin is also thin (user 0.41, Snow 0.26, threshold 0.33).

This plan feeds the canceller a WASAPI loopback of the endpoint the audio actually reaches, as the render reference. It falls back to the current reference whenever the loopback is unavailable. It adds an off-by-default wake-only fallback (gap study step 1), and a hardware scenario that simulates FxSound.

Purpose: the user keeps FxSound on and Snow stops hearing, and pausing for, its own voice.
Output: the code, config and tests in files_modified. PyAudioWPatch 0.2.12.9 is the only new package. Scope stays in src/snow/voice, tests/voice, tests/hardware, config/voice.toml, pyproject.toml and uv.lock. Another session owns src/snow/hub and src/snow/brain.
</objective>

<execution_context>
@.claude/gsd-core/workflows/execute-plan.md
@.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@.planning/seeds/openjarvis-gap-study.md
@.planning/quick/261026-wvr-robust-jarvis-style-barge-in-on-laptop-m/261026-wvr-RESEARCH.md
@.planning/quick/261027-rx2-instant-stop-on-the-user-s-voice-plus-in/261027-rx2-SUMMARY.md
@src/snow/voice/aec.py
@src/snow/voice/playout.py
@src/snow/voice/config.py
@config/voice.toml
@tests/voice/test_echo_cancel.py
@tests/hardware/test_bargein_loopback.py

<operating_rules>
- Snow is running right now from `.venv\Scripts\snow.exe run` (with `python -m snow.voice` and `python -m snow.brain`). Never stop, restart or kill it.
- Once pyproject.toml changes, a plain `uv run` re-syncs the project. That reinstall rewrites the locked `.venv\Scripts\snow.exe` and fails. So every gate in this plan uses `uv run --no-sync`: the same tools in the same venv. The orchestrator's gates (`uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pyright`, `uv run pytest -q tests/voice`) are run in exactly that form, with `--no-sync` added.
- Never `cd`. Run from the repo root and use tool directory flags.
- Audio never goes to disk or into logs (D-18).
</operating_rules>

<interfaces>
PyAudioWPatch 0.2.12.9. Verified from the source of `pyaudiowpatch/__init__.py` (module name `pyaudiowpatch`, a fork of PyAudio with the same API):
- `PyAudio()` and `.terminate()`. Use `.get_device_info_generator_by_host_api(host_api_type=paWASAPI)` to iterate WASAPI device dicts.
- Device dict keys: `index`, `name`, `maxInputChannels`, `maxOutputChannels`, `defaultSampleRate`, `isLoopbackDevice`.
- `.get_default_wasapi_device(d_out=True)` returns the dict of the default WASAPI output (OSError if there is no WASAPI).
- `.get_wasapi_loopback_analogue_by_dict(info)` returns the loopback input dict of an output device (LookupError if none, ValueError if not an output). It matches by name, and the loopback devices are input devices listed at the end.
- `.open(format=paFloat32, channels=ch, rate=rate, input=True, input_device_index=idx, frames_per_buffer=n, stream_callback=cb)` returns a Stream. Stream methods: `.is_active()`, `.stop_stream()`, `.close()`.
- The callback is `cb(in_data, frame_count, time_info, status) -> (None, paContinue | paAbort)`. If the callback raises, PyAudio prints a traceback and aborts the stream, so the callback must catch everything itself.
- Module constants: `paWASAPI`, `paFloat32`, `paContinue`, `paAbort`.
- WASAPI loopback delivers no packets while nothing plays on the endpoint.

Machine today (sounddevice WASAPI): output 10 "Speakers (Realtek(R) Audio)" (2 ch, 48000), and output 11 "FxSound Speakers (FxSound Audio Enhancer)" (2 ch, 48000). The default is currently Realtek (FxSound is off).

Existing code the tasks build on:
- `EchoCanceller(capture_rate, render_rate)` in `src/snow/voice/aec.py`: `render(block)` runs on the Playout thread, `capture(frame)` on the mic thread, `warming()` with `reference_s` and `WARMUP_S = 2.0`, `_REF_FLOOR` at -50 dBFS, `_fail()` drops to pass-through, `close()`. There is deliberately no `set_stream_delay_ms` call (aec.py lines 44-45; RESEARCH section 4: "Do not spend time on it again"). APM frames are exactly 10 ms.
- `soxr` 1.0.0 is installed and has `soxr.ResampleStream(in_rate, out_rate, num_channels, dtype="float32")` with `.resample_chunk(x)`.
- In `pipeline.py`, `_load_tts` creates the canceller with `EchoCanceller(cfg.audio.sample_rate, rate)`, where `rate = device_rate() or router.sample_rate`, and wires `Playout(on_render=aec.render)`. `stop()` closes the canceller.
- The tests reuse helpers from `tests/voice/test_echo_cancel.py` (`Scene`, `far_of`, `echo_of`, `noise`, `to_pcm`, `drive`, `longest_run_ms`, `erle_db`, `SR`, `TR`, `FRAME`, `MIN_RUN_MS`), from `tests/voice/test_bargein.py` (`make_rig`, `HoldEngine`, `ask`, `start_reply`), from `tests/voice/test_turn_engine.py` (`Vad`, `wake`, `speak`, `Over`) and from `tests/voice/test_no_egress.py` (the wave.open spy pattern).
</interfaces>

<package_legitimacy_audit>
| Package | Version | Registry evidence (checked 2026-10-28) | Status |
|---------|---------|----------------------------------------|--------|
| pyaudiowpatch | ==0.2.12.9 | pypi.org/project/PyAudioWPatch: author "Hubert Pham (S0D3S edition)", homepage github.com/s0d3s/PyAudioWPatch, releases since 2022-09-06 (7), cp312 win_amd64 wheel uploaded 2026-10-06 (before exclude-newer 2026-10-08), no runtime dependencies, Apache-2.0 | VERIFIED + USER-APPROVED (planning_context, 2026-10-28): no human checkpoint needed |
</package_legitimacy_audit>
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1 (tracer): FX-processed echo is cancelled through a WASAPI loopback reference (dependency, canceller intake, loopback module)</name>
  <files>pyproject.toml, uv.lock, src/snow/voice/aec.py, src/snow/voice/loopback.py, tests/voice/test_loopback.py</files>
  <behavior>
    - Tracer: a deterministic FxSound-style chain (a slow gain wobble of about ±6 dB, like compressor pumping, then tanh saturation) is applied to Snow's voice. Snow's raw voice goes into render() (the old reference). The FX version goes to the mic as echo, built with the room helpers from test_echo_cancel. The render path then shows the bug. The same FX signal is delivered as 48 kHz stereo float32 packets through LoopbackReference with a fake pyaudiowpatch module, into an EchoCanceller(16000, 24000). That path leaves no barge-in-length run (`longest_run_ms(out, utt2_s) < MIN_RUN_MS`) and gives ERLE of 20 dB or more from `utt2_s + 1.0`, the same bar as test_warm_echo_never_reaches_a_barge_in_length_run.
    - The bug is reproduced: with the render reference the same scene leaves a run of at least MIN_RUN_MS. If AEC3's suppressor hides that, assert instead that the loopback ERLE beats the render ERLE by 6 dB or more. Strengthen the FX (larger and faster gain swings) until one of the two holds, and record the measured numbers in the SUMMARY.
    - Switching: with use_loopback(True), render() blocks never reach the APM, and a queued loopback block is fed on the next capture(). With use_loopback(False), render() feeds again and the queue is empty. reference_s resets to 0.0 on every switch. Use a recording fake `_apm` like `_Broken` in test_echo_cancel, counting process_reverse_stream calls.
    - Silence: when loopback is on and the queue is empty, capture() feeds exactly len(frame) // (capture_rate // 100) zero frames of render_rate // 100 samples.
    - Bounded: 1 s of loopback_block with no capture leaves at most 20 queued frames.
    - Downmix and resample: a 1 kHz sine on both channels at 48 kHz arrives at the canceller at 24 kHz with RMS within 5% and about half the sample count. A left-only sine arrives at half amplitude (a channel mean, not channel 0).
    - Device loss: the fake stream turns inactive. The canceller is back on render (`aec.loopback is False`), `aec_reference=render reason=loopback_lost` is logged, and after retry_s the stream is reopened (`aec.loopback is True`, 2 opens). Liveness: the stream stays active but stops delivering while render() keeps getting loud blocks. After stale_s, the same fallback happens.
    - Unavailable: the fake PyAudio() raises OSError. The loopback stays off and `aec_reference=render reason=OSError` is logged once across several retries. An ambiguous endpoint (FxSound default with two real outputs) logs reason=no_endpoint once.
    - A malformed packet (byte length not divisible by channels × 4) makes the callback return (None, paAbort) without raising, and logs `aec_loopback_failed kind=ValueError` once.
    - pick_endpoint table: the default real output gives the default. An FxSound default with one real output gives that real output. An FxSound default with two real outputs gives None. A configured device substring is matched case-insensitively; one that matches nothing gives None.
    - No disk writes and nothing logged: during a full loopback session (open, 1 s of packets, captures, loss, close), spies on builtins.open (write, append, create and update modes), wave.open (write) and soundfile.write record nothing. Every captured log message starts with "aec_" and is under 200 characters.
  </behavior>
  <action>
    Step 1, dependency (user-approved, see package_legitimacy_audit). Run `uv add --no-sync "pyaudiowpatch==0.2.12.9"`. Then run `uv sync --inexact --no-install-project`, which installs only the locked, hash-checked wheel and does not reinstall the running project. 0.2.12.9 predates the exclude-newer cutoff, so add no `exclude-newer-package` override. If the sync still fails on a locked file, stop and report the exact uv error. Never stop Snow to get around it. pyproject.toml gains only the `"pyaudiowpatch==0.2.12.9"` dependency line.

    Step 2, `src/snow/voice/aec.py` (VOIC-06, D-18 memory only).
    - Make the render rate public as `render_rate` and add a public `loopback: bool = False`.
    - Add a `collections.deque` of int16 10 ms render-rate frames with maxlen 20 (`_REF_QUEUE`, 200 ms: steady state holds about one 80 ms mic frame; the cap only bites when capture stalls, for example while muted).
    - Add a loopback-thread remainder, `_loop_at` (time.monotonic of the last loopback block) and `_render_loud_at` (the last render block above `_REF_FLOOR`).
    - `use_loopback(on)` sets the flag, clears the queue and remainder, sets `_loop_at` to now and resets `reference_s` to 0.0, so a new reference re-warms the canceller.
    - `loopback_block(block)` runs on the loopback thread and takes float32 mono at render_rate. It returns at once unless loopback is on and the APM is up. It converts the block to int16 the way render() does, prepends the remainder, appends whole render_rate // 100 frames to the queue and keeps the rest. It stamps `_loop_at` and adds to reference_s when the block is above the floor. It does not catch exceptions: the LoopbackReference callback catches them and aborts the stream, so a loopback glitch never disables the whole canceller.
    - `loopback_stale(after_s)` is true when `_render_loud_at - _loop_at > after_s`, meaning Snow has been audible for that long with no loopback packet.
    - render() works out once whether the block is above the floor, stamps `_render_loud_at` if it is, then returns early while loopback is on. Otherwise it behaves as today.
    - capture(), inside its existing try and only when loopback is on, first pops every queued frame into `apm.process_reverse_stream` (same AudioFrame construction as render). If the queue was empty it feeds len(frame) // self._cn zero frames instead: WASAPI loopback sends nothing while the endpoint is silent, and the render timeline must keep pace with capture.
    - The mic thread does all loopback render calls, and draining everything before each capture follows the loopback clock. AEC3 estimates the short, stable loopback-to-mic delay and tracks drift itself. Keep the no-delay-hint comment.
    - Update the module docstring to cover the two references and to say that every PC sound is in the loopback reference, so videos and music are cancelled too.

    Step 3, new `src/snow/voice/loopback.py`.
    - `is_enhancer(name, enhancers)`: a case-insensitive substring match.
    - `pick_endpoint(outputs, default, device, enhancers) -> str | None`. If a device is configured, return the first output containing it (case-insensitive), else None. Otherwise return the default output, unless it is an enhancer. In that case return the single non-enhancer output, else None. The reason for this rule: an enhancer's virtual device is loopback before processing, and the real speakers behind it are after processing.
    - `LoopbackReference(aec, device="", enhancers=(), *, pa=None, check_s=1.0, retry_s=10.0, stale_s=1.0)`. `start()` runs a daemon supervisor thread named "snow-aec-loopback". `close()` sets a stop Event and joins with a 3 s timeout. Every PyAudioWPatch call (create, enumerate, open, is_active, stop, close, terminate) happens on that one thread, because PortAudio's WASAPI COM setup is per thread.
    - Load the module lazily as `Any`, via `pa or importlib.import_module("pyaudiowpatch")`, so pyright strict sees no unknown types and the import cost is paid only when used. An ImportError becomes reason ImportError.
    - Open: make a fresh PyAudio(). List the WASAPI outputs (maxOutputChannels > 0 and not isLoopbackDevice) and the default output name. Pick the endpoint (None gives reason no_endpoint). Get its loopback analogue and take rate and channels from it. Make a soxr.ResampleStream(rate, aec.render_rate, 1, dtype "float32") only when the rates differ. Open with format paFloat32, input=True, frames_per_buffer rate // 100 and the callback.
    - The callback reads np.frombuffer(in_data, float32), reshapes it to (-1, channels), takes the mean over channels, resamples it and calls aec.loopback_block. It returns (None, paContinue). On any exception it logs `aec_loopback_failed kind=<type>` once and returns (None, paAbort).
    - Supervisor loop until stop. After a successful open, call `aec.use_loopback(True)` and log info `aec_reference=loopback device=%r rate=%d channels=%d`. Then wait in check_s steps while the stream is active (is_active, with exceptions counted as dead) and `not aec.loopback_stale(stale_s)`. When it ends, call `aec.use_loopback(False)` and tear down (stop, close and terminate, each suppressed). Unless stopping, log warning `aec_reference=render reason=loopback_lost device=%r`.
    - A failed open logs warning `aec_reference=render reason=<reason>` only when the reason differs from the last one (no spam). For no_endpoint, add "set audio.aec_reference_device". Then wait retry_s.
    - Logs never include audio, levels or buffers.

    Step 4, `tests/voice/test_loopback.py` with the cases in behavior. The fake module is a SimpleNamespace with PyAudio, paWASAPI, paFloat32, paContinue and paAbort. Its FakePyAudio serves configurable device dicts and records opens. Its FakeStream stores the callback and has a settable `active`. The test pumps the stored callback from the test thread, after polling until `aec.loopback` is True (2 s timeout). Use small check_s, retry_s and stale_s (about 0.01-0.05) so the suite stays fast.
  </action>
  <verify>
    <automated>uv lock --check</automated>
    <fails_when>non-zero exit: uv.lock does not match pyproject.toml</fails_when>
    <automated>git diff -U0 --output=.pytest_tmp/uv-lock.diff uv.lock && grep -E '^[+-]name = ' .pytest_tmp/uv-lock.diff</automated>
    <fails_when>git diff exits non-zero, or the grep output is anything other than the single line `+name = "pyaudiowpatch"` (another package was added, removed or bumped)</fails_when>
    <automated>uv run --no-sync python -c "import importlib.metadata as m, pyaudiowpatch; assert m.version('pyaudiowpatch') == '0.2.12.9'"</automated>
    <fails_when>ImportError, or an installed version other than 0.2.12.9</fails_when>
    <automated>uv run --no-sync pytest -q tests/voice/test_loopback.py tests/voice/test_echo_cancel.py</automated>
    <fails_when>any test fails or errors, or test_loopback.py collects fewer than 10 tests</fails_when>
  </verify>
  <done>An FX-processed echo is cancelled to 20 dB or more of ERLE, with no barge-in-length run, when the reference arrives through LoopbackReference. The render reference visibly fails the same scene. Switching, silence, bounding, downmix and resample, loss, liveness, unavailability and no-disk tests pass. The existing echo-cancel tests still pass unchanged.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Snow uses the loopback reference live (config, voice.toml, pipeline wiring, test isolation)</name>
  <files>src/snow/voice/config.py, config/voice.toml, src/snow/voice/pipeline.py, tests/voice/conftest.py, tests/voice/test_loopback.py</files>
  <behavior>
    - With echo_cancel=True and aec_reference "loopback" (voice.toml), make_rig's pipeline creates exactly one LoopbackReference. It is passed the pipeline's canceller and cfg.audio.aec_reference_device and output_enhancers, and it is started. After `await pipeline.stop()` it is closed.
    - With aec_reference "render", no LoopbackReference is made and `aec_reference=render reason=config` is logged once.
    - With echo_cancel=False, or a canceller that failed to load (existing test test_a_canceller_that_cannot_load_leaves_the_voice_working), none is made.
    - voice.toml loads as aec_reference "loopback", aec_reference_device "", output_enhancers ["FxSound"], enhancer_disables_bargein false. An unknown value such as "loop" fails validation (Literal).
    - No test in tests/voice opens a real loopback device.
  </behavior>
  <action>
    `src/snow/voice/config.py`: add these AudioConfig fields, with one-line why-comments.
    - `aec_reference: Literal["loopback", "render"] = "render"`. The model default keeps the old behavior for configs without the key; voice.toml opts in.
    - `aec_reference_device: str = ""`
    - `output_enhancers: list[str] = []`
    - `enhancer_disables_bargein: bool = False`. It is consumed in Task 3.

    `config/voice.toml` [audio]: add the four keys with short comments in the file's style.
    - aec_reference = "loopback". The loopback is what the speakers really play, after FxSound or any enhancer, plus every other PC sound (videos and music are cancelled too). It falls back to "render" (Snow's own audio before any enhancer) whenever the loopback is unavailable. Audio stays in memory only.
    - aec_reference_device = "". Part of the speaker endpoint's name; empty means auto: the default output, or the one real output behind an enhancer.
    - output_enhancers = ["FxSound"]
    - enhancer_disables_bargein = false. When true, with an enhancer and no live loopback, only "Hey Snow" interrupts Snow.

    `src/snow/voice/pipeline.py`:
    - Import `LoopbackReference` from snow.voice.loopback as a module-level name, the same way EchoCanceller is imported, so tests can monkeypatch `snow.voice.pipeline.LoopbackReference`.
    - Add `self._loopback: LoopbackReference | None = None` next to `_aec`.
    - In `_load_tts`, after the canceller loads and before the Playout is built: if aec is not None and cfg.audio.aec_reference == "loopback", create LoopbackReference(aec, a.aec_reference_device, a.output_enhancers), start it and keep it. Its own thread logs which reference is live. Otherwise, when aec is not None, log info `aec_reference=render reason=config`.
    - Keep `on_render=aec.render` as it is (render() ignores blocks itself while the loopback is live).
    - In `stop()`, close the loopback before the canceller.
    - Do not touch src/snow/hub, src/snow/brain or the contracts.

    `tests/voice/conftest.py`: add an autouse fixture `loopbacks`. It monkeypatches `snow.voice.pipeline.LoopbackReference` with a recording fake that has `aec`, `device`, `enhancers`, `started` and `closed` attributes and no-op start and close, and it returns the list of fakes made. Every voice unit test (make_rig and setup(echo_cancel=True) included) is thereby kept off real audio devices.

    `tests/voice/test_loopback.py`: add the wiring tests in behavior. Use make_rig(echo_cancel=True) and the `loopbacks` fixture. For the "render" case, build the pipeline with a cfg copy whose audio has aec_reference "render" before start. The `setup()` path in test_tts_pipeline, or a model_copy of CFG passed to VoicePipeline, both work; pick whichever needs no edits to other test files.
  </action>
  <verify>
    <automated>uv run --no-sync python -c "from snow.config.settings import load_config; from snow.voice.config import VoiceConfig; a = load_config('voice.toml', VoiceConfig).audio; assert (a.aec_reference, a.aec_reference_device, a.output_enhancers, a.enhancer_disables_bargein) == ('loopback', '', ['FxSound'], False), a"</automated>
    <fails_when>a validation error, or any of the four values differs</fails_when>
    <automated>uv run --no-sync pytest -q tests/voice</automated>
    <fails_when>any test fails or errors (the existing echo_cancel=True rigs included)</fails_when>
  </verify>
  <done>The live voice worker starts the loopback reference whenever echo cancellation is on and voice.toml says "loopback". It logs which reference is live, closes the loopback on stop and needs no code change to switch back to "render". The whole voice suite passes without touching an audio device.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Optional wake-only fallback, FxSound-style hardware scenario, full gates</name>
  <files>src/snow/voice/turn.py, src/snow/voice/playout.py, src/snow/voice/pipeline.py, tests/voice/test_loopback.py, tests/hardware/test_bargein_loopback.py</files>
  <behavior>
    - TurnEngine with `speech_barge_in = lambda: False` while a reply is audible: speech over Snow (the `Over` helper from test_turn_engine) never calls pause and never calls check. The wake phrase still cuts the reply.
    - With the default (True), the existing barge-in tests are unchanged.
    - Pipeline gate: with enhancer_disables_bargein true, a default output name matching output_enhancers (monkeypatch `snow.voice.pipeline.default_output_name`) and a canceller whose loopback flag is False, `engine.speech_barge_in()` is False. Set the flag True and it becomes True. With enhancer_disables_bargein false, or a non-enhancer default output, it is always True.
  </behavior>
  <action>
    `src/snow/voice/turn.py`: add a public hook next to echo_warming and pause: `self.speech_barge_in: Callable[[], bool] = lambda: True`, set by the pipeline. In `_listen_over`, a new episode starts only when the chunk is speech and `self.speech_barge_in()` is True. That is the `if self._barge_span == 0` branch, so an episode already running finishes normally. on_wake and the wake cut path are untouched (gap study step 1: Snow never says "Hey Snow", so its echo cannot trigger the wake word).

    `src/snow/voice/playout.py`: add `default_output_name() -> str` next to device_rate(). It reuses `_wasapi_output()` and returns "" on any error. Mark it with the same shortcut comment style: the name is read once at voice load.

    `src/snow/voice/pipeline.py` `_load_tts`: when cfg.audio.enhancer_disables_bargein is true and `is_enhancer(default_output_name(), cfg.audio.output_enhancers)`, set `engine.speech_barge_in` to a lambda that is True only while the canceller exists and its loopback flag is True. Log one warning at load with the enhancer name: `speech_barge_in=wake_only_without_loopback output_enhancer=%r`. The flag defaults to off. The HUD shows nothing about it here; hub and contracts belong to the other session.

    `tests/hardware/test_bargein_loopback.py`:
    - Give `running()` the keyword arguments `reference: str = "render"` and `fx: bool = False`. Build the pipeline with a CFG copy whose audio.aec_reference is `reference`. When fx is set, pass a stream_factory that wraps `snow.voice.playout._device_stream`'s callback. The wrapper runs the real callback first, which hands the clean block to on_render as the render reference. It then processes outdata[:, 0] in place with an `FxStyle` stage, so the speakers play the processed signal like FxSound.
    - FxStyle has three stages, all in numpy, cheap and deterministic: a 129-tap FIR bass boost (0.6 times identity plus 0.4 times a windowed-sinc low-pass near 250 Hz), applied with a carried history; a per-block AGC/compressor gain of clip(0.25 / rms, 0.5, 4.0), smoothed by 0.3 per block; then tanh saturation with drive 1.8, normalised, clipped to ±1.
    - For reference "loopback", wait up to 10 s for the canceller's loopback flag before yielding, and fail with the captured `aec_reference` log lines if it never comes up.
    - The existing room-sound scenarios keep the default "render". The module docstring says why: room sounds play through the PC, so a loopback reference would cancel them and they would no longer stand in for a person in the room.
    - Add `test_fxsound_style_output_with_the_loopback_reference_never_pauses_snow`: enrolled, 3 replies, no cut-offs, all completed, no pauses in reply index 1 or later, loopback live.
    - Add `test_fxsound_style_output_with_the_render_reference_is_recorded`: the old reference as a control. It reports pauses; only a crash or an incomplete run fails.

    Then run the full gates. Then run the hardware command below. Snow is running now, so the module's `snow_must_be_quit` fixture is expected to skip it. Record SKIPPED-PENDING in the SUMMARY with the exact command for the orchestrator to run later with the user, after quitting Snow, with FxSound on: `uv run pytest -m hardware tests/hardware/test_bargein_loopback.py -x -q -s`. Never stop Snow to run it.

    The SUMMARY also notes:
    - the bonus: every sound the PC plays is cancelled;
    - assumption A1: the Realtek driver's own endpoint effects may or may not be in the loopback, and the hardware run settles it;
    - the edge where Snow plays to a different endpoint than the loopback, which the liveness check turns into a render fallback with a retry every 10 s;
    - that the user must restart Snow to pick up the change, after which a normal `uv sync` refreshes the project install.
  </action>
  <verify>
    <automated>uv run --no-sync ruff check src tests</automated>
    <fails_when>any lint error</fails_when>
    <automated>uv run --no-sync ruff format --check src tests</automated>
    <fails_when>any file would be reformatted</fails_when>
    <automated>uv run --no-sync pyright</automated>
    <fails_when>any error (strict mode on src/snow)</fails_when>
    <automated>uv run --no-sync pytest -q tests/voice</automated>
    <fails_when>any test fails or errors</fails_when>
    <automated>uv run --no-sync pytest -m hardware tests/hardware/test_bargein_loopback.py --collect-only -q</automated>
    <fails_when>an import or collection error, or either of the two fxsound_style tests is not listed</fails_when>
    <automated>uv run --no-sync pytest -m hardware tests/hardware/test_bargein_loopback.py -k fxsound -x -q -s -rs</automated>
    <fails_when>any failure or error. A skip whose reason is "Snow is running" or "loopback is not live" is not a failure: record it as SKIPPED-PENDING with that reason</fails_when>
  </verify>
  <done>The wake-only fallback is off by default and covered by tests. The hardware suite holds the FxSound-style scenarios and pins its room scenarios to the render reference. All four orchestrator gates pass in their --no-sync form. The hardware run is either recorded with its numbers or marked SKIPPED-PENDING, with the command to run later.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Windows audio engine -> Snow (loopback capture) | Every sound the PC plays (calls, media, notifications) now enters Snow's process |
| PortAudio callback thread -> Snow | Native thread; an exception there aborts the stream |
| PyPI -> .venv | A new native extension (PyAudioWPatch, statically linked PortAudio) |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-gyg-01 | Information disclosure | LoopbackReference callback, EchoCanceller queue | high | mitigate | Frames live only in a bounded 200 ms in-memory deque that the APM consumes. There is no file, log or network sink. Logs carry device names, rates and reasons only. test_loopback spies on builtins.open, wave.open and soundfile.write and checks every log message (Task 1). |
| T-gyg-02 | Denial of service | Echo reference (a dead, silent or wrong loopback would leave Snow hearing itself) | medium | mitigate | Liveness: an inactive stream, or Snow audible with no loopback packet for stale_s (1 s), switches back to the render reference at once, with a background retry every 10 s. An ambiguous endpoint never guesses; it falls back and logs reason=no_endpoint. |
| T-gyg-03 | Tampering / DoS | PortAudio callback | medium | mitigate | The callback catches everything and returns paAbort, which leads to the render fallback. All PyAudio calls run on one supervisor thread. A loopback glitch never disables the canceller. |
| T-gyg-04 | Spoofing | Barge-in | low | accept | Audio the PC plays itself (including a recording of the user's voice) is now cancelled and cannot barge in. That is the intended bonus. The wake word and speaker verification paths are unchanged. |
| T-gyg-05 | Denial of service | Wake-only fallback | low | accept | Off by default (enhancer_disables_bargein = false). When armed, "Hey Snow" still interrupts, and the mode is logged at load. |
| T-gyg-SC | Tampering | uv add pyaudiowpatch | high | mitigate | Exact pin ==0.2.12.9, recorded with hashes in uv.lock. Published 2026-10-06, inside the exclude-newer window, with no runtime dependencies. Verified on pypi.org and user-approved 2026-10-28 (package_legitimacy_audit). `uv lock --check` passes, and the lock diff adds only that package. |
</threat_model>

<source_audit>
| Source | Item | Covered by |
|--------|------|------------|
| GOAL | Backlog 999.2: FxSound-proof echo cancellation | Tasks 1-3 |
| REQ | VOIC-06 barge-in without self-interruption | Tasks 1-3 |
| RESEARCH | AEC3 10 ms frames; no set_stream_delay_ms; delay estimated by AEC3 (261026-wvr RESEARCH section 4) | Task 1 (aec.py) |
| CONTEXT | Loopback reference via PyAudioWPatch, pinned and hash-locked, exclude-newer respected | Task 1 |
| CONTEXT | Endpoint = where the final audio goes (Realtek behind FxSound), auto or configured; fall back to on_render; log which one is used | Tasks 1-2 |
| CONTEXT | In memory only, never stored or logged | Task 1 (test), T-gyg-01 |
| CONTEXT | Resample and downmix; drift and delay; silence; device change or loss | Task 1 |
| CONTEXT | Bonus: other PC sounds cancelled, noted | Task 1 docstring, Task 2 voice.toml comment, SUMMARY |
| CONTEXT | Optional wake-only fallback, config, default off | Task 3 |
| CONTEXT | Unit tests with fakes; hardware FxSound-style scenario; SKIPPED-PENDING if Snow runs | Tasks 1-3 |
| CONTEXT | Gates: ruff check, ruff format --check, pyright, pytest tests/voice | Task 3 |
| Excluded | HUD indicator for the wake-only mode (gap study) | Out of scope: hub and contracts belong to the parallel session; logged only |
</source_audit>

<verification>
- `uv lock --check` passes. The uv.lock diff adds only pyaudiowpatch, and pyproject.toml gains only its pin.
- `uv run --no-sync ruff check src tests`, `uv run --no-sync ruff format --check src tests`, `uv run --no-sync pyright` and `uv run --no-sync pytest -q tests/voice` all pass.
- The hardware FxSound scenarios are collected. Their run is recorded, or marked SKIPPED-PENDING because Snow was running.
- `git status` shows changes only under src/snow/voice, tests/voice, tests/hardware, config/voice.toml, pyproject.toml, uv.lock and this quick directory.
- Snow kept running throughout (same PIDs before and after).
</verification>

<success_criteria>
- FX-processed echo is cancelled (ERLE of 20 dB or more, no barge-in-length run) through the loopback reference in a deterministic unit test, and the render reference visibly fails the same scene.
- Live Snow uses the loopback reference by default and logs which reference is live. It falls back to the render reference and retries on loss, silence-death or ambiguity.
- No loopback audio reaches disk or logs.
- The wake-only fallback exists, is off by default and is tested.
- The hardware scenario exists, and the user can run it after quitting Snow.
</success_criteria>

<output>
Create `.planning/quick/261028-gyg-fxsound-proof-echo-cancellation-via-wasa/261028-gyg-SUMMARY.md` when done. Include the measured ERLE numbers for render vs loopback, the hardware status (ran with numbers, or SKIPPED-PENDING with the command), and the notes listed at the end of Task 3.
</output>
