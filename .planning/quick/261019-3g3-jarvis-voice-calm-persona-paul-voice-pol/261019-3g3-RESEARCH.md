# Calm, composed "Jarvis-like" voice for Snow: research

Researched 2026-10-19. Tags: [V] verified (read in the repo or ran it this session), [C] cited from docs/pages fetched this session, [A] assumed / not verified. No audio was played or written; all measurements are numbers computed in memory. Scripts: `.../scratchpad/voice-research/` (measure_pocket.py, measure_text.py, measure_kokoro.py, bench_dsp.py).

## Headline finding

The missing "calm" is mostly **pace and cadence**, not timbre. The Pocket voices the user likes speak briskly, and Pocket has **no speed control**. The cheap, free fixes are (1) punctuation-heavy, short-sentence wording from the LLM, (2) a small post-processing step in the playout push path (slow-down by resampling, pauses after sentences, light EQ/compression/reverb), and (3) picking `paul` as the base. None of this needs cloning, new packages or credits.

Measured on this laptop, Pocket 3.3.0 (english_2026-09, CPU, 4 threads), one 23-word line, speech span first-to-last voiced frame [V, measure_text.py]:

| Voice | Rate as the LLM writes it (words/s) | Pauses >=120 ms | Note |
|---|---|---|---|
| paul | 3.55 | 1.65 s | slowest, flattest (pitch spread about 1.1-1.25 semitones), ~113 Hz |
| george | 4.75 | 0.33 s | fast, little pause; spread about 2.4-2.8 st, ~128 Hz |
| Kokoro bm_george speed 1.0 (reference) | ~3.3 incl. lead/trail silence | n/a | george in Pocket is ~30% brisker than Kokoro's |

Same line with no punctuation at all: paul 4.57 wps, george 4.95 wps (run-on = fast, pause-less). Adding short sentences / commas / ellipses cut george to 3.9-4.2 wps and paul to 3.25 wps. So wording and punctuation are the strongest zero-cost text lever [V]. F0 comes from a crude autocorrelation estimate; charles's 71 Hz is probably an octave error, distrust it [A].
Run-to-run noise is large: the same george line was 5.76 s then 6.56 s at identical settings [V]. Judge by ear, not by one number.

## 1. Pocket TTS 3.3.0 levers [V: pocket_tts source read]

- `TTSModel.load_model(temp=None, sampler_decode_steps=1 (alias lsd_decode_steps, deprecated), noise_clamp=None, eos_threshold=-4.0, quantize=False)`; defaults file: `DEFAULT_TEMPERATURE = 0.3`. `generate_audio_stream(state, text, max_tokens=50, frames_after_eos=None, copy_state=True, stop=None)`. There is **no speed, pitch, emotion or pause parameter**. The README lists "Adding silence in the text input to generate pauses" as unsupported.
- `temp`: config comment says "Human evals preferred this model at 0.3 (equal WER/similarity/speech rate)". My test at 0.1 / 0.3 / 0.6 showed no pace or flatness change bigger than run-to-run noise (paul spread 1.10 / 1.14 / 1.37 st; george 2.85 / 2.57 / 2.84). Not worth exposing. Snow's `pocket.py:49` calls `TTSModel.load_model()` with defaults, nothing exposed.
- `frames_after_eos`: only adds a few 80 ms frames of tail (default guess 1-3). Marginal.
- `language="english_2026-09_24l"` is a bigger, "higher quality but slower" variant (README); untested here, a download plus CPU cost make it unlikely to stay real-time [A].
- **Voice conditioning is the real lever**: a voice is a KV-cache state built from an audio prompt (`get_state_for_audio_prompt`); docstring: it "captures the acoustic characteristics (speaker voice, style, prosody)" and the README says the sample's audio quality is reproduced too. So a slow, calm, clean prompt clip should transfer calmer delivery [C/A: plausible, not tested because it needs the gated weights].
- Gate: the HF cache holds only `kyutai--pocket-tts-without-voice-cloning` [V], so cloning is not unlocked. Without it, `get_state_for_audio_prompt(<file>)` raises `VOICE_CLONING_UNSUPPORTED` and only the named presets work. Terms (model card, CC-BY-4.0 licence): prohibited are "voice impersonation or cloning without explicit and lawful consent", passing audio off as genuine recordings, deception; accepting needs contact-info sharing and `hf auth login` [C: huggingface.co/kyutai/pocket-tts].
- **Pitfall:** `pocket.py:43` sets `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`, and huggingface_hub then refuses to send the cached login token [V: huggingface_hub/utils/_headers.py:147-150]. After accepting the terms, the gated download would still 401 unless that variable is unset for the one-time download.
- Licences of Kyutai's voice sets [C: huggingface.co/kyutai/tts-voices]: voice-donations CC0 (marius, javert); vctk CC BY 4.0 (george p315, charles p254, paul p259, michael p360, per the README links); voice-zero CC0 (LibriVox: peter_yearsley, stuart_bell, bill_boerst); alba-mackenna CC BY 4.0 (voice-acted Casual/Merchant/Announcer); expresso and ears non-commercial (CC BY-NC 4.0); mixed folder unmute-prod-website. Kyutai ships VCTK/LibriVox clips itself, so using them is clearly within their intent; whether a cloned *other* VCTK/LibriVox sentence counts as "explicit consent" under the model terms is a judgement for the user [A]. Safest original sources: the user's own recording (Snow's `consent = "self"`), or a paid voice actor with written AI-voice consent. LibriTTS-R is CC BY 4.0 [A: not re-checked]; its readers are mostly US.
- Snow's mood system is a no-op today: every mood in `tts.toml` is `marius`, and the base `reference` is still `marius` [V: config/tts.toml]. The audition tool is meant to rewrite the reference to the user's pick.

## 2. Text-side levers [V: persona.toml, text.py read]

Current prompt: "dry, understated, sarcastic British humour", "Prefer warm or content", "Match the length..." and a banter-gets-one-line rule; nothing about cadence, pauses or calm. `calm` is an allowed emotion but is not preferred.
What the engines honour:
- Pocket: sentence/clause punctuation drives pauses (measured above). It capitalises, appends terminal punctuation, pads <5-word inputs with spaces, and may turn `;` into `,` [V: text_chunking.py]. Ellipses and dashes are treated as weak/terminal marks. Unpunctuated text is ~30-40% faster.
- Snow's `sanitize` keeps `, . ... em-dash`, strips `[ ] { } < > | ^ ~ * #` [V: text.py]. The chunker splits the first chunk at the first comma after 3 words, so short clauses start fast.
- Cartesia: punctuation is the preferred pause method; `<break time="500ms"/>` exists but "splits the generation", costs 1 credit each and several in a row can hallucinate [C: docs.cartesia.ai ssml-tags]. Do not use breaks.
Suggested persona replacement for the manner block (original character, no film lines):
"Speak like a calm, composed, highly capable English butler-AI. Unhurried and precise. Short sentences, one idea each, with full stops and commas where a person would pause; no run-on sentences, no semicolons, no exclamation marks. Dry wit is rare and understated, one light remark at most, never in error or stress. Say 'sir' about once per reply, at a natural pause. Default to the calm emotion; use others only when the moment clearly calls for them. Understate: 'That went rather well', not 'Amazing!'" Also change "Prefer warm or content" to "Prefer calm". Consistency bonus: `calm` is Cartesia's best-supported emotion [C], Chatterbox calm=0.35 already [V], and D-36 already forces calm for stressed users.

## 3. Post-processing in numpy/scipy [V: benchmarked bench_dsp.py]

Installed in the core venv with no new dependency: numpy 2.5.3, scipy 1.18.1 (hard dep of pocket-tts METADATA), soxr 1.0.0 (transitive via pipecat; declare it directly if used), soundfile, livekit. Pedalboard is GPL, rubberband needs a binary: avoid.
Benchmark (streamed in 80 ms chunks, the size Pocket yields): high-pass 70 Hz + low-shelf +3 dB at 180 Hz + presence +2 dB at 2.8 kHz (Q 0.9) + 9.5 kHz low-pass (all `sosfilt` with carried state) + 2:1 block compressor with smoothed gain + 350 ms synthetic-noise plate-style reverb at 6% wet via `oaconvolve` with persistent tail + tanh limiter: **0.47% of one core (215x real time)**. `soxr.ResampleStream` slow-down: 0.0015 s per 7 s of audio. Pocket itself runs at ~2x real time on 4 threads, so post-processing is noise.
Slow-down trick: resample 24 kHz audio to 24000/f and play at 24000: f=0.93 gives 1.065x length and -1.26 semitones, tempo and pitch move together (deeper, "bigger" voice, mild formant shift). 0.90-0.94 is the sane range; pure time-stretch needs a phase vocoder you would have to write [A]. Pitch is only worth lowering where the base is already low (paul is ~113 Hz; a -1 to -1.5 st shift is the "few semitones" the brief asked for; do not go beyond about -2 st, formants get cartoonish [A]).
Pauses: insert silence rather than relying on the model. After a chunk ending in `.`/`?` push ~150-220 ms of zeros, after a `,` ~60-90 ms [A: values by ear]. The single choke point is `pipeline.py:597-600` (`push` -> `playout.push(audio)`), or `router.py:280-282`.
Pitfalls:
- AEC reference: `Playout._callback` calls `on_render(out)` on the samples *after* the ring buffer [V: playout.py:185]. Anything done in `push()` before the buffer is automatically in the reference. Never process inside the callback after `on_render`.
- The reverb tail and compressor/filter state must be flushed at `end_utterance` (push the tail) and reset on `abort()`, or the tail is chopped or leaks into the next reply.
- Keep gain staging: reverb and +dB shelves can clip; the tanh limiter covers it. Keep the reverb short and quiet (5-6% wet): a long tail smears consonants and makes the voice sound distant, and the AEC has to cancel the tail too (it is in the reference, so that works, but it lengthens the residual after barge-in).
- Apply to Pocket and Kokoro; for Cartesia use EQ only or skip, Cartesia has its own speed control.
- Add a deterministic unit test on the chain (state continuity: chunked output equals one-shot within tolerance).
"Subtle AI polish" beyond this (8-12 ms doubled copy at -18 dB, very slight chorus) is optional taste; try only after pace is fixed.

## 4. Cartesia sonic-3.6 [C unless noted]

- `generation_config`: `speed` 0.6-1.5 default 1.0, "guidance, not an exact multiplier"; docs say speed applies to Instant Voice Clones and are silent on stock voices; `volume` 0.5-2.0; `emotion` English only, primary (best data) = neutral, calm, angry, content, sad, scared. The ssml-tags page says a noticeable slow-down needs about 0.7, not 0.9. Snow sends only `emotion` today [V: cartesia.py:306]. Probe one short line at speed 0.85 and compare duration before relying on it. Inline `<speed ratio=.../>` exists but must be sent whole (not split across streamed tokens).
- Accent: `language` and `locale` accept `en` or `en-GB`, "Set one, never both". Snow sends `"language": "en"` [V: cartesia.py:305]. Try `locale: "en-GB"` for a British read from US voices [A: effect untested].
- Voices: docs name Archie (en-GB, male) and Daniel (en-US, male) among those recommended for sonic-3.6; stable voices for agents: Daniel, Archie, Parker, Jameson, Corey; emotive: Brandon, Cory, Alec. Third-party Famulor labels British male voices Archie "Approachable Mate", Benedict "Royal Narrator", Casper "Gentle Narrator", Caspian "Oracle" [C: famulor.io, labels not Cartesia's]. Voice IDs are not published on a page I could fetch; Snow's audition tool reads `/voices`. Audition order: Archie, Benedict, Casper, Caspian, Daniel (all already in the tts.toml shortlist).
- Cost on the free plan: 20K credits/month, 1 credit/character, a break tag = 1 credit; localization 225 credits per added accent; voice changer and voice design costs are not listed, and I could not confirm voice design exists. **Free plan excludes instant voice cloning and commercial use** (commercial licence is a Pro feature), which matters if others install Snow later.
- Audition cost: the 67-character audition line x 2 emotions x 8 candidates ~ 1,070 credits, about 5% of a month [V arithmetic from tts.toml].

## 5. Kokoro and Chatterbox

- Kokoro British male voices, hexgrad grades (target quality / overall): bm_fable B/C, bm_george B/C, bm_lewis C/D+, bm_daniel C/D; Apache-2.0 [C: huggingface.co/hexgrad/Kokoro-82M VOICES.md]. Measured, same line [V]: wps george 3.30, fable 3.58, lewis 3.25, daniel 3.96; speed 0.9 slows ~9% (george 3.30 -> 2.99). Keep bm_george or bm_fable, set `speed = 0.9`. Real-time factor measured 0.7x (slower than real time, whole-chunk synthesis, machine state unknown), fine for a last resort, not for primary.
- Chatterbox 0.1.7 (original model, `cfg_weight` honoured) [V: engines/chatterbox]. Official tips: defaults exaggeration 0.5 / cfg_weight 0.5; "Higher exaggeration tends to speed up speech; reducing cfg_weight helps compensate with slower, more deliberate pacing" [C: github.com/resemble-ai/chatterbox]. For calm: exaggeration 0.3, cfg_weight 0.3. Snow's `calm` is 0.35 but `cfg_weight` is a fixed 0.5; making it per-emotion is a tiny change. It only runs on mains power and idle GPU, so it is the lowest priority. Output is PerTh-watermarked [C].

## 6. Ranked plan (smallest change first)

1. **Persona/prompt rewrite (text only, no code, free).** Use the block in section 2. Expected: ~15-30% slower, more pauses on every engine, immediately. User decides: approve the tone wording.
2. **Make paul the base voice** (set `reference` and all moods to `paul` in tts.toml; keep george as the A/B alternative). Reason: slowest and flattest of the user's four likes by every measurement. User decides: paul vs george by ear after steps 1 and 3.
3. **Voice-polish stage in the push path** (about 60-80 lines + a test, `[polish]` section in tts.toml): resample factor 0.92 (about 8% slower, about -1.4 st), sentence/comma silence padding, EQ + 2:1 compression + 5-6% reverb, state reset on abort, tail flushed at end. Default values above; each independently switchable for A/B. Cost 0.5% CPU.
4. **Cartesia for big moments:** audition Archie/Benedict/Casper/Caspian, request `emotion: calm`, probe `speed: 0.85-0.9` and `locale: en-GB` on one short line each. User decides which voice to keep.
5. **Optional, user decision: unlock cloning for a true custom calm voice.** Needs: accept Kyutai terms on Hugging Face and log in, and unset `HF_HUB_DISABLE_IMPLICIT_TOKEN` for the one-time download. Conditioning source options (all consented/licensed): (a) the user's own slow, calm, quiet-room 20-30 s recording, `consent = "self"` (their timbre, but calm cadence transfers); (b) a commissioned voice actor with written AI-voice consent (the only route to an original British butler timbre); (c) a CC BY / CC0 speaker (VCTK, LibriVox) chosen for slow RP delivery, with the consent question above. Never a recording of the actor who voiced the film character. Then build real mood clips from the same speaker.
6. Chatterbox calm 0.3 / cfg 0.3; Kokoro speed 0.9. Low value, tiny edits.

Not recommended: exposing Pocket `temp`, the 24-layer model, `<break>` tags, pitch shifts beyond about -2 semitones.

## Caveats
Measurements are single short lines, no listening; "calm" is a perceptual target the user must confirm. The Hugging Face cache may have gained a few small Pocket voice files from the preset loads (no repo files were touched; scratchpad scripts ran with the repo venv, `-I`).
