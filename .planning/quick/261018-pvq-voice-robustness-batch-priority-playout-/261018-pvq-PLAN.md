---
phase: quick-261018-pvq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/snow/common/priority.py
  - src/snow/common/hubclient.py
  - src/snow/hub/supervisor.py
  - src/snow/hub/__main__.py
  - src/snow/voice/__main__.py
  - config/snow.toml
  - tests/hub/test_supervisor.py
  - tests/test_process_hardening.py
  - src/snow/voice/playout.py
  - src/snow/voice/tts/config.py
  - config/tts.toml
  - src/snow/voice/pipeline.py
  - tests/voice/test_playout.py
  - tests/hardware/test_pocket_rtf.py
  - src/snow/voice/stt_groq.py
  - src/snow/voice/config.py
  - src/snow/voice/tone.py
  - config/voice.toml
  - tests/voice/conftest.py
  - tests/voice/test_stt_groq.py
  - tests/voice/test_turn_filter.py
autonomous: true
requirements: [CORE-02, SPCH-03, SPCH-04, VOIC-04]

estimate:
  tokens: 110000
  raw_tokens: 110000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "The voice worker and the hub run at ABOVE_NORMAL priority with Windows EXECUTION_SPEED power throttling explicitly off (HighQoS), so Windows does not park them on efficiency cores on battery; if either call fails it is logged and the process carries on"
    - "After laptop sleep/resume (a supervisor tick gap above sleep_gap_s, 3 s) no worker is killed as hung; a worker that really stops beating is still killed after hang_after_s (20 s), with a worker_slow warning at slow_after_s (6 s) and its Python stacks written to logs/<worker>.err before the kill"
    - "When synthesis falls behind playback, the speaker fades out over about 5 ms, re-buffers until rebuffer_ms (250 ms) is queued or the clause is complete, and fades back in, instead of playing silence gaps for the rest of the reply; the echo canceller reference still receives every block, faded samples included"
    - "When the synthesis real-time factor (EWMA) is above hold_rtf (0.7), each clause starts playing only once it is fully synthesized; every spoken reply logs its underrun count and RTF"
    - "Groq requests use verbose_json, temperature 0 and the vocabulary prompt from voice.toml; a turn whose every segment has no_speech_prob >= silent_no_speech_prob and avg_logprob <= silent_avg_logprob, or whose voiced audio is under min_voiced_s (0.3 s), gets no transcript and no reply, and no scripted line is spoken; the short turn never reaches Groq"
    - "Every turn logs voiced seconds and voiced dBFS (plus Groq's confidence numbers and word counts); no transcript text and no audio reach logs or disk (D-18)"
    - "Every threshold lives in config TOML (snow.toml [supervisor], tts.toml [playout], voice.toml [stt] and [stt.groq]) and is tested at its edge"
  artifacts:
    - path: "src/snow/common/priority.py"
      provides: "raise_priority(): SetProcessInformation(ProcessPowerThrottling=4, EXECUTION_SPEED off) via ctypes plus psutil ABOVE_NORMAL_PRIORITY_CLASS; never raises"
      contains: "def raise_priority"
    - path: "src/snow/hub/supervisor.py"
      provides: "SupervisorConfig (slow_after_s, hang_after_s, sleep_gap_s); resume guard in tick(); slow warning; SNOW_STALL_DUMP_S passed to supervised workers"
      contains: "class SupervisorConfig"
    - path: "src/snow/common/hubclient.py"
      provides: "arm_stall_dump(): faulthandler.dump_traceback_later re-armed on every heartbeat, cancelled when the session ends"
      contains: "def arm_stall_dump"
    - path: "src/snow/voice/playout.py"
      provides: "re-buffer with fade on underrun, clause_done(synth_s), rtf EWMA, hold mode, underruns counter"
      contains: "def clause_done"
    - path: "src/snow/voice/stt_groq.py"
      provides: "verbose_json + temperature 0 + prompt request; silent-turn rule; confidence log line without text"
      contains: "verbose_json"
    - path: "src/snow/voice/tone.py"
      provides: "voiced_level(pcm, sample_rate) shared by the tone analyzer and the pipeline's per-turn gate"
      contains: "def voiced_level"
    - path: "tests/hardware/test_pocket_rtf.py"
      provides: "Hand-run battery A/B of Pocket RTF in two hidden child processes, with and without raise_priority (marked hardware)"
      contains: "pytest.mark.hardware"
  key_links:
    - from: "src/snow/voice/__main__.py and src/snow/hub/__main__.py"
      to: "snow.common.priority.raise_priority"
      via: "called once at process start, after configure()"
      pattern: "raise_priority\\(\\)"
    - from: "config/snow.toml [supervisor]"
      to: "Supervisor(timing=...)"
      via: "SnowConfig.supervisor in src/snow/hub/__main__.py"
      pattern: "timing=config.supervisor"
    - from: "Supervisor._spawn"
      to: "HubClient heartbeat arm_stall_dump"
      via: "SNOW_STALL_DUMP_S env var = slow_after_s"
      pattern: "SNOW_STALL_DUMP_S"
    - from: "VoicePipeline._run_reply texts()"
      to: "Playout.clause_done"
      via: "called after each clause's synthesis returns"
      pattern: "clause_done\\("
    - from: "VoicePipeline._transcribe"
      to: "snow.voice.tone.voiced_level"
      via: "per-turn log and min_voiced_s gate before SttRouter.final"
      pattern: "voiced_level\\("
---

<objective>
Voice robustness batch from the gap study, items 1, 2, 3 and 6 (`.planning/quick/261018-pvq-voice-robustness-batch-priority-playout-/261018-pvq-GAP-STUDY.md`, table rows 1, 2, 3, 6):

1. Process priority and Windows QoS: the voice worker and the hub opt out of power throttling and run above normal priority.
2. Playout re-buffering: on underrun, fade out, re-buffer with hysteresis, fade in. Track synthesis RTF and hold each clause until it is complete when RTF is high. Log underruns and RTF.
3. Resume-aware supervisor: a tick gap means the PC slept, so heartbeats reset instead of killing healthy workers. Longer kill timeout with an early warning, and Python stacks dumped before a kill.
4. Groq STT: verbose_json, temperature 0, a vocabulary prompt. Silent and too-short turns are dropped. Per-turn level and confidence logging without text.

Purpose: Snow keeps talking smoothly on battery and under load, survives laptop sleep without restarting itself, and stops answering noise. These target problems 4, 5 and 6 in the gap study (SPCH-03, SPCH-04, CORE-02, VOIC-04).
Output: `src/snow/common/priority.py`, changes to the supervisor, hubclient, playout, pipeline, Groq STT and tone, config in three TOML files, unit tests at every threshold edge, and a hand-run Pocket RTF A/B test.

IMPORTANT, sits on top of quick task 261018-glq (echo cancellation), already merged to main as commit 10b4e0d. Re-read `src/snow/voice/playout.py`, `src/snow/voice/pipeline.py`, `src/snow/voice/turn.py` and `config/tts.toml` fresh before editing. Keep these intact:
- `Playout.on_render(out)` stays called exactly once per callback block, after the locked fill. Every fade in this plan is applied to `out` inside the locked section, before `on_render`, so the canceller's reference equals what is played.
- `_on_frame` stays as is, with `aec.capture(frame)` first.
- `_load_tts` keeps building the EchoCanceller before the Playout and keeps passing `on_render` and `echo_warming`.
- `stop()` keeps closing the canceller.
- `PlayoutConfig` keeps `assume_headphones` and `echo_cancellation`.
</objective>

<execution_context>
@.claude/gsd-core/workflows/execute-plan.md
@.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@.planning/quick/261018-pvq-voice-robustness-batch-priority-playout-/261018-pvq-GAP-STUDY.md
@src/snow/hub/supervisor.py
@src/snow/hub/__main__.py
@src/snow/common/hubclient.py
@src/snow/voice/__main__.py
@src/snow/voice/playout.py
@src/snow/voice/pipeline.py
@src/snow/voice/stt_groq.py
@src/snow/voice/tone.py
@src/snow/voice/config.py
@src/snow/voice/tts/config.py
@config/snow.toml
@config/tts.toml
@config/voice.toml
@tests/hub/test_supervisor.py
@tests/voice/test_tts_pipeline.py
@tests/voice/test_bargein.py
@tests/voice/test_stt_groq.py
@tests/voice/conftest.py

Facts verified at planning time (use them as given):
- Windows API, checked against Microsoft Learn (PROCESS_INFORMATION_CLASS, PROCESS_POWER_THROTTLING_STATE, SetProcessInformation pages) and the mingw-w64 processthreadsapi.h:
  - Enum order: ProcessMemoryPriority, ProcessMemoryExhaustionInfo, ProcessAppMemoryInfo, ProcessInPrivateInfo, ProcessPowerThrottling. So ProcessPowerThrottling = 4.
  - The struct is three ULONGs, in this order: Version, ControlMask, StateMask. sizeof = 12.
  - PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1 and PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1.
  - HighQoS is ControlMask = EXECUTION_SPEED with StateMask = 0.
  - Signature: `BOOL SetProcessInformation(HANDLE hProcess, PROCESS_INFORMATION_CLASS cls, LPVOID info, DWORD size)`. It returns nonzero on success; on failure, call GetLastError.
- Windows does not hand ABOVE_NORMAL_PRIORITY_CLASS down to child processes (only IDLE and BELOW_NORMAL are inherited), so the hub's boost does not reach the brain or the HUD.
- Supervisor: the hub stamps `heartbeats[role] = time.monotonic()` (src/snow/hub/server.py:158, 205). The supervisor's default clock is also `time.monotonic`. The tick runs every `TICK_S = 0.25`. Workers beat every `HEARTBEAT_S = 2.0` from `HubClient._heartbeat`. Worker stderr is appended to `<data_dir>/logs/<name>.err` by `_launch`. `scrub_env` is asserted byte-exact in tests/test_cli.py:70, so do not change it.
- `SnowConfig` lives in src/snow/hub/__main__.py, with `hub: HubSettings = HubSettings()` (defaults mirrored in snow.toml). tests/hub/test_autostart.py, tests/hub/test_retention.py and tests/test_cli.py write their own snow.toml without new sections, so a new config section must have model defaults (same pattern as HubSettings).
- tests/hub/test_supervisor.py `Rig` advances the fake clock by large steps in a single tick (`advance(5.9)`, `run_for(40)`, `expect_restart_after(30)`). With a resume guard, any single tick longer than sleep_gap_s counts as a resume.
- openai SDK in .venv:
  - `audio.transcriptions.create(..., response_format="verbose_json")` returns `TranscriptionVerbose`, with `text` and `segments: list[TranscriptionSegment] | None`.
  - Each segment has `avg_logprob`, `no_speech_prob` and `compression_ratio`.
  - `create` accepts `prompt: str` and `temperature: float`.
  - The SDK's own segment docstring gives Whisper's silence rule: high no_speech_prob AND avg_logprob below -1.
- `ToneAnalyzer.analyze` (src/snow/voice/tone.py:93-128) already computes the voiced frames and `voiced_s` (30 ms frames, a frame is voiced if within 20 dB of the 95th-percentile frame and above -50 dBFS, gaps up to 300 ms bridged) and the voiced loudness in dBFS.
- The pipeline releases a turn with empty text at pipeline.py `_transcribe` (`if not text: self._release(turn_id)`): no transcript and no spoken line.
- The router synthesizes clause by clause, strictly in order (src/snow/voice/tts/router.py:255-256: `async for text in chunks: await self._say(...)`). So when the `texts()` generator in `_run_reply` resumes after a `yield`, that clause's synthesis has finished.
- Logs go to `%LOCALAPPDATA%\Snow\logs\<process>.log` (JSON, secrets redacted). Pytest's default addopts already exclude hardware, gpu, slow and network.
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Tracer - process level: priority and QoS opt-out, resume-aware supervisor, stall stacks before a kill</name>
  <files>src/snow/common/priority.py, src/snow/voice/__main__.py, src/snow/hub/__main__.py, src/snow/hub/supervisor.py, src/snow/common/hubclient.py, config/snow.toml, tests/hub/test_supervisor.py, tests/test_process_hardening.py</files>
  <behavior>
    - The power-throttling struct has ctypes.sizeof 12 and fields Version, ControlMask, StateMask, with ProcessPowerThrottling == 4, CURRENT_VERSION == 1 and EXECUTION_SPEED == 1.
    - Real child process (Windows only, a hidden python -c child, nothing audio): after raise_priority() returns True, psutil reports ABOVE_NORMAL_PRIORITY_CLASS. GetProcessInformation(ProcessPowerThrottling) read back shows ControlMask with the EXECUTION_SPEED bit set and StateMask with it clear. If GetProcessInformation itself is not supported for this class on the OS, the child reports that and the test asserts only on raise_priority's True. In the same child, arm_stall_dump(0.2) followed by a blocking time.sleep(1.0) writes a faulthandler dump ("most recent call first") to its stderr.
    - raise_priority() with SetProcessInformation patched to return 0, or with psutil raising AccessDenied, returns False, logs process_priority_failed and does not raise.
    - Supervisor, with the shipped snow.toml [supervisor] values (load_config("snow.toml", SnowConfig).supervisor) and the fake clock stepped one TICK_S at a time with no beats:
      - Alive at hang_after_s minus one tick, killed with cause "hang" after hang_after_s.
      - worker_slow is logged exactly once after slow_after_s and is re-armed by a fresh beat.
    - Resume guard edge: after a beat, one tick that jumps the clock by exactly sleep_gap_s is not a resume. One tick that jumps by sleep_gap_s plus 0.01 is a resume: hub_resumed is logged, the heartbeat is reset, and there is no kill even when the jump is 3600 s. A worker that then stays silent is still killed hang_after_s after the resume tick.
    - Supervised workers are launched with SNOW_STALL_DUMP_S equal to slow_after_s in their env. Extra dev workers get the env unchanged.
    - HubClient._heartbeat calls arm_stall_dump(seconds) after each publish when SNOW_STALL_DUMP_S is set, never when it is unset or malformed, and cancels the dump when the task ends.
    - All existing supervisor tests pass (the six-second hang test is rewritten for the new timeout, see action).
  </behavior>
  <action>
1. Create `src/snow/common/priority.py` (gap study row 1). Module docstring:
   - Windows QoS can put a windowless background process on efficiency cores at low clock speed on battery. Snow's voice must keep real time, so the voice worker and the hub opt out.
   - Cite the verified constants from the context block.
   - Logger `logging.getLogger("snow.process")`.

   Function `raise_priority() -> bool`:
   - Return False at once when `sys.platform != "win32"`, so pyright narrows the Windows-only ctypes names.
   - Step 1, QoS: define a `ctypes.Structure` with three `wintypes.ULONG` fields (Version, ControlMask, StateMask), plus module constants `PROCESS_POWER_THROTTLING = 4`, `THROTTLING_VERSION = 1` and `EXECUTION_SPEED = 0x1`. Load `ctypes.WinDLL("kernel32", use_last_error=True)` and declare `argtypes`/`restype` explicitly for `GetCurrentProcess` (restype `wintypes.HANDLE`) and `SetProcessInformation` (HANDLE, c_int, c_void_p, DWORD -> BOOL). Without the declarations the 64-bit pseudo-handle is truncated. Call it with Version 1, ControlMask EXECUTION_SPEED, StateMask 0. On a zero return, `log.warning("process_priority_failed step=qos winerror=%d", ctypes.get_last_error())`.
   - Step 2, priority: `psutil.Process().nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)`. On `psutil.Error` or `OSError`, `log.warning("process_priority_failed step=priority kind=%s", type(e).__name__)`.
   - Never use HIGH or REALTIME: they can starve the mic and audio threads of other apps.
   - On success of both, `log.info("process_priority qos=high priority=above_normal")` and return True. Return False if either step failed. Never raise.
   - Also expose a small `read_throttling() -> tuple[int, int] | None` (GetProcessInformation with the same class and struct, None when the call fails). Only the test uses it. Keep it under 10 lines.

2. Call `raise_priority()` once at process start:
   - In `src/snow/voice/__main__.py`, under `if __name__ == "__main__":` right after `configure("voice")`.
   - In `src/snow/hub/__main__.py` `main()`, after the single-instance mutex is acquired and before `asyncio.run`. The second-instance exit path must not touch priority.
   - The brain is not boosted (out of scope; it is network-bound).

3. `src/snow/hub/supervisor.py` (gap study row 3, D-40):
   - Add `class SupervisorConfig(_Strict)` with three fields:
     - `slow_after_s: float = 6.0`: warn, and the worker dumps stacks.
     - `hang_after_s: float = 20.0`: kill.
     - `sleep_gap_s: float = 3.0`: a longer tick gap means the hub was frozen (sleep/resume).

     Defaults mirror the shipped TOML, the same pattern as HubSettings, because several tests write a snow.toml without this section. Delete `HEARTBEAT_TIMEOUT_S`.
   - Replace the `heartbeat_timeout_s` keyword of `Supervisor.__init__` with `timing: SupervisorConfig = SupervisorConfig()` and store it. Add `self._last_tick: float | None = None` and a `slow: bool = False` field on `_State`. `_spawn` resets `slow`.
   - `tick()`:
     - After the `_stopping` check, read `now = self._clock()`. If `_last_tick` is set and `now - _last_tick > timing.sleep_gap_s`, call `log.warning("hub_resumed gap_s=%.1f", gap)` and set every key already in `self._hub.heartbeats` to `now`. Workers that never beat stay absent. This alone skips hang verdicts on this tick. Store `_last_tick = now`, then watch.
     - One-line why: GetTickCount64-based monotonic time keeps counting through sleep, so the first tick after resume would otherwise see every heartbeat as stale.
   - `_watch` hang branch, for watched workers with `w.cause is None` and `silent = now - beat`:
     - If `silent > timing.hang_after_s`: `log.warning("worker_hung worker=%s silent_s=%.1f", ...)`, then kill as today.
     - Else if `silent > timing.slow_after_s` and not `w.slow`: set `w.slow`, then `log.warning("worker_slow worker=%s silent_s=%.1f", ...)`.
     - Else if `silent <= timing.slow_after_s`: clear `w.slow`.
   - `_spawn`: launch supervised workers with `{**self._env, "SNOW_STALL_DUMP_S": f"{self._timing.slow_after_s:g}"}`. Leave `start()`'s extra dev workers on `self._env`.
   - Update the module docstring: kill after hang_after_s, warning at slow_after_s, resume guard, values from snow.toml [supervisor].

4. `src/snow/hub/__main__.py`: add `supervisor: SupervisorConfig = SupervisorConfig()` to `SnowConfig`, importing `SupervisorConfig` from `snow.hub.supervisor`, and pass `timing=config.supervisor` to `Supervisor(...)`.

   `config/snow.toml`: add a `[supervisor]` table with `slow_after_s = 6.0`, `hang_after_s = 20.0` and `sleep_gap_s = 3.0`, each with a one-line comment:
   - workers beat every 2 s, so 6 s is three missed beats: logged, and the worker writes its Python stacks to logs/<worker>.err;
   - 20 s is killed and restarted;
   - a 3 s supervisor tick gap means the laptop slept, so heartbeats are reset, not judged.

5. `src/snow/common/hubclient.py`:
   - Add module function `arm_stall_dump(seconds: float) -> None`. It calls `faulthandler.dump_traceback_later(seconds, repeat=True)` only when `sys.stderr is not None`, because faulthandler needs a real stream; worker stderr is the .err file. One-line why: the hub cannot read another process's stacks on Windows, so the stalled worker writes its own, every `seconds`, until the hub kills it at hang_after_s.
   - In `__init__`, read `SNOW_STALL_DUMP_S` into `self._stall_s: float | None`. A missing or malformed value gives None; a bad value must never crash a worker.
   - In `_heartbeat`, call `arm_stall_dump(self._stall_s)` after each publish when it is set. Wrap the loop in try/finally that calls `faulthandler.cancel_dump_traceback_later()`, so a lost hub connection does not leave a timer that dumps spuriously.
   - Faulthandler output holds file, line and function names only, no locals, so no transcript text can leak (D-18).

6. Tests:
   - `tests/test_process_hardening.py`:
     - The struct and constants test.
     - The failure-path tests (monkeypatch the module's kernel32 call and `psutil.Process`).
     - The real hidden-child test: `subprocess.run([sys.executable, "-c", script], creationflags=CREATE_NO_WINDOW, capture_output=True, timeout=60)`. The child calls raise_priority, read_throttling and psutil nice, prints JSON on stdout, then calls arm_stall_dump(0.2) and blocks in time.sleep(1.0). Skip it on non-Windows. The child opens no audio device.
     - The HubClient heartbeat test, with `HEARTBEAT_S` monkeypatched small, `publish` faked, and `arm_stall_dump` plus `faulthandler.cancel_dump_traceback_later` spied through the module.
   - `tests/hub/test_supervisor.py`:
     - Add a `Rig.idle(seconds)` helper that ticks every `TICK_S` without beats.
     - Rewrite `test_no_heartbeat_for_six_seconds_is_a_hang` as a hang-after test driven by `idle` against the TOML `hang_after_s`.
     - Add the slow-warning (caplog), resume-edge and env tests from the behavior block. Read the thresholds from `load_config("snow.toml", SnowConfig).supervisor`; never hard-code 6/20/3 in assertions.
     - Leave the other existing tests alone. Their big single-tick advances only reset heartbeats, which do not affect spawn, backoff or breaker logic. If one fails, find out why before changing it.
  </action>
  <verify>
    <automated>uv run pytest -q tests/hub/test_supervisor.py tests/test_process_hardening.py tests/test_hub_roundtrip.py</automated>
  </verify>
  <done>raise_priority() opts the voice worker and the hub out of power throttling and raises them to ABOVE_NORMAL, proven in a real hidden child process. The supervisor survives a simulated one-hour sleep without killing anyone. It warns at 6 s, kills at 20 s, and every value comes from snow.toml [supervisor]. A stalled supervised worker writes faulthandler stacks to its stderr before the hub kills it. scrub_env and the existing supervisor behaviour are unchanged.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Playout re-buffers on underrun with fades, tracks synthesis RTF, holds whole clauses when slow, logs both; Pocket RTF A/B hardware test</name>
  <files>src/snow/voice/playout.py, src/snow/voice/tts/config.py, config/tts.toml, src/snow/voice/pipeline.py, tests/voice/test_playout.py, tests/hardware/test_pocket_rtf.py</files>
  <behavior>
    - Underrun mid-utterance (not ended), using TTS_CFG.playout and the FakeStream/Speaker helpers from tests/voice/test_tts_pipeline.py: push 400 ms of constant 0.5, then pump until the queue runs dry inside a block.
      - That block's real samples ramp down to at most 0.5 / fade_samples at the last one, and the rest of the block is zeros. underruns == 1.
      - Pushing rebuffer_ms minus one sample plays nothing; one more sample resumes playback.
      - The first resumed samples ramp up from near 0 and reach 0.5 within the fade length.
    - An ended utterance that drains is never counted as an underrun. The existing prebuffer and drain test passes unchanged.
    - clause_done(synth_s) after pushing exactly 1.0 s: the first measurement sets rtf to synth_s / 1.0 (0.4 gives 0.4). Later clauses blend as an EWMA with weight 0.5.
    - Hold edge, on a fresh Playout: rtf exactly hold_rtf is not holding; hold_rtf + 0.01 is holding. While holding, pushing 500 ms (more than the prebuffer) plays nothing until clause_done or end_utterance.
    - A finished clause shorter than the prebuffer (200 ms, then clause_done) starts playing without waiting for more audio.
    - on_render still gets exactly one block per callback, and the faded block it receives is the same array the device plays.
    - Pipeline (setup() from tests/voice/test_tts_pipeline.py): a two-sentence reply calls Playout.clause_done once per sentence with synth_s >= 0. When drained, it logs tts_playout with underruns= and rtf= (caplog), and the message holds no reply text.
  </behavior>
  <action>
1. `src/snow/voice/tts/config.py` `PlayoutConfig`: add two required fields.
   - `rebuffer_ms: int`: after an underrun, playback resumes once this much is queued (hysteresis).
   - `hold_rtf: float`: above this synthesis real-time factor, each clause plays only once complete.

   `config/tts.toml` `[playout]`: add `rebuffer_ms = 250` and `hold_rtf = 0.7`, with comments:
   - If synthesis falls behind, Snow fades out, waits for 250 ms of audio, and fades back in instead of leaving gaps.
   - Above 0.7, a slow CPU (battery, load) makes Snow speak clause by clause the way OVOS does.
   - The measured RTF appears in voice.log as tts_playout rtf=.

   Leave prebuffer_ms, assume_headphones and echo_cancellation as they are.

2. `src/snow/voice/playout.py` (gap study row 2). Keep the callback non-raising and allocation-light.
   - Module constants:
     - `_FADE_S = 0.005`. One-line why: 5 ms removes the click of cutting a waveform mid-cycle without audibly softening speech.
     - `_RTF_ALPHA = 0.5`. One-line why: the EWMA follows a load change within two clauses.
   - State in `__init__`:
     - `self._rebuffer` in samples from cfg.rebuffer_ms;
     - `self._hold_rtf`;
     - `self._fade` in samples;
     - public `self.rtf: float = 0.0`, which persists across utterances because machine load does;
     - public `self.underruns = 0`, reset only in `start_utterance`, so the pipeline can read it after drain or abort;
     - `_reset_utterance` also sets `self._threshold = self._prebuffer`, `self._fade_in = False` and `self._clause = 0` (samples pushed since the last clause boundary).
   - A `holding` property: `self.rtf > self._hold_rtf`.
   - `push`: add to `_clause`. Only when not holding, set `_playing` once `_buffered >= _threshold`.
   - New `clause_done(synth_s: float) -> None`, under the lock:
     - If `_clause > 0`, compute this clause's RTF as synth_s divided by its audio seconds. Take it as is for the first measurement and blend it after that. Reset `_clause`.
     - Then set `_playing` when anything is buffered: a fully synthesized clause cannot underrun inside itself.
   - `_callback`, inside the existing `if self._playing:` branch after the fill loop:
     - If `_fade_in` and filled, multiply the first min(filled, fade) samples by a 0-to-1 ramp and clear `_fade_in`.
     - If `filled < frames and not self._ended`: this is an underrun. Multiply the last min(filled, fade) real samples by a 1-to-0 ramp, set `_playing = False`, `_threshold = _rebuffer`, `_fade_in = True`, and `underruns += 1`.
     - Keep the existing ended/drained logic.
     - The `on_render(out)` call stays where it is, after the lock: it now receives the faded block, so the echo reference matches the speaker exactly.
     - Do not log from the callback: it runs on PortAudio's thread.
   - Update the module docstring: re-buffering, clause hold, RTF.

3. `src/snow/voice/pipeline.py`:
   - In `_run_reply`'s `texts()` generator, record `time.monotonic()` just before `yield text`. After the yield returns (the router has finished synthesizing that clause), call `playout.clause_done(time.monotonic() - started)`. The time spent waiting on `reply.queue.get()` for the next LLM text is outside that window, so LLM latency does not count as synthesis. If the router cancels or fails, the generator is closed at the yield and nothing runs after it.
   - In `_publish_timing` (called by both `_finish` and `_interrupt`), before its early return, when `self._playout is not None and reply.spoke`: `log.info("tts_playout turn_id=%s underruns=%d rtf=%.2f hold=%s", reply.turn_id, playout.underruns, playout.rtf, playout.holding)`. No text, no audio (D-18).
   - Do not change TurnTiming or any other contract: logging only.
   - Shortcut comment on `rtf`: one EWMA across engines; per-engine RTF only if Cartesia and Pocket ever need separate holds (gap study row 9).

4. `tests/voice/test_playout.py`: the behavior-block tests. Import `Speaker`, `FakeStream` and `setup` from tests/voice/test_tts_pipeline.py. Use `TTS_CFG.playout.model_copy(update=...)` only where a test needs a different value, and read rebuffer_ms and hold_rtf from the loaded config for the edge tests. Do not hard-code 250 or 0.7. Nothing opens a device.

5. `tests/hardware/test_pocket_rtf.py`, with `pytestmark = pytest.mark.hardware`. The executor only collects it.
   - Header docstring:
     - Purpose: battery A/B of Pocket TTS real-time factor with and without `raise_priority()`. This tests the gap study's inferred cause of problem 4.
     - Setup: laptop unplugged, Snow running and idle (realistic contention), nothing else heavy.
     - Command: `uv run pytest -m hardware tests/hardware/test_pocket_rtf.py -s -q`.
     - Nothing is played or written.
   - The test runs two hidden child processes, one after the other, with `subprocess.run([sys.executable, "-c", script, mode], creationflags=CREATE_NO_WINDOW, capture_output=True, timeout=600)`. CREATE_NO_WINDOW is the same flag the supervisor uses, so Windows classifies each child like the worker.
   - Each child:
     - calls `raise_priority()` first in mode "boosted" only;
     - loads `PocketEngine(load_config("tts.toml", TtsConfig).engines.pocket_tts)`;
     - synthesizes one warm-up sentence;
     - then synthesizes three fixed test sentences, streaming them the way tests/voice/test_tts_pipeline.py's real Pocket test does;
     - prints JSON {mode, rtf} computed as total synthesis time over audio seconds.
   - The parent prints both RTFs and the ratio, and asserts that both children produced audio. There is no performance assert: the numbers are for the user to report.
  </action>
  <verify>
    <automated>uv run pytest -q tests/voice/test_playout.py tests/voice/test_tts_pipeline.py tests/voice/test_bargein.py tests/voice/test_echo_cancel.py tests/voice/test_tts_failover.py && uv run pytest -q -m hardware tests/hardware/test_pocket_rtf.py --collect-only</automated>
  </verify>
  <done>An underrun no longer leaves the rest of the reply silent: the playout fades out, re-buffers to rebuffer_ms or to the clause end, and fades back in. When RTF is above hold_rtf, clauses play whole. Each spoken reply logs underruns and RTF without text. The echo-canceller tests and the barge-in tests still pass. The Pocket RTF A/B hardware test collects and writes nothing.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Groq request (verbose_json, temperature 0, vocabulary prompt), silent and too-short turns dropped, per-turn dBFS and confidence logs; run every gate</name>
  <files>src/snow/voice/stt_groq.py, src/snow/voice/config.py, config/voice.toml, src/snow/voice/tone.py, src/snow/voice/pipeline.py, tests/voice/conftest.py, tests/voice/test_stt_groq.py, tests/voice/test_turn_filter.py</files>
  <behavior>
    - The multipart request carries response_format verbose_json, temperature 0 and prompt equal to CFG.stt.groq.prompt, alongside the existing model, language and WAV checks.
    - Silent rule edges (FakeGroq answering one segment): no_speech_prob == silent_no_speech_prob with avg_logprob == silent_avg_logprob gives "" (inclusive). no_speech_prob 0.01 below the threshold keeps the text. avg_logprob 0.01 above the threshold keeps the text.
    - With two segments, one confident and one silent-looking, the full text is kept: the rule drops a turn only when every segment looks silent.
    - A response with no segments keeps result.text (fail open).
    - The groq_stt log line carries segments, no_speech_prob and avg_logprob, and the transcript text never appears anywhere in caplog.text.
    - voiced_level on synthetic 16 kHz PCM: a 270 ms tone burst at -30 dBFS on -70 dBFS noise, aligned to 30 ms frames, gives about 0.27 s voiced and about -30 dBFS. A 300 ms burst gives at least min_voiced_s. Pure -70 dBFS noise gives 0.0 s and -100.0.
    - The ToneAnalyzer.analyze outputs are unchanged (tests/voice/test_tone.py passes untouched).
    - Pipeline (make_rig flow from tests/voice/test_bargein.py):
      - A wake turn with 256 ms of speech: no Groq request at all, no TranscriptFinal, the turn is released (the engine leaves waiting), and turn_audio plus turn_dropped reason=too_short are logged.
      - A wake turn with 352 ms of speech is transcribed.
      - A turn where FakeGroq answers silent segments: no TranscriptFinal, the turn is released, and the voice process emits no ReplyDelta or ReplyFinal.
    - tests/brain/test_no_scripts.py passes.
  </behavior>
  <action>
1. `src/snow/voice/config.py`:
   - `GroqConfig`: add `prompt: str`, `silent_no_speech_prob: float` and `silent_avg_logprob: float`.
   - `SttConfig`: add `min_voiced_s: float`.
   - All are required, matching the strict style of these models.

   `config/voice.toml`:
   - `[stt]`: `min_voiced_s = 0.3`, with the comment that a turn with less voiced sound than this (a cough, a click) is dropped before any Groq request.
   - `[stt.groq]`: `prompt = "Hey Jarvis. Snow, Claude Code, Antigravity, OpenCode."`. Comment: Whisper spelling hints of up to 224 tokens; "Jarvis" helps the wake-phrase strip patterns catch the stand-in wake word; change it with the wake word.
   - `silent_no_speech_prob = 0.6` and `silent_avg_logprob = -1.0`. Comment: a turn is dropped when every segment is at or above the first and at or below the second; this is Whisper's own silence rule; tune it from the groq_stt lines in voice.log.

   Claude's discretion: the gap study suggested 0.4 and -0.5 as a starting point. The user's mic sits 12-18 dB under reference, and dropping a real command is worse than letting a rare hallucination through. So this ships Whisper's canonical, more conservative pair, confirmed in the openai SDK's segment docstring. The study's pair is noted in the TOML comment as the tighter option.

2. `src/snow/voice/stt_groq.py` (gap study row 6, D-37):
   - Request `response_format="verbose_json"`, `temperature=0` (module constant with a one-line why: Groq recommends 0 for transcription; it removes sampling randomness on short clips), and `prompt=self._cfg.prompt` when it is non-empty (omit it otherwise, using the SDK's omit sentinel).
   - The result is a `TranscriptionVerbose`. With `segs = result.segments or []` and at least one segment:
     - `nsp = min(s.no_speech_prob for s in segs)` and `alp = max(s.avg_logprob for s in segs)`.
     - The turn is silent when `nsp >= silent_no_speech_prob and alp <= silent_avg_logprob`, which means every segment satisfies both.
     - `log.info("groq_stt segments=%d no_speech_prob=%.2f avg_logprob=%.2f silent=%s", ...)` using logger `snow.voice`.
     - Return "" when silent, else `result.text`. Return `result.text` when there are no segments.
   - Never log text. Error mapping is unchanged.
   - Update the module docstring.

3. `src/snow/voice/tone.py`: move the frame, RMS, threshold, voiced and bridged-span computation out of `ToneAnalyzer.analyze` into one private helper that both callers use. Add a public `voiced_level(pcm: bytes, sample_rate: int) -> tuple[float, float]`, returning (voiced seconds over the bridged span exactly as analyze computes `voiced_s`, voiced dBFS or -100.0 when nothing is voiced). analyze keeps identical outputs. Do not change constants.

4. `src/snow/voice/pipeline.py` `_transcribe`:
   - First statement: `voiced_s, dbfs = voiced_level(pcm, self._cfg.audio.sample_rate)`, then `log.info("turn_audio turn_id=%s voiced_s=%.2f dbfs=%.1f", ...)`.
   - If `voiced_s < self._cfg.stt.min_voiced_s`: `log.info("turn_dropped turn_id=%s reason=too_short", turn_id)`, `self._release(turn_id)`, return. The local final future is simply left unused, and Groq is never called. It bills at least 10 s per request.
   - After the existing `strip_wake`, log `turn_heard turn_id=%s source=%s raw_words=%d words=%d` (word counts of raw and stripped text). This is the privacy-safe stand-in for the study's "keep raw and stripped text": it shows whether the strip regex or Whisper drops words (gap study section b, point 4).
   - An empty result from a silent Groq turn already takes the existing `if not text: self._release(turn_id)` path. Add nothing that speaks: no scripted line (SPCH-01).
   - Keep the glq changes intact (re-read the file first).

5. Tests:
   - `tests/voice/conftest.py` `FakeGroq`: add `no_speech_prob: float = 0.01` and `avg_logprob: float = -0.2`. The handler answers a realistic verbose_json body: text, language "en", duration, and one segment carrying those two values plus the other `TranscriptionSegment` fields. Existing callers keep working because the defaults are confident.
   - `tests/voice/test_stt_groq.py`: the request-shape and silent-rule tests from the behavior block. Use a custom MockTransport for the two-segment and no-segment cases. Read every threshold from CFG.
   - `tests/voice/test_turn_filter.py`: the voiced_level unit tests and the three pipeline tests. Use `make_rig`, `of` and `until` from tests/voice/test_bargein.py and tests/voice/conftest.py, waking with zero pre-roll so only `rig.hear` speech is voiced. `Rig.hear` feeds 512-sample chunks, so 256 ms and 352 ms land clear of the 0.3 s edge. The exact edge is covered by the voiced_level and config-driven tests.
   - If an existing test now fails because its turn audio has under 0.3 s of voiced sound, lengthen that test's speech. Never lower min_voiced_s.

6. Run every gate from the repo root and fix what fails:
   - `uv run pytest -q -m "not hardware and not gpu and not network"`. Known pre-existing: tests/test_cli.py::test_hub_launches_workers_with_scrubbed_env errors while the user's real Snow hub is running (single-instance lock). Note it; do not fix it here.
   - `uv run ruff check src tests`
   - `uv run ruff format --check src tests`
   - `uv run pyright`
   - `uv run python -m snow.contracts.export --check`. No contract changed, so it must pass without regenerating. If it fails, a contract was touched by mistake: revert that instead of regenerating.
   - `git diff --quiet uv.lock pyproject.toml`: no new packages.

   Never `cd`. Never kill processes by image name. No automated test opens the real mic or speakers.

   In the SUMMARY, list the human checks below verbatim for the user.
  </action>
  <verify>
    <automated>uv run pytest -q -m "not hardware and not gpu and not network" && uv run ruff check src tests && uv run ruff format --check src tests && uv run pyright && uv run python -m snow.contracts.export --check && git diff --quiet uv.lock pyproject.toml</automated>
    <human-check>Run by the user after merge (not by the executor). Logs are in %LOCALAPPDATA%\Snow\logs.
1. Battery A/B (priority): unplug the laptop and leave Snow running and idle. Run `uv run pytest -m hardware tests/hardware/test_pocket_rtf.py -s -q` and report both RTFs. Boosted should be equal or lower. Then talk to Snow on battery for a few replies: voice.log `tts_playout` lines should show underruns=0 and rtf well under 0.7. Worker start lines should show `process_priority qos=high priority=above_normal` in voice.log and hub.log.
2. Sleep/resume: with Snow running, put the laptop to sleep for 2+ minutes, then wake it. hub.log should show `hub_resumed gap_s=...`, with no `worker_hung` and no `worker_exited ... cause=hang` after it. Snow should answer "Hey Jarvis" right after wake without a restart.
3. Short sentences: say several short commands ("what time is it", "you are up buddy") and one-word answers ("yes", "no") in a conversation. Each should be recognised; none should hit `turn_dropped reason=too_short` or `groq_stt ... silent=True`. Report any that did, with their voiced_s, dbfs, no_speech_prob and avg_logprob values, so the thresholds can be tuned.
4. Noise: cough or tap the desk during a conversation. Snow should stay silent, with `turn_dropped` or `silent=True` in voice.log.
5. Underrun feel: during a long reply while the CPU is busy (for example a build running), gaps, if any, should fade rather than click, and Snow should keep speaking to the end.</human-check>
  </verify>
  <done>Groq is asked with verbose_json, temperature 0 and the vocabulary prompt. Silent turns (Whisper's rule over every segment) and turns under 0.3 s of voiced sound get no transcript, no reply and no scripted line, and short ones never reach Groq. Every turn logs voiced_s and dbfs, and Groq turns log their confidence numbers and word counts, never text. All gates pass (except the documented hub-lock error while Snow runs). uv.lock and pyproject.toml are unchanged. The SUMMARY carries the human-check list.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Voice worker -> logs on disk | Per-turn diagnostics are written to a rotating file; transcripts and audio must not cross (D-18) |
| Voice worker -> Groq (cloud) | Turn audio and a config prompt leave the PC; only for wake-opened turns that pass the voiced-length gate |
| Hub supervisor -> worker processes | The hub decides life and death of workers from heartbeat timing; a wrong verdict kills a healthy voice |
| Snow processes -> Windows scheduler | Raised priority and QoS opt-out change how Snow competes with every other app |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-pvq-01 | Information disclosure | New log lines (turn_audio, turn_heard, groq_stt, tts_playout) and faulthandler dumps | medium | mitigate | Lines carry only numbers, ids and word counts. Faulthandler dumps file, line and function names, no locals. Task 3 asserts the transcript string never appears in caplog.text. No audio is written anywhere (D-18) |
| T-pvq-02 | Denial of service | Supervisor resume guard | medium | mitigate | The guard only resets heartbeats for one tick. A silent worker is still killed hang_after_s after resume (Task 1 test). A hub frozen by load rather than sleep also only defers one verdict |
| T-pvq-03 | Denial of service | Longer kill timeout (6 s to 20 s) | low | accept | A truly hung voice now takes about 20 s to heal instead of 6 s. That trades for no false kills after sleep and model loads; the slow warning at 6 s and the stack dumps keep it diagnosable |
| T-pvq-04 | Denial of service | raise_priority starving other apps | low | mitigate | ABOVE_NORMAL only, never HIGH or REALTIME. Not inherited by the brain or HUD children. Failure is logged and ignored |
| T-pvq-05 | Elevation of privilege | SetProcessInformation via ctypes | low | mitigate | Only the GetCurrentProcess pseudo-handle is used, so no handle to another process is opened. argtypes and restype are declared so the 64-bit handle is not truncated |
| T-pvq-06 | Denial of service | Playout fades in the PortAudio callback | medium | mitigate | Slicing and multiplication only, on bounded block-size arrays inside the existing lock. No logging or allocation-heavy work in the callback. Tests drive the callback through FakeStream |
| T-pvq-07 | Spoofing / Denial of service | Silent-turn and min-voiced filters dropping real commands | medium | mitigate | Conservative Whisper rule (AND of both signals over every segment), config thresholds, per-turn logs of the deciding numbers, and a human check of one-word answers |
| T-pvq-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package is installed: psutil, ctypes and faulthandler are already available. The final gate fails if uv.lock or pyproject.toml change |
</threat_model>

<verification>
- Task 1 verify passes, including the real hidden-child proof of ABOVE_NORMAL, HighQoS and the stall dump.
- Task 2 verify passes, including tests/voice/test_echo_cancel.py and tests/voice/test_bargein.py (glq behaviour intact).
- The full gate set in Task 3 passes: pytest (not hardware/gpu/network), ruff check, ruff format --check, pyright, contracts export --check, and uv.lock/pyproject.toml unchanged. The pre-existing tests/test_cli.py hub-lock error is acceptable only while the user's Snow hub runs.
- Hardware tests collect and are not executed by the executor.
</verification>

<success_criteria>
- The voice worker and hub run HighQoS at ABOVE_NORMAL priority.
- Sleep/resume does not restart workers. Real hangs are killed at 20 s after a 6 s warning, with stacks in the worker's .err file.
- Playout re-buffers with 250 ms hysteresis and 5 ms fades, holds whole clauses above RTF 0.7, and logs underruns and RTF per reply.
- Groq uses verbose_json, temperature 0 and a prompt. Silent and under-0.3 s turns are dropped without a spoken line, and each turn logs voiced_s and dBFS without text.
- Every threshold sits in TOML with tests at its edges. No new packages, no contract changes.
</success_criteria>

<output>
Create `.planning/quick/261018-pvq-voice-robustness-batch-priority-playout-/261018-pvq-SUMMARY.md` with `status: complete` in its frontmatter. Include the gate results, whether GetProcessInformation readback worked on this OS, any test numbers that surprised you, and the five human checks from Task 3 verbatim.
</output>
