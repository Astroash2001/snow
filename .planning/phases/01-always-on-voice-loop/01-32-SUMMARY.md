---
phase: 01-always-on-voice-loop
plan: 32
subsystem: voice
tags: [tts, pocket-tts, moods, consent, audition, cartesia, spch-02]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "PocketEngine and TtsConfig (01-26), router (01-28), CartesiaEngine with empty voice_id (01-31), allowed emotions from the brain (01-16)"
provides:
  - "PocketConfig.reference / moods / emotion_to_mood with mandatory consent tags; PocketConfig.mood_for(emotion)"
  - "PocketEngine: one cached voice state per distinct clip, stream() picks the mood clip, unloadable mood falls back to the base voice, preview() for the audition"
  - "snow dev audition-voices [--cartesia] [--pocket] [--config PATH]"
  - "config/tts.toml: audition_line, [audition], reference, [engines.pocket_tts.moods], [engines.pocket_tts.emotion_to_mood]"
affects: [01-33 Chatterbox (can reuse VoiceClip consent), HUD Voice card (voice_name is now the reference path)]

commits: 1
plan_head_before: 83d34483b157dd56e9f729ec2dfbe0e88e2d071c
plan_head_after: ee79af353b9539a19f011e0a660e0cdaf6562be8

actuals:
  tokens: 26000
  tasks: 1
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Targeted line replacement (set_line) instead of a TOML writer: only the named key inside the named section changes, line endings and every other line stay byte for byte"
    - "Dev tool takes a Tools dataclass (ask, say, play, secret, transport, synth fakes) so tests run with a scripted user and no audio"

key-files:
  created:
    - src/snow/voice/audition.py
    - tests/voice/test_mood.py
  modified:
    - src/snow/voice/tts/pocket.py
    - src/snow/voice/tts/config.py
    - config/tts.toml

key-decisions:
  - "Mood clips default to the base preset (marius) for all five moods: the same-speaker style clips Kyutai publishes (expresso, ears) are CC BY-NC (non-commercial) and an audio clip needs the gated voice-cloning weights; I did not accept either on the user's behalf. The mechanism works and is tested; the moods do not sound different yet (see Pending)"
  - "`voice` in PocketConfig is replaced by `reference = { path, consent }`; the HUD voice_name stays 'marius' (path of the reference)"
  - "audition_line is a top-level tts.toml key and the rest of the audition settings sit in [audition]; test_no_scripts only scans ReplyDelta/ReplyFinal calls, so the line, which never reaches either, passes untouched"
  - "A consent tag is a Literal in the config model: a missing or unknown value fails pydantic validation with the entry path (e.g. engines.pocket_tts.moods.playful.consent)"

requirements-completed: [SPCH-02]

coverage:
  - id: D1
    description: "emotion_to_mood maps neutral/content/calm/curious/sympathetic/excited and an unknown emotion to calm"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_mood.py#test_emotions_map_to_moods_and_an_unknown_one_is_calm", status: pass}
    human_judgment: false
  - id: D2
    description: "stream(text, 'sympathetic') uses the state of the sympathetic clip; a mood without a clip, or with an unloadable one, uses the base voice; one state per distinct clip"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_mood.py (4 engine tests)", status: pass}
    human_judgment: false
  - id: D3
    description: "A reference or mood clip without consent, or with a value outside the three, fails config load naming the entry; the shipped config tags every clip"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_mood.py#test_a_clip_without_a_valid_consent_tag_is_refused", status: pass}
    human_judgment: false
  - id: D4
    description: "Audition with input 2 writes that Cartesia voice's id and name into tts.toml and changes no other line; asks before spending, shows the cost, caps at 8 candidates"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_mood.py#test_choosing_two_writes_that_voice_into_tts_toml_and_nothing_else", status: pass}
      - {kind: test, ref: "tests/voice/test_mood.py#test_cartesia_asks_before_spending_and_caps_at_eight", status: pass}
    human_judgment: false
  - id: D5
    description: "Pocket audition writes reference and moods with a consent tag; a user clip without a valid tag, or one that cannot be spoken, is refused and nothing is written"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_mood.py (pocket audition tests)", status: pass}
    human_judgment: false
  - id: D6
    description: "Listen: pick the Cartesia voice (calm, dry, British-leaning male) and the Pocket voice; judge whether the five moods sound different enough (D-34)"
    status: pending
    human_judgment: true
    rationale: "Choosing by ear is the user's. Not run by this agent; no voice id was written."
---

# Phase 1 Plan 32: Voice moods, consent and the audition Summary

**The everyday voice now takes the LLM's emotion through a mood-clip mechanism (default: every mood is the base preset, so no audible difference yet), every reference clip needs a consent tag or Snow refuses it, and `snow dev audition-voices` lets the user hear Cartesia and Pocket candidates and writes the pick into `config/tts.toml`.**

## What was built

- `tts/config.py`: `VoiceClip{path, consent}` with `Consent = self | consenting_person | licensed_preset`; `PocketConfig` now has `reference`, `moods` (calm, upbeat, serious, playful, sympathetic; any may be absent), `emotion_to_mood`, and `mood_for()` (unknown emotion gives calm). New `AuditionConfig` and `TtsConfig.audition_line` / `audition`.
- `tts/pocket.py`: states are built once per distinct clip path at load; the base voice must load (else `EngineLoadError` as before), a mood whose clip fails is logged (`tts_mood_unavailable`) and speaks in the base voice. `stream(text, emotion)` selects by mood. `preview(text, path)` is used only by the audition.
- `audition.py`: Cartesia part reads stock voices through the credit-free `GET /voices` (key in headers, via `get_secret`, paginated up to 500), keeps English male voices, ranks the research shortlist first then British-sounding ones, caps at `max_candidates` (8), shows `len(line) * 2 emotions * n` as the credit estimate and only speaks after `y`. Pocket part plays each preset in `[audition].pocket_voices`, accepts a number or the path of the user's own clip (asks whose voice it is; anything but the three tags is refused, nothing written), asks for optional mood clips (Enter = base voice), plays any non-base mood clip, and writes `reference` and the five mood lines. `set_line` rewrites only the named key inside the named section and the result is validated against `TtsConfig` before it is written, so a bad pick can never leave Snow unable to start. Playback uses `sounddevice` from memory; nothing is recorded or written.
- `config/tts.toml`: `reference`, `[engines.pocket_tts.moods]`, `[engines.pocket_tts.emotion_to_mood]`, `audition_line`, `[audition]`. `voice_id` / `voice_name` for Cartesia stay empty.

## Licences of the Pocket presets (Kyutai tts-voices README, read this session)

| Preset(s) | Source | Licence |
|-----------|--------|---------|
| marius, javert | voice-donations | CC0 |
| george, charles, paul, michael | VCTK | CC BY 4.0 (credit the dataset before distribution) |
| peter_yearsley, stuart_bell, bill_boerst | LibriVox via Voice-Zero | CC0 |
| cosette, jean | expresso, ears | CC BY-NC, non-commercial: deliberately left out of the audition list |
| alba | alba-mackenna | CC BY 4.0 (not in the audition list) |

Model weights `kyutai/pocket-tts-without-voice-cloning`: CC-BY-4.0, ungated (unchanged from 01-26).

## Voice-cloning gate and mood clips (STOPPED short of this, reported)

Checked the installed `pocket_tts` 3.3.0: with the ungated weights only predefined catalog names and precomputed `.safetensors` states can be used. Any audio file (a mood clip, or the user's own voice) raises `VOICE_CLONING_UNSUPPORTED` unless the user accepts the terms at huggingface.co/kyutai/pocket-tts and logs in with a Hugging Face token. I did not accept that, so no audio mood clips were set up. Kyutai's only multi-style clips of one speaker are in expresso (speakers ex01..ex04) and ears (p031 male, emotion files), both non-commercial. Result: all five moods use `marius`, so D-34 is wired and tested but inaudible until the user decides. Options for the user: (a) accept the Pocket TTS terms and supply their own clips (consent `self`), (b) use the NC clips for personal use only, knowing the licence, (c) keep one voice and let Cartesia carry emotion.

## Credit-free real calls

Two sessions of `GET https://api.cartesia.ai/voices` (limit 100, plus `starting_after` pages, 6 requests in total) with the stored key through `get_secret`; 200 each time; 500 unique voices read; key never printed. No synthesis, no WebSocket. The real shortlist after filtering: Archie (British), Brandon, Caspian, Daniel, Parker, Corey, Jameson, Cory (cap of 8 leaves Alec, Benedict, Casper, which were not in the first 500 or ranked below the cap).

## Deviations from Plan

1. **[Rule 3] respx replaced by `httpx2.MockTransport`** in the tests, as in 01-31 (respx does not intercept httpx2).
2. **Mood clips are the base preset** instead of same-speaker style clips (gate and licence above); the plan allows this fallback.
3. `src/snow/cli.py` already contained the `dev audition-voices` entry from plan 01-06, so it was not edited. No files outside `files_modified` were touched.
4. `PocketConfig.voice` was replaced by `reference` (plan key); no other code read `voice`.

## Known limits (shortcuts)

- `set_line` drops the old line's trailing comment (the replaced values are simple strings and inline tables).
- Each synthesis in the audition runs in its own `asyncio.run`, so Cartesia opens a socket per candidate and emotion; fine for 16 short lines.
- The Pocket audition reloads nothing but builds one state per heard preset (the first run downloads each small embedding from Kyutai's repo).

## Known stubs

None. (The identical mood clips are configuration, documented above, not a code stub.)

## Pending for the user (not done by this agent)

1. Run `uv run snow dev audition-voices` (or `--cartesia` / `--pocket`). It will ask before spending Cartesia credits (about 1,060 for 8 voices in two emotions). Pick the Cartesia voice closest to a calm, dry, British-leaning male (Archie is listed first and is described as British; Clive and Daniel are other candidates) and the Pocket voice.
2. Decide the mood-clip question above, then listen to the same line in each mood and write the verdict (D-34 is unverified until heard): calm / upbeat / serious / playful / sympathetic sound different enough?
3. If a CC BY preset (george, charles, paul, michael) is chosen, add the VCTK credit to the project credits before distribution.
4. Optional: `uv run pytest -m network tests/voice/test_cartesia.py` after a voice id is set.

## Threat flags

None new. T-01-50 mitigated: consent is a required typed field at config load and is asked for in the audition; untagged and invalid tags are refused (tested). T-01-SC: no new packages, pyproject.toml and uv.lock unchanged.

## Verification

- `uv run pytest tests/voice/test_mood.py -x -q`: 21 passed.
- `uv run pytest -x -q -m "not hardware and not network and not slow"`: 397 passed (includes test_no_egress, the no-disk proof, test_no_scripts).
- `uv run pytest -m slow tests/voice/test_tts_pipeline.py`: real Pocket TTS still speaks with the new `reference` config.
- `ruff check`, `ruff format --check`, `pyright` (0 errors), `snow.contracts.export --check`: clean.
- `uv run snow dev audition-voices --help` exits 0.

## Self-Check: PASSED

Files exist: src/snow/voice/audition.py, tests/voice/test_mood.py. Commit ee79af3 exists.
