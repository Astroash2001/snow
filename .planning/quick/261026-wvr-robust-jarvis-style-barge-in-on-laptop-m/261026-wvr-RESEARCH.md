# Quick Task 261026-wvr: Robust Jarvis-style barge-in - Research

**Researched:** 2026-10-26
**Domain:** speaker verification (sherpa-onnx), false-interruption pause/resume, AEC3 on a laptop
**Confidence:** MEDIUM (numbers below were measured this session on the user's phone clips and synthetic voices, not on the laptop mic)

## Summary

The intended design is sound and matches how LiveKit Agents does it (pause, wait for words, resume on a false alarm). Two changes to the plan: (1) use **NeMo TitaNet-small**, not CAM++ or WeSpeaker. In a test on this machine it was the only model that separated Snow's own Kokoro voice from the user (cosine <= 0.07 for Snow, >= 0.71 for the user on whole phrases), and it costs ~40 ms per 1 s of audio on one CPU thread. (2) Make the "duck" a real **pause that stops consuming samples** (not gain 0), so playout `played` stays truthful, the remaining reply can resume from the pause point, and the mic hears the user without Snow's voice while the verifier decides.

sherpa-onnx installs cleanly: pin `sherpa-onnx==1.13.8` (published 2026-09-10, before the 2026-10-08 `exclude-newer`; no per-package override needed). It pulls `sherpa-onnx-core==1.13.8`, which bundles its own `onnxruntime.dll`. That does NOT clash with pipecat's `onnxruntime 1.24.4` (verified, see below).

**Primary recommendation:** Pause on the first 150 ms of speech over Snow, verify the post-pause audio with TitaNet-small (decide between 0.6 s and 1.2 s of speech), confirm the cut only on a speaker match plus real words, otherwise resume with a 30 ms fade-in.

## Project Constraints (from CLAUDE.md)

- Python 3.12 core, uv, hash-locked deps; `onnxruntime~=1.24` CPU stays (pipecat pin). No new packages except the user-approved sherpa-onnx (2026-10-26).
- Supply-chain policy: `exclude-newer = "2026-10-08T00:00:00Z"` in pyproject.toml (confirmed, line 45).
- Privacy: audio in memory only (D-18); no secrets/personal data in logs; speaker verification is mandatory security, not optional.
- Never `cd`; use `uv --directory`, `git -C`.
- Hard-coded spoken phrases are forbidden (the "resume" after a false alarm must not announce anything).

## 1. sherpa-onnx speaker ID

### Package
| Item | Finding | Source |
|------|---------|--------|
| Version | `sherpa-onnx==1.13.8`, cp312 win_amd64 wheel 2,287,856 B, sha256 `566e49ad3fb2aa8ceb723a52f9809aa6c2ee0a5eb3b0946c3fd2374af807a5c6`, uploaded 2026-09-10. Requires `sherpa-onnx-core==1.13.8` (win_amd64 wheel 16 MB, sha256 `5579e80196d516e6dae23c8f629292ce3142ab8869925d32b94612fd86f93733`) | [VERIFIED: pypi.org JSON API, run this session] |
| Newer | 2.0.0 (2026-10-23) and 2.0.1 (2026-10-26) exist but are newer than `exclude-newer`; do not use | [VERIFIED: pypi.org JSON API] |
| License | Apache 2.0 ("Apache licensed, as found in the LICENSE file") | [VERIFIED: PyPI metadata] |
| onnxruntime | `sherpa-onnx-core` ships `sherpa_onnx/lib/onnxruntime.dll` (17.8 MB) and `sherpa-onnx-c-api.dll` | [VERIFIED: inspected wheel contents] |

**No clash with pipecat's onnxruntime.** I installed both wheels with `uv pip install --target` against the project venv (python 3.12.13, onnxruntime 1.24.4) and imported in both orders, creating a sherpa extractor and a plain `onnxruntime.InferenceSession`. Both orders worked. Loaded-module listing showed `sherpa_onnx\lib\onnxruntime.dll` plus pip's `onnxruntime_pybind11_state.pyd` (pip's wheel links ORT statically, so there is no second `onnxruntime.dll` name to collide). [VERIFIED: ran it]. Residual risk: ~18 MB of extra RAM and a second ORT thread pool; set `num_threads=1`.

Package Legitimacy Audit (seam run this session):

| Package | Registry | Age | Source Repo | Seam verdict | Disposition |
|---------|----------|-----|-------------|--------------|-------------|
| sherpa-onnx | PyPI | first release 2023-11-21; pinned 1.13.8 is 2026-09-10 | github.com/k2-fsa/sherpa-onnx | SUS ("too-new", "unknown-downloads") | Approved by the user 2026-10-26. The verdict keys on today's 2.0.1 upload; the pinned 1.13.8 is 6 weeks old. Install with `==1.13.8` and hash-lock via `uv.lock`. No human-verify task needed beyond the user's approval. |
| sherpa-onnx-core | PyPI | same release train | same repo | SUS (same reason) | Transitive, pinned by sherpa-onnx. |

### API (verified by `dir()` on the installed 1.13.8 module)
- `SpeakerEmbeddingExtractorConfig(model=..., num_threads=1, debug=False, provider="cpu")`
- `SpeakerEmbeddingExtractor(cfg)` has `dim`, `create_stream()`, `is_ready(stream)`, `compute(stream)`.
- Flow: `st = ex.create_stream(); st.accept_waveform(sample_rate=16000, waveform=float32_array); st.input_finished(); vec = ex.compute(st)` (list of floats; I wrap with `np.array` and L2-normalize).
- `SpeakerEmbeddingManager(dim)` has `add, remove, search, verify, score, all_speakers, num_speakers`. **Use plain numpy cosine instead**: the raw score is needed for calibration and logging.

### Model choice (all from the `speaker-recongition-models` release of k2-fsa/sherpa-onnx; checksums match the release's `checksum.txt`)
Measured on this laptop's CPU, 1 thread, enrolling on 20 of the user's 33 phone clips (trimmed, 0.8-2 s) and scoring 13 held-out clips plus impostors. Impostors: Snow's own voice (Kokoro `bm_daniel`, speed 0.9, 6 lines), 6 real Chinese-speaker wavs from the release, 60 other Kokoro voices. [VERIFIED: ran it this session; scripts in the OS temp dir, not committed]

| Model | Size | ms per 1 s clip | Genuine (whole clip) | Snow's voice max | Verdict |
|-------|------|-----------------|----------------------|------------------|---------|
| `nemo_en_titanet_small.onnx` | 40.3 MB | ~39 | 0.71-0.91 | **0.07** (others <= 0.25) | **Use** |
| `wespeaker_en_voxceleb_resnet34_LM.onnx` | 26.5 MB | ~133 | 0.76-0.92 | 0.89 | Reject: scores Snow like the user |
| `wespeaker_en_voxceleb_CAM++.onnx` | 29.3 MB | ~63 | 0.29-0.94 | 0.83 | Reject |
| `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx` | 29.6 MB | ~18 | 0.20-0.99 | 0.86 | Reject |

Chosen model: URL `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx`, 40,257,283 bytes, **sha256 `ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e`** (computed on my download and equal to the release `checksum.txt` line) [VERIFIED]. Embedding dim 192. License: the NGC page says "License to use this model is covered by the license of the NeMo Toolkit" (toolkit is Apache 2.0) [CITED: catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small]; re-confirm before any public distribution [ASSUMED for redistribution terms].

### Accuracy on short audio and noise (TitaNet-small, same enrollment) [VERIFIED: ran it]
| Test | min / mean / max cosine |
|------|-------------------------|
| genuine, whole clip (0.8-2 s) | 0.71 / 0.83 / 0.91 |
| genuine, first 0.5 s | 0.07 / 0.55 / 0.77 |
| genuine, first 0.3 s | -0.03 / 0.32 / 0.49 |
| genuine + white noise 10 dB SNR | 0.56 / 0.69 / 0.79 |
| genuine + white noise 0 dB | 0.48 / 0.57 / 0.75 |
| user mixed with Snow's voice at -6 dB | 0.33 / 0.45 / 0.63 |
| Snow's voice, 0.5 s crops | -0.23 / -0.06 / 0.07 |
| real other speakers (6) / 60 Kokoro voices | max 0.25 / max 0.19 |

Reading: below 0.5 s the genuine score is unreliable, so **decide on >= 0.6 s of post-pause speech, preferably 0.8-1.2 s**. Talk-over mixtures drop genuine scores to ~0.33-0.63, which argues for a threshold well below the "clean" genuine range.

**Threshold:** default `0.35`, tunable in `config/voice.toml`; accept `>= 0.35`. Impostors in this test stay <= 0.25 and noisy/mixed genuine stays >= 0.33. Calibration (in `enroll-voice`): record 30 s on the laptop mic, cut into 1.5-3 s segments, enrol the L2-normalized mean of all but 5 held-out segments, then report held-out genuine p5 (from the 0.8 s crops) and impostor max (Snow's own TTS captured through the speakers, plus any TV audio the user plays). Set `thr = clamp(midpoint(impostor_max, genuine_p5), 0.30, 0.60)` and refuse to save the voiceprint if `genuine_p5 - impostor_max < 0.15`. **Caveat:** only 13 genuine clips of one phrase, phone mic, synthetic and non-English impostors; the number is a starting point and must be recalibrated on the laptop mic (the loopback self-test does this).

## 2. False-interruption patterns (ideas, not code)

| System | Knob | Default |
|--------|------|---------|
| LiveKit Agents `turn_handling.interruption` | `min_duration` (speech needed to count) | 0.5 s |
| | `min_words` (needs STT) | 0 (so VAD alone interrupts by default) |
| | `false_interruption_timeout` (silence/no transcript before calling it false) | 2.0 s |
| | `resume_false_interruption` (resume "from where it left off") | True |
| Pipecat 1.12 `MinWordsUserTurnStartStrategy` | `min_words`, applies only while the bot is speaking; 1 word otherwise; `use_interim` default True | docs give no numeric default |
| Pipecat `VADUserTurnStartStrategy` | interrupts as soon as VAD fires; default start strategies are VAD + Transcription | n/a |

[CITED: docs.livekit.io/reference/agents/turn-handling-options.md; docs.pipecat.ai/server/utilities/turn-management/user-turn-strategies]. LiveKit warns that resume is ignored if the audio output cannot pause: the pause primitive is the load-bearing part. Snow's current 0.4 s / 1.0 s release is in the same range as LiveKit's 0.5 s / 2.0 s; keep Snow's shorter release because the verifier decides earlier.

Transferable ideas: pause first and call it false only when no words arrive; count words, not VAD time, before a **cut** (Pipecat min-words only while the bot talks); resume silently (no speech, no announcement).

## 3. Resume after a pause: hold samples, do not re-synthesize

Hold the remaining samples in `Playout._chunks` and continue from the pause point. Re-synthesis costs a new TTS call (RTF, latency, a prosody jump) and breaks the `_Reply.heard(played)` text mapping. Pitfalls found in `src/snow/voice/playout.py` (read this session):

1. **Pause must stop consuming, not set gain 0.** The callback does `self._played += filled` only for samples it takes from `_chunks`. Gain 0 would advance `played` and lose reply text silently; stopping consumption keeps `heard()` right when the pause turns into a cut.
2. **Bypass the drain/underrun branches while paused.** `if filled < frames and self._ended: drained = True; self._reset_utterance()` would fire `on_drained` (and discard the held reply) when a paused buffer yields `filled = 0`. The `elif filled < frames` branch would also count an underrun and reset the threshold. Add a `_paused` check before both.
3. Ramp the pause and the resume (30 ms, same `_DUCK_RAMP_S`; use the existing `_fade`/gain machinery) to avoid clicks.
4. While paused, TTS keeps pushing into `_chunks`; bounded by one reply and the <= ~1.2 s pause, fine. Do not stop the synthesis task.
5. **Echo reference:** `on_render(out)` runs every block, so pausing feeds the canceller zeros that equal what is played, which is correct. The pause ramp must be applied before `on_render` (already the rule for gain). Snow's echo tail (room + canceller adaptation, ~100-350 ms measured in the repo) is still in the mic right after the pause: **do not verify audio from the first ~250 ms after pause onset**. Verify the speech that follows; at that point Snow is silent, so residual echo no longer pollutes the embedding or the transcript. This is the main benefit of pause-first.
6. Resume position: continuing exactly where it stopped loses ~0.2 s the listener already half heard; acceptable. A short rewind is optional, skip.

## 4. WebRTC AEC3 via livekit `AudioProcessingModule`

- Constructor flags `echo_cancellation`, `noise_suppression`, `high_pass_filter`, `auto_gain_control`; methods `process_stream`, `process_reverse_stream`, **`set_stream_delay_ms(delay_ms)` exists**; frames must be exactly 10 ms [VERIFIED: `.venv/Lib/site-packages/livekit/rtc/apm.py` lines 15-36, 41-96].
- The repo already tried the delay hint: "the hint changed nothing for true delays up to 500 ms, and PortAudio's latencies understate the real path on this laptop" (`src/snow/voice/aec.py` lines 44-45) [VERIFIED]. Do not spend time on it again.
- Typical residual-echo causes on laptops (nonlinear loudspeaker distortion, speaker-to-mic coupling inside one chassis, variable/large output delay, clock drift between output and input devices, double talk freezing adaptation): general AEC3 knowledge, a source describes AEC3 as an adaptive linear filter plus a nonlinear residual suppressor [CITED: forasoft.com/learn/audio-for-video/glossary/terms-audio/aec3]; the specifics are [ASSUMED]. Practical consequence: AEC cannot be the only defense; that is the reason for pause + verify + echo-text filter.
- **Noise suppression for the VAD path: leave it off.** It is a 'speech-shaped' filter that changes spectra (hurts speaker embeddings and Whisper) and the repo already measured that AGC-type processing shifts VAD/wake levels (aec.py header). If a noisy-room test shows false VAD triggers, A/B it behind a config flag, not by default [ASSUMED effect on embeddings; not measured].
- Lowering Snow's own playback level during barge-in checks (duck) reduces nonlinear echo too; keep the existing duck as a fallback for the first 150 ms.

## 5. Pitfalls (verification)

- **Verify the AEC output (the stream VAD/STT already hear), not raw mic.** Enrol through the same `capture()` path so the channel matches; with no render energy the canceller is near pass-through, so enrollment is effectively raw mic. During talk-over AEC3 can attenuate/warp the user (my mixture test: 0.33-0.63), so the threshold must be set from talk-over data, not clean data [VERIFIED for mixtures, ASSUMED for real AEC3 behavior].
- **Enrollment mic mismatch:** the 33 phone clips ("Hey Snow", ~1 s) are a different channel and phrase. Use them only as a supplement; primary enrollment is 30 s of free speech on the laptop mic. Run a cross-check (laptop-centroid vs phone-clip cosine) and report it.
- **CPU:** TitaNet-small ~39 ms per 1 s audio on one thread (this laptop, [VERIFIED]); 3 checks per barge-in episode is ~0.1 s CPU. The engine runs on the audio thread, so call the verifier from a worker thread and post the verdict back through the existing `_inbox` pattern; never run it inline in the mic callback.
- **Determinism:** `TurnEngine` is audio-time-only (module docstring). An async verdict breaks pure determinism; give the verifier a synchronous fake in tests (same pattern as `duck`, `echo_warming`).
- **Privacy:** a voiceprint is a biometric. Store only the 192-float centroid (and per-segment vectors if wanted), never the audio; keep it in a git-ignored per-user path, wrap with DPAPI (`win32crypt`, already a stack member) if cheap; never log vectors; scores may be logged. The 33 clips and enrollment recording stay out of git and out of any log or HUD event. Delete on `snow dev enroll-voice --reset`.
- **Single speaker:** a family member or TV voice that scores >= threshold is accepted; this is Alexa-level, not forensic.
- **Wake phrase** keeps its immediate cut (turn.py `on_wake`), untouched by the verifier.

## Architecture notes (integration points, read this session)

- `turn.py::_listen_over` currently ducks at `duck_after_ms` and calls `_barge_in()` at `_barge_min()`. Change: at 150 ms call `pause()` (new `TurnEngine.pause: Callable[[bool], None]`, wired to `Playout`); at the confirm point (min speech + words check) request verification instead of cutting; `verdict` through `_inbox`; reject or timeout (`duck_release_s`, 1.0 s) calls resume. `_ring` already keeps `duck_release_s + 0.3 s` of audio, which covers the post-pause segment.
- `playout.py::set_gain` ramps in 30 ms and `abort` resets: add `set_paused(bool)` with the callback rules from section 3.
- `pipeline.py` wires `self._engine.duck = self._playout.set_gain` (line 532) and `on_render=aec.render`; add the verifier and the 10 s "what Snow said" buffer here (`_Reply.heard()` already knows the spoken text).
- Self-echo filter: `difflib.SequenceMatcher` (stdlib) ratio on normalized words against Snow's last ~10 s of spoken text; no new dependency. Words check: reuse the local Moonshine partials already running during the turn.

## Don't Hand-Roll

| Problem | Use instead |
|---------|-------------|
| Speaker embedding | sherpa-onnx `SpeakerEmbeddingExtractor` + TitaNet-small |
| Text similarity for the echo filter | stdlib `difflib` |
| Voiceprint at-rest protection | `win32crypt.CryptProtectData` (pywin32 already in the stack) |
| Model integrity | pinned SHA-256 check before load (same pattern as the wake word `model_sha256`) |

## Validation Architecture

| Behavior | Test | Command / note |
|----------|------|----------------|
| Cosine decision, thresholds | unit, fake verifier returning scores | `uv run pytest tests/voice -k barge -x` |
| Pause holds samples, `played` frozen, no `on_drained` while paused | unit on `Playout` with the stream factory fake | add to existing playout tests |
| Engine: pause at 150 ms, resume on reject, cut on confirm | unit on `TurnEngine` (audio-time) | existing fake VAD |
| Voiceprint never logged / never in git | grep test + `.gitignore` check | |
| Hardware loopback: long replies and noise through real speakers into the real mic pipeline, zero confirmed barge-ins | hardware suite (not CI) | positive control: play a stored user clip through a second output stream **not** fed to `on_render`; the canceller treats it as near-end speech like a live user; it must confirm a barge-in. Caveat: a speaker-replayed voice is not a live voice, so use it for regression, not for the final threshold. Allow >= 2 s of AEC warm-up (`WARMUP_S`) before asserting. |
| Self-echo and word filters | unit with transcripts of "Certainly." / "Understood, sir." and "Peace." | |

Wave 0: `uv add sherpa-onnx==1.13.8`, model download + sha check helper, `models/speaker/` (git-ignored).

## Security Domain

| ASVS | Applies | Control |
|------|---------|---------|
| V2/V4 (who may command) | yes | speaker verification gate; wake still needs the wake phrase |
| V6 Cryptography | yes | DPAPI for the voiceprint, not hand-rolled |
| V8/Data protection | yes | biometric stays local, not logged, not committed |
| V10 Supply chain | yes | `==1.13.8`, hash-locked `uv.lock`, model SHA-256 |

Threats: replay of the user's voice from a phone or TV (Spoofing; not stopped by embedding verification, accepted risk), poisoned model download (Tampering; SHA-256), voiceprint exfiltration (Info disclosure; DPAPI + local only).

## Assumptions Log

| # | Claim | Risk if wrong |
|---|-------|---------------|
| A1 | TitaNet-small redistribution terms (NeMo license) fit later public distribution | Swap model before shipping; personal use is fine |
| A2 | Specific laptop residual-echo causes and AEC3 behavior during double talk | Threshold needs real-hardware calibration (planned) |
| A3 | Enabling APM noise suppression would hurt embeddings/Whisper | Missed gain on noisy rooms; A/B behind a flag |
| A4 | Threshold 0.35 transfers to the laptop mic | False accepts/rejects until `enroll-voice` calibrates it |
| A5 | Pause/resume does not upset AEC3 delay tracking | Residual echo after resume; the loopback test would catch it |

## Open Questions (RESOLVED)

1. Does TitaNet-small stay separated from Snow's voice with real speaker-to-mic acoustics (room, distortion)? The loopback self-test answers it; if the margin is < 0.15, enroll-voice must refuse and report it.
   **RESOLVED:** answered by measurement, not assumption. The hardware loopback self-test in plan 261026-wvr-02 (Task 2, `tests/hardware/test_bargein_loopback.py`) records the speaker scores of Snow's own voice through the real speakers. `snow dev enroll-voice` (plan 02, Task 1) refuses to save when the calibrated margin is under 0.15.
2. Whisper/Groq cost of an extra transcript per paused episode: decide whether words check uses only local Moonshine (recommended).
   **RESOLVED:** local Moonshine only. The barge-in check transcribes its window with `LocalStt.transcribe` (plan 261026-wvr-01), so no extra Groq request is made and no audio leaves the PC for the check.

## Sources

- Measured this session (HIGH): PyPI JSON API for sherpa-onnx / sherpa-onnx-core; wheel inspection; k2-fsa/sherpa-onnx release `speaker-recongition-models` (asset list, `checksum.txt`); DLL-load and accuracy scripts run against the project venv.
- Read this session (HIGH): `src/snow/voice/turn.py`, `playout.py`, `aec.py`, `config/voice.toml`, `pyproject.toml`; livekit `apm.py`.
- [CITED] https://docs.livekit.io/reference/agents/turn-handling-options.md ; https://docs.pipecat.ai/server/utilities/turn-management/user-turn-strategies ; https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small ; https://www.forasoft.com/learn/audio-for-video/glossary/terms-audio/aec3
- Not verified: the k2-fsa docs pages for speaker-identification returned 404; no recommended threshold was found upstream, so the threshold above is empirical.

**Valid until:** ~2026-11-25 (sherpa-onnx 2.x is out; re-evaluate the pin after the `exclude-newer` date moves).
