"""Typed config/voice.toml (CORE-04). Extras are forbidden: a typo fails at start."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AudioConfig(_Strict):
    input_device: str = ""
    sample_rate: int = 16000
    frame_samples: int = 1280


class WakeConfig(_Strict):
    model: str
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


class LocalSttConfig(_Strict):
    model: Literal["tiny", "small", "medium"]  # Moonshine English streaming sizes
    partial_interval_ms: int


class SttConfig(_Strict):
    final_deadline_s: float  # Groq gets this long, then the local final is used
    cooldown_s: float  # how long a failed Groq is left alone
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
