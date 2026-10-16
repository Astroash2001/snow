"""Typed config/voice.toml (CORE-04). Extras are forbidden: a typo fails at start."""

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


class SttConfig(_Strict):
    groq: GroqConfig


class VoiceConfig(_Strict):
    audio: AudioConfig
    wake: WakeConfig
    turn: TurnConfig
    conversation: ConversationConfig
    phrases: PhrasesConfig
    stt: SttConfig
