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


class TurnConfig(_Strict):
    vad_threshold: float
    start_secs: float
    stop_secs: float
    max_silence_secs: float
    max_turn_secs: float
    wake_alone_window_s: float
    barge_in_min_ms: int
    barge_in_warmup_min_ms: int  # while the echo canceller is still adapting
    # a quiet stretch up to this long inside the user's words keeps a barge-in run
    barge_gap_ms: int
    duck_after_ms: int  # this much speech over Snow lowers its voice
    duck_gain: float  # Snow's playout gain while ducked
    # an unconfirmed barge-in releases the duck this long after its first speech
    duck_release_s: float

    @model_validator(mode="after")
    def _duck_is_sane(self) -> Self:
        if not 0 < self.duck_gain <= 1:
            raise ValueError("turn.duck_gain must be above 0 and at most 1")
        longest = max(self.barge_in_min_ms, self.barge_in_warmup_min_ms)
        if self.duck_release_s * 1000 < longest:
            raise ValueError(
                "turn.duck_release_s is shorter than a barge-in minimum: "
                "a barge-in could never be confirmed"
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


class VoiceConfig(_Strict):
    audio: AudioConfig
    wake: WakeConfig
    turn: TurnConfig
    conversation: ConversationConfig
    phrases: PhrasesConfig
    stt: SttConfig
    tone: ToneConfig
