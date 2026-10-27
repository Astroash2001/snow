"""Typed config/voice.toml (CORE-04). Extras are forbidden: a typo fails at start."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AudioConfig(_Strict):
    input_device: str = ""
    sample_rate: int = 16000
    frame_samples: int = 1280


class WakeConfig(_Strict):
    model: str  # a pretrained openWakeWord name, or a repo-relative path to an .onnx
    model_sha256: str = ""  # required for a path; the file is refused if it differs
    threshold: float
    patience_frames: int
    preroll_frames: int
    refractory_s: float
    strip_patterns: list[str]


class BargeCheckConfig(_Strict):
    """What the check on a paused episode needs before it stops Snow for good."""

    min_words_verified: int  # words a verified voice needs (1: "Stop." works)
    min_words_unverified: int  # words with no voiceprint (the degraded mode)
    echo_match: float  # share of the heard words found in Snow's own last words
    echo_window_s: float  # how far back Snow's own words count as an echo
    timeout_s: float  # the words check is given this long, then it fails closed

    @model_validator(mode="after")
    def _words_are_sane(self) -> Self:
        if not 1 <= self.min_words_verified <= self.min_words_unverified:
            raise ValueError(
                "barge_check needs 1 <= min_words_verified <= min_words_unverified"
            )
        return self


class TurnConfig(_Strict):
    vad_threshold: float
    start_secs: float
    stop_secs: float
    max_silence_secs: float
    max_turn_secs: float
    wake_alone_window_s: float
    barge_in_min_ms: int  # only the wake acknowledgement's cut-off (see `_chunk`)
    barge_in_warmup_min_ms: int  # the pause trigger while the echo canceller adapts
    # a quiet stretch up to this long inside the user's words keeps a barge-in run
    barge_gap_ms: int
    pause_after_ms: int  # this much speech over Snow pauses it, holding the rest
    echo_tail_ms: int  # audio this soon after a pause is not checked (echo dies away)
    verify_speech_ms: int  # VAD speech in the check window that starts the check
    check_min_speech_ms: int  # an episode with this much speech is checked once
    quiet_resume_ms: int  # this long with no speech ends an episode
    # after a rejected check, Snow plays at least this long before speech can pause it
    reject_hold_s: float
    # an unconfirmed episode gives the voice back (pause resumed) this long after its
    # first speech
    duck_release_s: float

    @model_validator(mode="after")
    def _barge_in_is_sane(self) -> Self:
        timings = (
            self.pause_after_ms,
            self.echo_tail_ms,
            self.verify_speech_ms,
            self.check_min_speech_ms,
            self.quiet_resume_ms,
            self.reject_hold_s,
        )
        if any(v <= 0 for v in timings):
            raise ValueError("turn pause, check and hold timings must be above 0")
        if self.check_min_speech_ms > self.pause_after_ms:
            raise ValueError(
                "turn.check_min_speech_ms must not exceed turn.pause_after_ms"
            )
        needed = (
            max(
                self.pause_after_ms,
                self.barge_in_warmup_min_ms,
                self.reject_hold_s * 1000,
            )
            + self.echo_tail_ms
            + self.verify_speech_ms
        )
        if self.duck_release_s * 1000 < needed:
            raise ValueError(
                "turn.duck_release_s is shorter than a (held-back) pause, echo tail "
                "and check window: a barge-in could never be confirmed"
            )
        return self


class ConversationConfig(_Strict):
    silence_timeout_s: float
    reply_timeout_s: float = 20.0  # give up waiting for a reply after this much audio


class PhrasesConfig(_Strict):
    end: list[str]
    sleep: list[str]
    mute: list[str]


class GroqConfig(_Strict):
    base_url: str
    key_name: str
    model: str
    language: str
    timeout_s: float
    prompt: str  # spelling hints for Whisper, up to 224 tokens; empty omits it
    silent_no_speech_prob: (
        float  # a turn is silent when every segment is at or above this
    )
    silent_avg_logprob: float  # ... and at or below this


class LocalSttConfig(_Strict):
    model: Literal["tiny", "small", "medium"]  # Moonshine English streaming sizes
    partial_interval_ms: int


class SttConfig(_Strict):
    final_deadline_s: float  # Groq gets this long, then the local final is used
    cooldown_s: float  # how long a failed Groq is left alone
    min_voiced_s: float  # a turn with less voiced sound than this is dropped
    groq: GroqConfig
    local: LocalSttConfig


class ToneConfig(_Strict):
    """Tone detection (D-35). An empty model_url means prosody only, no emotion."""

    model_url: str = ""
    model_sha256: str = ""
    labels: list[str] = []
    temperature: float = 1.0  # softmax divisor for the model's raw scores
    min_confidence: float = 0.4
    loud_offset_db: float = 6.0
    quiet_offset_db: float = 8.0
    fast_wpm: float = 170.0
    slow_wpm: float = 110.0
    ref_loudness_dbfs: float = -24.0  # "normal" voiced level until history exists
    wait_s: float = 0.3  # the transcript waits at most this long for the tone


class SpeakerConfig(_Strict):
    """Speaker verification for the barge-in check (TitaNet-small, sherpa-onnx)."""

    model_url: str  # https only; fetched once into models/speaker/
    model_sha256: str  # the file is refused unless it matches
    threshold: float  # used until `snow dev enroll-voice` stores a calibrated one
    min_threshold: float  # a calibrated threshold is clamped into this range
    max_threshold: float
    min_margin: float  # enrollment refuses when genuine p5 minus impostor max is below
    calibration_lines: list[str]  # read aloud while enrolling (dev tool only)

    @model_validator(mode="after")
    def _is_sane(self) -> Self:
        if not self.model_url.startswith("https://"):
            raise ValueError("speaker.model_url must be https")
        if not self.min_threshold <= self.threshold <= self.max_threshold:
            raise ValueError(
                "speaker.threshold must lie within min_threshold and max_threshold"
            )
        if self.min_margin <= 0:
            raise ValueError("speaker.min_margin must be above 0")
        if not any(line.strip() for line in self.calibration_lines):
            raise ValueError("speaker.calibration_lines must not be empty")
        return self


class VoiceConfig(_Strict):
    audio: AudioConfig
    wake: WakeConfig
    turn: TurnConfig
    conversation: ConversationConfig
    phrases: PhrasesConfig
    stt: SttConfig
    tone: ToneConfig
    barge_check: BargeCheckConfig
    speaker: SpeakerConfig

    @model_validator(mode="after")
    def _release_covers_the_words_check(self) -> Self:
        t = self.turn
        needed = (
            max(t.pause_after_ms, t.barge_in_warmup_min_ms, t.reject_hold_s * 1000)
            + t.echo_tail_ms
            + t.verify_speech_ms
            + self.barge_check.timeout_s * 1000
        )
        if t.duck_release_s * 1000 < needed:
            raise ValueError(
                "turn.duck_release_s is shorter than a (held-back) pause, echo tail, "
                "check window and barge_check.timeout_s: a verdict could arrive stale"
            )
        return self
