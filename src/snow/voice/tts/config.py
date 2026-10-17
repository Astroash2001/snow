"""Typed config/tts.toml (CORE-04). Extras are forbidden: a typo fails at start."""

from pydantic import BaseModel, ConfigDict

from snow.voice.tts.base import EngineName


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouterConfig(_Strict):
    order: list[EngineName]  # D-33; consumed by the router of plan 01-28


class PlayoutConfig(_Strict):
    prebuffer_ms: int


class PocketConfig(_Strict):
    enabled: bool
    voice: str  # a built-in preset until the user's own voice arrives (plan 01-32)
    torch_threads: int


class SwitchConfig(_Strict):
    enabled: bool  # later plans add their own settings next to this


class EnginesConfig(_Strict):
    pocket_tts: PocketConfig
    kokoro: SwitchConfig
    cartesia: SwitchConfig
    chatterbox: SwitchConfig


class TtsConfig(_Strict):
    router: RouterConfig
    playout: PlayoutConfig
    engines: EnginesConfig
