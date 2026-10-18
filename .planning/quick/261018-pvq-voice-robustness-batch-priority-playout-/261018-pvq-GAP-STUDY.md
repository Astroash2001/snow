# Snow voice loop vs mature open-source assistants: gap study

Date 2026-10-18. Read-only study. Clones (untrusted, never executed) are in `.../scratchpad/gap/`.

Tags: **[V]** read in source this session (path:line). **[C]** from a doc page fetched this session. **[I]** inferred, not measured. **[A]** from memory, unchecked.

References studied (commit, licence): Pipecat `a2cb3d6` 2026-10-17, BSD-2-Clause. LiveKit Agents `01fb91f` 2026-10-17, Apache-2.0. ovos-dinkum-listener `b147339` and ovos-audio `64f1c08`, Apache-2.0. rhasspy/wyoming-satellite `7a3ba2b` 2026-01-24, MIT. rhasspy/wyoming-openwakeword `419701f` 2025-10-30, Apache-2.0. livekit-wakeword, Apache-2.0, pushed 2026-09-30 (GitHub API). Open Interpreter 01: AGPL-3.0, last push 2024-11 (GitHub API); not studied, stale and not copyable. `OHF-Voice/wyoming-satellite` and `OHF-Voice/wyoming-openwakeword` do not exist; the rhasspy repos are the live ones. All five studied repos permit copying code with attribution (AGPL one excluded); ideas are free anyway.

## a. Turn-taking, endpointing, false interruptions

**Snow now.** Silero VAD threshold 0.5, `start_secs` 0.2, `stop_secs` 0.2, `max_silence_secs` 3.0, `barge_in_min_ms` 250 [V voice.toml:22-28]. After 0.2 s of silence Smart Turn is asked once; if "incomplete", the buffer is cleared and the engine waits up to 3 s [V turn.py:335-348]. Barge-in: 250 ms of VAD speech while Snow talks calls `playout.abort()` and `_interrupt`, which cancels synthesis, adds the turn to `_dropped`, emits `TurnCancelled` and `ReplyInterrupted` [V turn.py:266-293, pipeline.py:429-437, 616-629]. It is irreversible and needs no words. A cough, echo or door slam kills the reply for good; the empty transcript then just releases the turn (`pipeline.py:697-699`) and Snow stays silent.

**References.**
- LiveKit `voice/turn.py` `InterruptionOptions`: `min_duration` 0.5 s, `min_words` 0, `resume_false_interruption` True, `false_interruption_timeout` 2.0 s, `backchannel_boundary` (1.0, 1.0) [V turn.py ~L120-165]. Mechanism [V agent_activity.py:2339-2404, 4919-5064]: VAD speech only **pauses** playout (`audio_output.pause()`); the interruption commits only when a final transcript or turn commit arrives; if the user goes quiet for 2 s with no commit, playout **resumes** and an `agent_false_interruption` event fires. `min_words` is checked against the live transcript before pausing. `aec_warmup_duration = 3.0`: audio interruptions are ignored for 3 s after the agent starts speaking, "to prevent the agent from being interrupted by echo before AEC is ready" [V agent_session.py:117, 531-534]. Endpointing: fixed 0.5/3.0 s, or `DynamicEndpointing` where the minimum delay is an EMA (alpha 0.9) of the user's own mid-turn pauses [V endpointing.py ~L50-75].
- Pipecat: `MinWordsUserTurnStartStrategy` needs `min_words` only while the bot speaks, 1 word otherwise [V turns/user_start/min_words_user_turn_start_strategy.py:94-110]. `EmptyUserTurnConfig`: a turn that interrupted the bot but yields no transcript re-runs the LLM with a "briefly ask them to repeat" prompt, max 1 in a row [V turns/empty_user_turn.py]. VAD defaults: confidence 0.7, start 0.2, stop 0.2, `min_volume` 0.6 [V audio/vad/vad_analyzer.py:25-28].
- OVOS: `speech_seconds` 0.3, `silence_seconds` 0.7, `timeout_seconds` 10 [V voice_loop.py:141-144]; VAD reset after every command to avoid a stuck "always silence" state [V voice_loop.py:983-987] (Snow already does this: `turn.py:352-355`). OVOS mutes the mic during playback if configured [V service.py:984]; no AEC.

**Gap.** Snow has no pause-then-commit stage, no minimum words, no resume, no post-speech grace window. Short-utterance endpointing itself is comparable to Pipecat's; per-user adaptive delay is a nice-to-have, not a fix.

## b. STT on short or quiet clips

**Snow now.** Groq `whisper-large-v3-turbo`, `language="en"`, `response_format="json"`, no `prompt`, no `temperature` [V stt_groq.py:76-81, voice.toml:48-53]. Raw int16 PCM goes up with no gain, normalisation or padding [V stt_groq.py:29-37, pipeline.py:665-674]. No minimum-clip rule, no confidence or hallucination filter; only "empty text means release" and the wake-phrase regex strip [V pipeline.py:689-699]. Wake audio is sent with the "Hey Jarvis" pre-roll included. Local Moonshine `tiny` is the fallback [V voice.toml:44-46]. Tone code knows loudness (`ref_loudness_dbfs = -24`) but nothing uses it to fix input level.

**References.**
- Groq docs [C console.groq.com/docs/speech-to-text]: `prompt` (224 tokens) guides spelling; `temperature` 0 recommended; `verbose_json` returns `avg_logprob` (about -0.5 or lower may signal trouble), `compression_ratio`, `no_speech_prob` and the docs say to flag segments outside set ranges. Turbo WER 12% vs `whisper-large-v3` 10.3% on Groq's table. Minimum billed length 10 s per request. Service downsamples to 16 kHz mono.
- Pipecat local Whisper drops segments with `no_speech_prob` at or above 0.4 (MLX 0.6) [V services/whisper/stt.py:449-455, 525, 610-620]. Its Groq path does not (`base_stt.py` only reads `response.text`, L291).
- Wyoming satellite: `--mic-auto-gain 5` (WebRTC AGC, 0-31 dBFS), `--mic-noise-suppression 2`, `--mic-volume-multiplier`, applied to the mic stream before wake/VAD/STT; README recommends the first two [V satellite README L160-171, settings.py MicSettings]. `debug_recording_dir` dumps audio for diagnosis [V settings.py].
- OVOS: speech trimmed for STT but never below 1 s [V voice_loop.py:903-931]. LiveKit Silero plugin pads each speech chunk with 0.5 s of prefix and keeps 0.55 s of silence [V plugins-silero/vad.py:63-67].

**Gap.** (1) Level: voiced speech at -37 to -42 dBFS is 12 to 18 dB under Snow's own -24 dBFS reference. Silero and openWakeWord were not trained for such levels, and Whisper turbo is weakest on short, quiet clips [I]. The references fix level at the source with AGC; Snow does nothing. (2) No confidence data requested, so no way to reject "Thank you."-style hallucinations or dropped words. (3) No `prompt` for vocabulary ("Snow", "Claude Code", "Antigravity", "OpenCode"). (4) Dropped word in "you are up buddy" cannot be diagnosed today: no per-turn level, no logprob, no raw-vs-stripped text log.

## c. TTS playout robustness

**Snow now.** `Playout` is a ring buffer behind one WASAPI float32 stream, 20 ms blocks, prebuffer 300 ms [V playout.py:23, tts.toml:29]. The callback zero-fills the block and, once `_playing` is true, never goes back to buffering: an empty queue just emits silence, with no log and no counter [V playout.py:155-190]. Plan 01-26 says so itself: "If synthesis ever falls below real time the speaker just goes quiet during the gap (no re-buffering)", validated only at RTF 0.40-0.42 on an idle CPU [V 01-26-SUMMARY.md:100, 127]. Synthesis runs clause by clause, strictly sequential [V router.py:255-256]. Pocket: `torch_threads = 4`, defaults otherwise, `TTSModel.load_model()` with no options [V pocket.py:48-49, tts.toml:42]. No process or thread priority code exists anywhere in `src/` (grep); the supervisor spawns workers with only `CREATE_NO_WINDOW` [V supervisor.py:114]. The machine has 16 logical, 12 physical CPUs [V psutil], so a hybrid Intel part [I].

**References.**
- Pipecat local transport: blocking PyAudio `write` in a one-thread executor [V transports/local/audio.py:186-200]; grep for underrun/prebuffer in the core transports finds nothing relevant. Output is paced in 10 ms chunks with a `BOT_VAD_STOP_SECS` 0.35 stop heuristic [V base_output.py:61, 148]. No slower-than-real-time handling.
- LiveKit: no underrun handling found either (grep). OVOS-audio synthesises each sentence **fully to a file, then plays it** [V ovos_audio/playback.py:124-168]: no underruns inside a sentence, at the cost of first-audio latency.
- Windows QoS [C learn.microsoft.com/windows/win32/procthread/quality-of-service]: windowless background processes can be classed Low/Utility QoS ("on battery, selects most efficient CPU frequency and schedules to efficient core"); only "processes determined to be playing audio" or explicitly tagged ones are HighQoS; `SetProcessInformation(ProcessPowerThrottling, EXECUTION_SPEED)` tags a process HighQoS.

**Gap.** No reference solves this; the answer is Snow-specific. Likely cause of problem 4: CPU contention plus Windows efficiency-core scheduling of a hidden worker (Moonshine, Silero, openWakeWord, Pocket's 4 torch threads plus its Mimi decoder thread, HUD all compete) [I, unmeasured]. Missing: priority/QoS opt-in, rebuffer-on-underrun, RTF measurement, RTF-aware fallback.

## d. Always-on robustness

**Snow now.** Mic: reopen with 1 s to 30 s backoff when `finished_callback` fires or the open fails; COM joined on the mic thread [V sources.py:120-186]. Gaps: no stall detector (`q.get(timeout=0.1)` Empty just loops forever, L184-186); the device is chosen once from `query_hostapis()` default at open, so a changed default device (plugging USB-C earphones) is not followed [V L72-86]; python-sounddevice has `_terminate()`/`_initialize()` for re-enumeration [V .venv sounddevice.py:2918-2950], unused [I that the list is otherwise cached]. Speaker: the output stream is created once and kept [V playout.py:114-121]; no `finished_callback`, no recreate after device loss or sleep. Supervisor: `HEARTBEAT_TIMEOUT_S = 6.0`, worker beats every `HEARTBEAT_S = 2.0`, kill on `now - beat > 6` [V supervisor.py:39, 263-266, hubclient.py:31]. Clock is `time.monotonic`, which is `GetTickCount64()` on this Python 3.12.13 [V get_clock_info]. No resume/suspend/power-broadcast code exists (grep) [V]. After laptop sleep the hub's first tick sees `now - beat` equal to the sleep duration and kills a healthy worker [I, consistent with the symptom; whether GetTickCount64 counts sleep time not verified].

**References.**
- LiveKit supervised processes: ping every 5 s, "unresponsive" warning above 2.5 s round trip, kill only after **60 s** without a pong, and it dumps all-thread stack traces (`faulthandler`) plus asyncio tasks before killing [V worker.py:617-619, ipc/supervised_proc.py:486-531, proc_client.py:163-196].
- OVOS: systemd watchdog ping from its own thread every 0.5 s [V service.py:71-72, 557-564]; `read_chunk()` returning None is tolerated [V voice_loop.py:312-317]; hotword engine reload on failure [V L364-368]; "sleep" there is a listening mode, not OS suspend; no OS-resume or hot-plug code found in the listener.
- Wyoming satellite: mic is a separate service with `reconnect_seconds` 3.0; the whole satellite restarts after `restart_timeout` 5.0 [V settings.py, satellite.py:357-364]. Repair by restart, no suspend awareness either.
- Pipecat local transport: opens streams once in `setup`; no hot-plug [V local/audio.py:155-161].

**Gap.** Nobody in the references handles OS sleep or device change well; Snow can be the first. Needed: resume-aware supervisor, mic stall watchdog, output-stream recreate, hang diagnostics.

## e. Wake word

**Snow now.** `hey_jarvis` stand-in, threshold 0.5, `patience_frames` 2 (80 ms frames), refractory 1.5 s, ONNX, no verifier [V voice.toml:9-14, wake.py:62-102]. Plan 01-30 (not executed) trains "hey snow" with `livekit-wakeword 0.3.0` on Colab, target under 1 false accept per hour, at least 90% recall on 50 user utterances [V 01-30-PLAN.md must_haves].

**References.**
- wyoming-openwakeword defaults: threshold 0.5, `--trigger-level` 1, `--refractory-seconds` 2.0 [V __main__.py:29-45]; satellite refractory 5.0 s [V settings.py]. Snow's values are in the normal range.
- openWakeWord custom verifier [C github.com/dscripka/openWakeWord/blob/main/docs/custom_verifier_models.md]: logistic regression on the shared features, at least 3 positive clips of the user, about 10 s of the user's non-wake speech, optional 5 s of room noise or recorded false activations ("one of the most effective ways" to cut false activations); used via `Model(custom_verifier_models={"name": "v.pkl"}, custom_verifier_threshold=0.3)`; "not a substitute for true speaker verification". Snow's `Model(...)` call does not pass it [V wake.py:62-67].
- livekit-wakeword [C docs.livekit.io/agents/multimodality/audio/wakeword]: stages generate, augment, train, export, eval (DET curve); example config `n_samples` 10,000, `steps` 50,000, `target_fp_per_hour` 0.2, `conv_attention`; `pip install "livekit-wakeword[train,eval,export]"`; ONNX models are openWakeWord-compatible; Python 3.11+. Matches the plan.
- Fallback recipe: community `alfiedennen/openwakeword-colab-2026` (MIT): patched Colab for Python 3.12, `piper-phonemize-cross`, hard-negative mining, FP/hour on ACAV100M slices; author reports 13/13 recall and no phantom fires in 30 min, no formal FA/h [C, community claim]. Original openWakeWord notebook is reported broken on current Colab [C, third-party claim].
- HA-style audio conditioning (AGC 5, NS 2) is how satellites make wake work on weak mics (section b).
- openWakeWord pretrained models carry a non-commercial licence [A]; irrelevant once the custom model replaces the stand-in.

**Gap.** Only the human-run training step; and the wake gate also suffers from quiet input (problem 5 level fix helps it). A verifier layer is optional and overlaps the mandatory speaker-verification work (no speaker-verification module exists in `src/snow/voice/` yet [V file list]).

## f. Other things mature assistants have that Snow lacks

- Preemptive generation (LiveKit): start the LLM on the interim transcript, cancel if it changes; defaults `max_speech_duration` 10 s, `max_retries` 3, `preemptive_tts` False [V turn.py PreemptiveGenerationOptions]. Snow waits for the Groq final before the brain starts. This targets the "reply in about 1 s" bar.
- Mic muting around Snow's own wake acknowledgement: Wyoming `mute_during_awake_wav` plus 0.5 s [V settings.py MicSettings].
- Per-turn diagnostics without audio on disk (D-18): level dBFS, logprob, raw and stripped text. Wyoming's `debug_recording_dir` writes audio, which conflicts with D-18 unless opt-in.
- User-idle controller (Pipecat) and empty-turn recovery prompt. Snow has the 45 s conversation timeout only.
- Adaptive ML "backchannel" interruption model (LiveKit `mode: adaptive`): needs LiveKit inference, skip.

## Top 10 changes for Snow (impact vs effort)

| # | Change | Fixes | Impact / effort | Copy from (licence) |
|---|--------|-------|-----------------|---------------------|
| 1 | **Voice worker QoS and priority.** At worker start call `SetProcessInformation(ProcessPowerThrottling, EXECUTION_SPEED off)` via ctypes and set `ABOVE_NORMAL_PRIORITY_CLASS` (psutil is already a dependency, `chatterbox.py:38`). Do the same for hub. | **4**, helps **6** | High / S. Cause is inferred; verify by A/B on battery. | MS QoS doc [C]; no reference does it |
| 2 | **Playout rebuffer and adaptive start.** On underrun while `_playing` and not `_ended`, fade out, drop to buffering, resume at 200 to 300 ms (hysteresis). Track synth RTF (EWMA of pushed audio seconds vs wall seconds); if RTF above 0.7 hold playback until the whole clause is buffered (the OVOS model). Count underruns and RTF in `TurnTiming`/log. | **4** | High / S-M | Original; OVOS sentence-then-play idea (Apache-2.0) |
| 3 | **Resume-aware supervisor.** Tick-gap guard: if `now - last_tick > ~3 s`, the hub was frozen: reset all heartbeats to `now`, skip hang verdicts that tick. Raise kill timeout to 15 to 20 s with a warning at 6 s; `faulthandler.dump_traceback` into the log before kill. | **6** | High / S | LiveKit `ipc/supervised_proc.py` (Apache-2.0), idea only |
| 4 | **Device resilience.** Mic: stall watchdog (no frames for 1.5 s while stream active, so reopen), follow default-device change by re-enumerating (`sd._terminate/_initialize` while no stream is open). Speaker: `finished_callback` plus recreate on error, device change and resume. | **6** | High / M | Wyoming restart-on-failure (MIT); sounddevice API [V] |
| 5 | **Input gain stage before wake, VAD and STT.** AGC (target about -24 dBFS, cap +20 dB, limiter) plus high-pass; piggyback on the livekit APM in the AEC task (enable its AGC/NS/HPF on the capture path) rather than a second pass. Log per-turn dBFS. | **5**, helps 7 | High / S if shared with AEC, else M | Wyoming `--mic-auto-gain 5` / `--mic-noise-suppression 2` (MIT) |
| 6 | **Groq request and filter.** `response_format="verbose_json"`, `temperature=0`, `prompt` with Snow vocabulary; drop turns where `no_speech_prob` is high and `avg_logprob` low (start at Pipecat's 0.4 and Groq's -0.5, tune on logged turns); minimum voiced length 0.3 s; for clips under about 3 s try `whisper-large-v3` (10.3% vs 12% WER on Groq's table). Pad 200 ms of silence each side [A]. Keep raw and stripped text in the log. | **5** | Med-High / S | Groq docs [C]; Pipecat `whisper/stt.py` (BSD-2) |
| 7 | **Soft barge-in.** On 250 ms VAD speech over Snow: pause playout (keep buffer, stop only after 3 s), open the turn, commit (abort, cancel brain) only when the Moonshine partial or Groq final has at least 1 word (2 for non-command words); if silent for 2 s with no words, resume. Ignore audio barge-in for the first 3 s of a reply until AEC is proven. On empty-transcript cut-offs have the brain say a short "repeat that?" turn. | mitigates 3 | High / M | LiveKit `agent_activity.py` (Apache-2.0); Pipecat min-words and empty-turn (BSD-2) |
| 8 | **Train "hey snow".** Run plan 01-30 (livekit-wakeword, `n_samples` 10,000, `steps` 50,000, `target_fp_per_hour` 0.2); fallback `alfiedennen/openwakeword-colab-2026`. Later add an openWakeWord custom verifier from 3 user clips plus recorded TV false accepts. Keep threshold 0.5, patience 2, refractory 2.0 s until FP/h data exists. | **7** | Med / L (human step) | livekit-wakeword (Apache-2.0); oww verifier (Apache-2.0); colab (MIT) |
| 9 | **RTF-aware voice failover.** If Pocket's RTF EWMA stays above 1.0 for 2 replies, router prefers Kokoro (or Pocket with `load_model(quantize=True)`, which exists in pocket-tts 3.3.0 [V], effect unmeasured) until load drops. Surface "voice under load" in HUD health. | **4** worst case | Med / S-M | Original; router already supports failover |
| 10 | **Preemptive generation.** Start brain on the Moonshine final when Smart Turn says complete, cancel if Groq text differs materially; no preemptive TTS; cap at 10 s speech and 3 retries. | latency only | Med / M-L | LiveKit `turn.py` options (Apache-2.0) |

Not in the top 10 on purpose: dynamic endpointing (LiveKit `DynamicEndpointing`, Apache-2.0) is polish; Smart Turn behaviour on one-word replies was not measured here.

## What was not verified
- No measurement was run: not RTF under load, not the QoS theory, not the sleep/clock behaviour, not whether Silero's probability drops at -40 dBFS, not whether Pocket `quantize=True` helps.
- Whether `GetTickCount64` counts sleep time is unchecked; the supervisor fix works either way.
- I did not read the OVOS microphone plugins, Pipecat's rnnoise/Krisp filters in depth, or LiveKit's adaptive interruption model internals.
- `ProcessPowerThrottling = 4` and the struct layout for change 1 are from memory [A]; check `processthreadsapi.h` when implementing.
- Dropped word in problem 5 may come from the wake-phrase strip regex (`voice.toml:16-19`) or Whisper rather than level; change 6's logging settles it.
