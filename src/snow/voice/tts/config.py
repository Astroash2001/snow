"""Typed config/tts.toml (CORE-04). Extras are forbidden: a typo fails at start."""

from pydantic import BaseModel, ConfigDict

from snow.voice.tts.base import EngineName


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouterConfig(_Strict):
    order: list[EngineName]  # D-33: the first usable engine for a reply speaks it
    cooldown_s: float  # a voice that errored mid-reply is left alone this long


class PlayoutConfig(_Strict):
    prebuffer_ms: int
    assume_headphones: bool  # no echo cancellation in v1: barge-in needs headphones


class PocketConfig(_Strict):
    enabled: bool
    voice: str  # a built-in preset until the user's own voice arrives (plan 01-32)
    torch_threads: int


class KokoroConfig(_Strict):
    enabled: bool
    voice: str  # a voice in voices-v1.0.bin; bm_george is British male
    speed: float
    threads: int  # onnxruntime intra-op threads (measured best at 4)
    model_url: str  # official kokoro-onnx release, fetched on first use
    voices_url: str
    model_sha256: str  # pinned: a file that differs is never loaded (T-01-58)
    voices_sha256: str


class SwitchConfig(_Strict):
    enabled: bool  # later plans add their own settings next to this


class CartesiaConfig(_Strict):
    enabled: bool
    ws_url: str
    api_base: str  # REST base for the credit-free probe and the optional credits call
    api_version: str  # sent as the Cartesia-Version header
    model: str  # a dated snapshot never changes under us
    voice_id: str  # empty until plan 01-32's audition; then Cartesia is skipped (D-41)
    voice_name: str
    key_name: str
    daily_char_budget: int  # 1 credit is about 1 character; 20,000 a month / 30
    probe_interval_s: float  # while unavailable, how often the free probe runs
    credits_url: (
        str  # empty: Cartesia has no remaining-balance endpoint for a normal key
    )
    sample_rate: int


class EnginesConfig(_Strict):
    pocket_tts: PocketConfig
    kokoro: KokoroConfig
    cartesia: CartesiaConfig
    chatterbox: SwitchConfig


class TtsConfig(_Strict):
    router: RouterConfig
    playout: PlayoutConfig
    engines: EnginesConfig
