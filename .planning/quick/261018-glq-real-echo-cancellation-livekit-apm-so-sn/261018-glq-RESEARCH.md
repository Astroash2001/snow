# Quick Task 261018-glq: Real echo cancellation (livekit APM) - Research

**Researched:** 2026-10-18
**Domain:** WebRTC AEC3 via `livekit.rtc.AudioProcessingModule`, wired into Snow's mic/playout threads (VOIC-06)
**Confidence:** HIGH on API and measured numbers (run in a throwaway venv, synthetic audio only); MEDIUM on real-device behaviour (FxSound, Intel SST) which only a hardware run can settle.

## Summary

`livekit==1.1.20` works as the user approved. It resolves against the existing `uv.lock` with no pin changes (only `livekit` and `types-protobuf` are new), ships a `py3-none-win_amd64` wheel (11 MB wheel, 26 MB installed, 24 MB is `livekit_ffi.dll`), and AEC3 cancels a synthetic laptop-speaker echo by 25-40 dB at a cost of about 0.6% of one core. After it has converged, residual echo never reached the 250 ms VAD run that triggers barge-in in 36 of 36 swept cases (4 room seeds x delays 60/120/250 ms x echo levels -24/-30/-36 dBFS).

Two things the stock API does not give you, both measured and both must be in the plan: (1) **cold start** - during roughly 0.6-1.4 s after the first reference audio, residual echo still passes Silero for 250-350 ms in about 36-47% of cold runs, so the first reply after process start needs a temporary barge-in guard; (2) **a wrong frame size kills the whole Python process** (Rust panic, no exception) - the wrapper must validate sizes itself.

**Primary recommendation:** Add `src/snow/voice/aec.py` (`EchoCanceller`: echo cancellation ON only; noise suppression, AGC and high-pass OFF). Feed the reference from `Playout._callback` at the playout's own rate (24 kHz, 2 x 10 ms frames per 20 ms block, no resampling needed), process each 80 ms mic frame as 8 x 10 ms at the top of `VoicePipeline._on_frame`, set `assume_headphones = false`, and raise the barge-in minimum to ~600 ms until ~2 s of reference audio has played.

## Project Constraints (from CLAUDE.md)

- Audio stays in memory only (D-18); nothing written to disk. CPU-light; no new heavy work on the laptop.
- Never `cd`; use `uv --directory`. Pin exact versions; delayed-adoption policy (`exclude-newer = "2026-10-08T00:00:00Z"`). pyright strict on `src/snow`, ruff `S` rules.
- Stack table says: "livekit (rtc) 1.1.20 ... `AudioProcessingModule`: WebRTC AEC3 ... Frames must be exactly 10 ms ... AEC3 silently gives ~0 dB if the echo path delay is >~500 ms or highly variable." Both confirmed below with numbers.

## Standard Stack and Package Audit

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| livekit | ==1.1.20 | `livekit.rtc.AudioProcessingModule` (WebRTC AEC3) | Apache-2.0; wheel `livekit-1.1.20-py3-none-win_amd64.whl`, uploaded 2026-09-23, 10,991,380 bytes [VERIFIED: pypi.org/pypi/livekit/1.1.20/json]. Requires `protobuf>=5, types-protobuf>=5, aiofiles>=24, numpy>=1.26` [VERIFIED: wheel METADATA] |
| types-protobuf | 7.35.1.20260906 | transitive (livekit declares it as a runtime dep) | only new transitive package |

Resolution check (no project files touched): `uv export --frozen` of the project into a constraints file, then `uv pip compile livekit==1.1.20 -c <constraints> --python-platform windows --python-version 3.12 --exclude-newer 2026-10-08T00:00:00Z` gave exactly: `aiofiles==25.1.0, livekit==1.1.20, numpy==2.5.3, protobuf==6.33.6, types-protobuf==7.35.1.20260906` - the first three and `protobuf` match the existing lock entries [VERIFIED: uv.lock lines 21-22, 748-749, 1008-1009]. No `exclude-newer-package` override needed. **No blocker.**

Add to `pyproject.toml` `dependencies`: `"livekit==1.1.20"`. Do not add scipy/soxr (not needed, see below).

### Package Legitimacy Audit

| Package | Registry | Age | Source Repo | Verdict | Disposition |
|---------|----------|-----|-------------|---------|-------------|
| livekit | PyPI | 1.1.20 is 25 days old; org project | github.com/livekit/python-sdks | SUS (seam: `too-new` because the *latest* release is 2026-10-16, `unknown-downloads`) | User explicitly approved this package and we pin ==1.1.20 (before the lock cutoff). Planner: still pin exactly, and run `pip-audit` after lock |
| types-protobuf | PyPI | 6 weeks | github.com/python/typeshed | SUS (`unknown-downloads` only) | Transitive typeshed stub; accept |

Output of `gsd-tools query package-legitimacy check --ecosystem pypi livekit types-protobuf` [VERIFIED: seam run this session]. Weekly-download data was unavailable (null), which is what drove both SUS verdicts.

## livekit.rtc APM API (1.1.20), read from `livekit/rtc/apm.py` and verified by running it

- Constructor, keyword-only, all default False: `AudioProcessingModule(*, echo_cancellation, noise_suppression, high_pass_filter, auto_gain_control)`. No aggressiveness/suppression-level knobs exist.
- `process_stream(frame)` = capture (mic) path, modifies the frame in place. `process_reverse_stream(frame)` = render (reference) path. `set_stream_delay_ms(int)`.
- `AudioFrame(data, sample_rate, num_channels, samples_per_channel)` or `AudioFrame.create(...)`; int16 interleaved; read results with `np.frombuffer(frame.data, dtype=np.int16)`.
- **In place needs a `bytearray`.** `AudioFrame(memoryview(ndarray))` is copied (observed: the numpy array was not modified), `bytes` is converted to a bytearray internally. Use `AudioFrame(bytearray(chunk.tobytes()), rate, 1, n)` and read back from `frame.data`.
- **Frame size:** must be exactly 10 ms (`rate // 100` samples). Observed: 160 @16k, 240 @24k, 441 @44.1k, 480 @48k, 8k, 32k and stereo all work; 320 @16k (20 ms) is accepted (multiple of 10 ms); **80 @16k (5 ms) prints `thread panicked at libwebrtc\src\native\apm.rs:48:9: slice must have a multiple of 10ms worth of samples` and the interpreter dies - no Python exception** [VERIFIED: ran it]. Validate in Python and raise `ValueError` first.
- **Reference may be a different rate from the mic.** Feeding 24 kHz reference (240-sample frames) against 16 kHz capture worked as well or better than a soxr-resampled 16 kHz reference: ERLE 35.4 vs 35.0 dB (echo -24 dBFS) and 28.3 vs 14.5 dB (echo -30 dBFS, cold start variance), residual run shorter [VERIFIED: experiment]. Requires `rate % 100 == 0`; Pocket/Kokoro/Chatterbox/Cartesia all run at 24000 and `VoiceRouter` resamples every engine to one rate (`src/snow/voice/tts/router.py:74`, `:310`). For any other rate resample with `soxr.ResampleStream` (already in the lock via pipecat; 0.004 ms per 20 ms block) - but assert instead of building that unless needed.
- `set_stream_delay_ms`: accepts **0..500**; `-1`, `501`, `600`, `1000` raise `RuntimeError: ... Failed to set stream delay` [VERIFIED]. It is only a hint (see numbers).
- **Thread safety:** reverse on one thread and capture on another, 500 iterations each concurrently: 0 errors, capture mean 0.088 ms, p99 0.46 ms [VERIFIED]. This is the intended WebRTC model (render thread + capture thread). Stress it once in CI anyway.
- Process-level costs: `import livekit.rtc` 538 ms, first APM construction 358 ms, +7 MB RSS, +21 OS threads (idle tokio runtime). Import lazily, only when AEC is enabled.
- Shutdown: dropping the module is required; an APM still alive at interpreter exit prints `Exception ignored in FfiHandle.__del__ ... AssertionError` (harmless). `del self._apm` in `close()` removes it [VERIFIED].
- AEC3 brings its own high-pass: `high_pass_filter=True` gave bit-identical results with and without it, so leave it off. The capture path adds roughly 10 ms of latency (output lags input by ~181 samples at 16k with EC on) - irrelevant for VAD/STT.

## Measured results (synthetic echo, real APM, real Silero via the project's own call pattern)

Harness: fixture speech (`tests/fixtures/audio/*.wav`) as "TTS", upsampled to 24 kHz, echo = decaying-noise room impulse (60 ms) + delay, scaled to an absolute level at the mic, + -63 dBFS white noise. User speech -26 dBFS rms. Scripts: `C:/Users/avina/AppData/Local/Temp/claude/C--Users-avina-Desktop-asssistant/ae60ca63-1c7c-46fd-9698-f28da90d884c/scratchpad/aec/exp/aec_exp*.py`.

| Question | Result |
|----------|--------|
| ERLE once converged | 25-45 dB (echo -24 dBFS: 26-35; -30: 28-45; -36: 27-39); echo+NS adds ~10 dB |
| CPU | reverse 0.010-0.03 ms + capture 0.04-0.10 ms per 10 ms pair; 1000 pairs = 62 ms CPU => **0.62% of one core** at real time; 24 kHz path 0.055 ms per pair |
| Raw mic (no AEC) | Silero fires 95-100 chunks >= 0.5 on the echo alone: this is the reported bug |
| **Warm** residual (2nd reply after 2 s silence) | longest VAD>=0.5 run **<= 192 ms in 36/36 combos (0 ms in 33)**; barge-in needs >= 250 ms. Heavy loudspeaker nonlinearity (tanh drive 3.0, hard clipping) still 128 ms warm, ERLE 24.8 dB |
| **Cold** residual (first reply after start) | residual chunks appear **0.64-1.38 s after the first reference energy**; longest run >= 250 ms in 13/36 (EC only) and 17/36 (EC+NS), max 352 ms. NS does not help the cold start |
| Double-talk (user over echo, warm) | user-alone VAD chunks 69; after APM 54-66 (78-96%); 250 ms barge-in fires 0.1-0.5 s later than ideal (user -38 to -26 dBFS over echo -32/-26 dBFS); zero false chunks before the user speaks |
| Delay hint | true delay 120: hint None/0/20/120 identical (ERLE 36.7-36.8 dB); hint 220 or 400 (too large) ruined the first-second convergence (3.8 dB) then recovered. True delay 450 ms ok (31 dB). 500 ms ok (hint or none). **650 ms: ERLE 2 dB with no hint, 18-34 dB with hint=500. 800/1000 ms: fail (<6 dB)** |
| Delay jitter | abrupt +-30 ms delay steps every second: ERLE 4 dB (fails). Scheduling jitter of the two callbacks up to 0-40 ms: unaffected (27-31 dB); 0-60/80 ms: degraded (9-17 dB) |
| Feed strategy | feeding reverse directly from the playout callback while capture arrives in 80 ms bursts: 27.7 dB, 3 residual chunks - works. Feeding a reference that is *older* than the echo path (causality violation) fails (3 dB) |
| AGC | `auto_gain_control=True` raised the user's level -26.4 -> -18.9 dBFS: do not enable (breaks tone analysis levels and VAD/wake thresholds) |
| Wake word | openWakeWord `hey_jarvis` on `wake_cmd_gap0/gap600/wake_only` through APM (silent reference): score 1.00 raw, 1.00 with EC, EC+NS, EC+NS+HPF [VERIFIED] but the score saturates, so this only shows no gross harm; NS effect on a marginal/quiet wake is untested (LOW) |

## Architecture / integration design

```
PortAudio output thread                        snow-voice-audio thread
Playout._callback(outdata 480 f32 @24k)        MicSource -> _Pump -> VoicePipeline._on_frame(int16 x1280 @16k)
   out[:] filled (speech or zeros)                  frame = aec.capture(frame)   # NEW, first line
   -> aec.render(out)  # NEW                        -> _recent / local STT / wake / TurnEngine (unchanged)
      float32 -> int16, 2 x 240-sample frames          (8 x 160-sample process_stream, bytearray, read back)
      process_reverse_stream(...)
              \_______ one shared rtc.AudioProcessingModule (EC only) ______/
```

- **Tap point:** `Playout._callback` (`src/snow/voice/playout.py:155`), after `out` is filled and before the level callbacks; the callback runs continuously while the stream is open (zeros between utterances), so the reference timeline is gapless. Add an `on_render: Callable[[npt.NDArray[np.float32]], None]` constructor parameter like the existing three callbacks; `_load_tts` (`pipeline.py:476`) passes `aec.render`. Keep leftover samples in `render()` so frames are always exact 10 ms even if PortAudio hands a different block size.
- **Capture point:** first line of `VoicePipeline._on_frame` (`pipeline.py:333`) so wake gate, VAD/turn, local Moonshine, Groq STT and tone all see cleaned audio. 1280 samples = 8 x 160 exactly. Do **not** apply it for `FileSource` (no reference; the HPF would alter golden-test audio): construct `EchoCanceller` in `build_pipeline` only for a live `MicSource` and when enabled.
- **No resampling needed:** reference at 24 kHz / capture at 16 kHz is accepted natively (see API section). Guard: `assert render_rate % 100 == 0 and capture_rate % 100 == 0` at construction.
- **Alignment across threads:** direct feed, no ring buffer, worked in simulation with 80 ms capture bursts and 0-40 ms callback jitter. The one rule is: reference must never be *older* than the echo path; never delay or pre-buffer the reference relative to what the speaker plays. Do not add a ring buffer unless the hardware run shows jitter problems.
- **Stream delay:** call `set_stream_delay_ms` once after both streams exist: `clamp(round((out.latency + in.latency) * 1000) + 30, 0, 500)` from `sd.OutputStream.latency` / `sd.InputStream.latency` (floats in seconds). For this laptop PortAudio's *query* numbers are tiny (WASAPI default input "Microphone Array (Intel Smart Sound Technology ...)" low latency 0.002 s, default output "FxSound Speakers (FxSound Audio Enhancer)" low latency 0.003 s, both 48 kHz [VERIFIED: sd.query_devices run this session]) and understate the real path, so treat the hint as approximate; AEC3 estimates the delay itself and any hint within ~100 ms of truth is harmless. The playout stream is created lazily (`start_utterance`), so set the hint when the first utterance starts, not at pipeline start; a missing hint also works.
- **Config (in-repo values, verbatim):** `src/snow/voice/tts/config.py:19-21` is `class PlayoutConfig(_Strict):\n    prebuffer_ms: int\n    assume_headphones: bool  # no echo cancellation in v1: barge-in needs headphones`; `config/tts.toml:33` is `assume_headphones = true`; `config/voice.toml` has `barge_in_min_ms = 250  # used by plan 01-29`; the startup warning is `log.warning("speakers_without_echo_cancellation barge_in_hears_snow")` at `pipeline.py:190` guarded by `not self._tts_cfg.playout.assume_headphones`. Recommend: add `echo_cancellation: bool` to `PlayoutConfig` (fields are strict/required), set `assume_headphones = false` / `echo_cancellation = true`, and log the warning only when both are false. Reword the stale comments in `tts.toml:30-33` and `config.py:21`.
- **Cold-start guard (required):** `TurnEngine._listen_over` (`turn.py:266-274`) uses `self._cfg.barge_in_min_ms`. Add a second value (e.g. `barge_in_warmup_min_ms = 600`) used while `aec.reference_seconds < 2.0` (seconds of reference frames with rms above about -50 dBFS, accumulated in `render`; an int/float written on the output thread and read on the audio thread is fine under the GIL). Cold residual maxed at 352 ms, so 600 ms has margin; the guard only delays a real barge-in by ~350 ms during the first 2 s of the first reply after start. Also reset the counter if the APM is recreated (mic reopened after unplug).
- **Do not enable:** noise suppression (no benefit for gating, worse cold start, unknown wake effect), AGC, high-pass. `EchoCanceller(echo_cancellation=True)` only.
- **Residual-echo guard beyond warm-up:** not needed on the data (warm max 192 ms vs 250 ms). Keep `barge_in_min_ms = 250` for steady state; consider 300 only if the hardware run shows single warm hits.
- **Failure mode:** if `livekit` fails to import or `AudioProcessingModule` raises, log `aec_unavailable` and fall back to pass-through (audio never stops), and keep the headphone warning. Wrap `render`/`capture` so one bad frame never raises into the PortAudio thread (`_Pump.deliver` already isolates the mic side; the output callback does not - add a try/except around the tap).

### Skeleton (types as in the repo style)

```python
class EchoCanceller:
    def __init__(self, capture_rate: int = 16000, render_rate: int = 24000) -> None:
        if capture_rate % 100 or render_rate % 100:
            raise ValueError("APM frames are 10 ms: rates must be multiples of 100")
        from livekit import rtc  # lazy: 0.5 s import, 21 native threads
        self._rtc = rtc
        self._apm = rtc.AudioProcessingModule(echo_cancellation=True)
        self._cn, self._rn = capture_rate // 100, render_rate // 100
        self._cr, self._rr = capture_rate, render_rate
        self._tail = np.zeros(0, np.int16)
        self.reference_s = 0.0

    def set_delay(self, ms: int) -> None:
        self._apm.set_stream_delay_ms(max(0, min(500, ms)))  # >500 raises RuntimeError

    def render(self, block: npt.NDArray[np.float32]) -> None:  # PortAudio output thread
        pcm = np.concatenate([self._tail, np.clip(block * 32768.0, -32768, 32767).astype(np.int16)])
        usable = len(pcm) - len(pcm) % self._rn
        for i in range(0, usable, self._rn):
            self._apm.process_reverse_stream(
                self._rtc.AudioFrame(bytearray(pcm[i : i + self._rn].tobytes()), self._rr, 1, self._rn))
        self._tail = pcm[usable:]

    def capture(self, frame: npt.NDArray[np.int16]) -> npt.NDArray[np.int16]:  # audio thread
        if len(frame) % self._cn:
            raise ValueError("mic frame must be a whole number of 10 ms")  # a bad size panics the process
        out = np.empty_like(frame)
        for i in range(0, len(frame), self._cn):
            f = self._rtc.AudioFrame(bytearray(frame[i : i + self._cn].tobytes()), self._cr, 1, self._cn)
            self._apm.process_stream(f)
            out[i : i + self._cn] = np.frombuffer(f.data, dtype=np.int16)
        return out

    def close(self) -> None:
        del self._apm  # avoids the FfiHandle.__del__ traceback at exit
```
`reference_s` update and `float(np.sqrt(np.mean(block**2)))` energy check go in `render`. pyright strict will need `# pyright: ignore[reportMissingTypeStubs]`-style comments on the untyped `livekit.rtc` surface (it ships `py.typed`, so likely fine).

## Don't Hand-Roll

| Problem | Use | Why |
|---------|-----|-----|
| Echo cancellation | livekit APM (AEC3) | adaptive filters + delay estimator + nonlinear suppressor; hand-rolled NLMS did not survive in this class of project |
| 10 ms framing | the 8-iteration loop above | 1280 mic samples and 480 playout samples are exact multiples; leftover buffer only on the render side |
| Resampling | nothing (APM resamples internally) | verified equal or better than soxr to 16 kHz |
| Residual gate energy math | none beyond `reference_s` | warm data does not need it |

## Common Pitfalls

1. **Wrong frame size aborts the process** (Rust panic). Validate in Python; unit-test `ValueError`.
2. **Cold start (first ~1.5 s of reference):** residual is speech-like for 250-350 ms. Guard as above. Warm state persists across silences (a 2-3 s gap was fine); a long idle or a changed echo path (volume jump, device switch) re-triggers a short adaptation, so the guard keyed on cumulative reference seconds is a heuristic - LOW confidence for long idles until the hardware run.
3. **Reference older than the echo path** (causality) or **delay > 500 ms** (hint max 500; unhinted fails above ~500) gives ~0-3 dB. WASAPI shared + FxSound is expected to be tens of ms; if the hardware test shows ERLE < 6 dB, measure the real loopback delay first.
4. **FxSound Speakers (virtual device with DSP):** the speaker output is processed after Snow hands samples over (EQ/loudness/possible compression), adding nonlinearity and delay the reference does not contain. Synthetic hard clipping (tanh drive 3.0) still gave 24.8 dB warm and 128 ms residual, so it should work, but the hardware test must be run with FxSound as default AND once with its effects off / another output to isolate it [ASSUMED about its internals].
5. **Intel SST mic arrays** may already apply their own AEC/NS in the driver ("Microphone Array", 2 channels, 48 kHz, downmixed and resampled by WASAPI `auto_convert` to 16 kHz mono). A driver-side AEC would be nonlinear and unknown; the APM still helps but numbers may differ from synthetic [ASSUMED].
6. **Double-talk:** AEC3 attenuates near-end speech a little (78-96% of user VAD chunks survive; barge-in 0.1-0.5 s later than ideal). Acceptable; do not raise `vad_threshold`.
7. **Sample-rate mismatch at runtime:** `Playout.sample_rate` comes from the first engine that loads (`router.py:74`, `:161`); construct `EchoCanceller` with the router's rate after `wait_ready()` (inside `_load_tts`), not before.
8. **Noise suppression harms the premise:** keeps ~10 dB more cancellation when warm but adds ~10 ms and changes speech spectra for Moonshine/tone; skip.
9. **Pocket TTS 0.25x real time** during the echo loop is consistent with self-triggered STT/LLM turns competing for CPU; the AEC itself costs 0.6% of a core. Re-measure the Pocket real-time factor in the hardware run after AEC; if it is still < 1x the cause is elsewhere (do not assume AEC fixed it).
10. **GIL in the audio callback:** `process_reverse_stream` does a protobuf serialisation + FFI call (about 10-30 us) inside the PortAudio output callback. Fine at 2 calls per 20 ms; keep the try/except tight and do not add logging there.

## Test strategy

### CI (no hardware): `tests/voice/test_echo_cancel.py`
Real `EchoCanceller`, real `VadDetector` (Silero), fixtures via `read_wav(path, rate)` from `snow.voice.sources` (resamples to 24 kHz for the "TTS" signal; `tests/fixtures/audio/phrase_thats_all.wav`, `tone_calm.wav`, `phrase_go_to_sleep.wav` as TTS, `mid_thought_pause.wav` as the user). Echo helper (deterministic; ~15 lines):

```python
def echo_of(far16, delay_ms, level_dbfs, seed):
    rng = np.random.default_rng(seed)
    n = int(16000 * 0.06)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (16000 * 0.015)); ir[0] = 3.0
    ir /= np.sqrt((ir ** 2).sum())
    y = np.convolve(far16, ir)[: len(far16)]
    y = np.concatenate([np.zeros(int(16000 * delay_ms / 1000)), y])[: len(far16)]
    return y * (10 ** (level_dbfs / 20) / np.sqrt(np.mean(y ** 2)))
```
Drive `render()` with 480-sample 24 kHz blocks and `capture()` with 1280-sample 16 kHz frames in the same loop (render before capture per 20 ms), mic = echo + white noise at -63 dBFS (+ user). Cases and thresholds, all measured above (deterministic for a fixed seed and pinned livekit):
1. **Precondition:** raw mic (no AEC) has a VAD>=0.5 run >= 250 ms (observed 64-100 chunks). Proves the fixture is a real test.
2. **Warm residual:** far = utt1, 2 s silence, utt2; for seeds 0-3 and delays 60/120/250 ms at -26 dBFS: longest VAD>=0.5 run during utt2 < `CFG.turn.barge_in_min_ms` (observed max 192 ms, mostly 0).
3. **ERLE warm >= 20 dB** (observed 24.5-39 dB).
4. **Double-talk:** user starts 1.5 s into utt2 at -32 dBFS over echo -26 dBFS: >= 70% of the user-alone VAD chunks survive (observed 78-96%) and a 250 ms run exists within 0.7 s of the user-alone onset (observed +0.1 to +0.5 s).
5. **Cold start documents the guard:** with `reference_s < 2.0`, assert the engine uses the warm-up minimum (unit test on `TurnEngine` with a stub VAD, no APM needed) and that a 352 ms residual burst does not barge in under 600 ms.
6. **Frame guards:** `capture()` with 100 or 170 samples raises `ValueError` (never reaches the panicking FFI); construct with `render_rate=22050` raises.
7. **Thread stress:** render from one thread, capture from another, 500 iterations each, no exception.
8. **Pipeline wiring:** with `Speaker`/`FakeStream.pump` from `tests/voice/test_tts_pipeline.py`, `Playout` calls `on_render` once per block with `float32` of the block length; with AEC disabled/`FileSource` the capture path is untouched (existing tests stay byte-identical).

Runtime: 12-13 s of audio at 0.07 ms per 10 ms pair is well under a second of APM plus Silero time; mark nothing `slow`. Existing `addopts` excludes only `hardware/gpu/slow/network`.

### Hardware (`tests/hardware/test_echo_cancel.py`, `@pytest.mark.hardware`, run by hand)
Outline (header docstring like `tests/hardware/test_latency.py`: "Run by hand on the laptop, speakers on, room quiet, Snow's worker stopped"): open the real `MicSource` and a real `Playout` with the real `EchoCanceller`; play `tests/fixtures/audio/tv_negative.wav`-style or a fixture phrase (repeated, 24 kHz) through the default output at the user's normal volume while the user stays silent for ~10 s; tap raw mic frames and post-APM frames in memory. Print and assert: stream latencies (`out.latency`, `in.latency`) and the hint used; raw vs processed RMS per second (ERLE after 3 s >= 15 dB, looser than synthetic); longest VAD>=0.5 run on processed audio after 3 s < `barge_in_min_ms`; cold residual burst length (informational). Second part: prompt "say 'stop' now", expect a barge-in within ~1 s while a reply plays. Variants to record in SUMMARY: FxSound default vs FxSound effects off / another output, hint = computed vs 0 vs 100. Nothing is written; do not record to disk.

## Environment Availability

| Dependency | Available | Notes |
|------------|-----------|-------|
| Python 3.12 + uv | yes | `uv venv --python 3.12` scratch venv used |
| livekit 1.1.20 win_amd64 wheel | yes | installed and run in scratchpad venv |
| Silero VAD / openWakeWord models | yes | Silero via pipecat 1.12.0 in scratch venv; `models/openwakeword/hey_jarvis_v0.1.onnx` present |

## Assumptions Log

| # | Claim | Risk if wrong |
|---|-------|---------------|
| A1 | FxSound's DSP and the Intel SST driver's own processing behave like the synthetic nonlinear/delayed echo | AEC may reach only 10-15 dB; guard values and `echo_cancellation` default need tuning in the hardware run |
| A2 | Cold-start residual window (0.6-1.4 s after first reference energy) and the 2 s / 600 ms guard generalise to real rooms | A real first reply could still self-interrupt once; raise guard window |
| A3 | Noise suppression off is right for wake-word reliability | If the user's mic is noisy, wake false-accepts/rejects change; re-test with the trained "Hey Snow" model |
| A4 | PortAudio `stream.latency` + 30 ms is a good delay hint | Hint is optional; wrong-by->100 ms costs first-second convergence only |
| A5 | Windows' own communications-stream AEC (not reachable through PortAudio/sounddevice) is not worth pursuing | None for this task |

## Open Questions

1. Real loopback delay on this laptop with FxSound (tens of ms vs hundreds)? Answered only by the hardware test; if > 500 ms the approach is blocked and the fallback is headphones or switching the output to the physical Realtek/"Speakers" device.
2. Does a Pocket TTS real-time factor of < 1x persist after the echo loop is gone? Measure in the same hardware run.

## Security Domain

No new trust boundary: audio stays in process memory (no disk, no network); the native `livekit_ffi.dll` is loaded into the voice worker (supply-chain: pin exact, hash-locked `uv.lock`, run `pip-audit` as the project already does). ASVS V5 (input validation): validate frame sizes before FFI. livekit's `FfiClient` initialises with `livekit_ffi_initialize(..., b"python", version)`; no `Room` is created, so no network connection is made by this use [VERIFIED: read `_ffi_client.py`; APM path only issues APM requests]. Confirm with the existing `tests/voice/test_no_egress.py` after adding the dependency.

## Sources

### Primary (HIGH)
- `livekit/rtc/apm.py`, `audio_frame.py`, `_ffi_client.py`, `_utils.py` in the installed 1.1.20 wheel (read this session)
- `https://pypi.org/pypi/livekit/1.1.20/json` (files, upload date, license, project URLs); `uv pip compile` / `uv export` resolution runs
- Repo files read this session: `src/snow/voice/playout.py`, `sources.py`, `pipeline.py`, `turn.py`, `vad.py`, `wake.py`, `tts/config.py`, `config/voice.toml`, `config/tts.toml`, `pyproject.toml`, `tests/voice/test_tts_pipeline.py`, `tests/hardware/test_latency.py`
- Experiments in the scratchpad (`aec_exp.py` ... `aec_exp14.py`): all numbers above

### Tertiary (LOW)
- Behaviour of FxSound and the Intel SST driver internals (A1)

## Metadata

**Confidence:** stack/API HIGH (executed); architecture MEDIUM (simulated threading, no live devices by design); real-room pitfalls MEDIUM-LOW until the hardware test.
**Research date:** 2026-10-18. **Valid until:** 2026-11-17 (livekit ships weekly; stay on the pin).
