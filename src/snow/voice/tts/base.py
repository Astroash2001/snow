"""The contract every speech engine meets (D-33). The router in plan 01-28 picks one."""

from collections.abc import AsyncIterator
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

EngineName = Literal["pocket_tts", "cartesia", "chatterbox", "kokoro"]
ErrorKind = Literal[
    "load_failed", "unreachable", "out_of_credits", "no_key", "budget_reached"
]
Samples = npt.NDArray[np.float32]  # mono, -1..1


class EngineError(Exception):
    """An engine cannot speak right now; the router decides what to do next."""

    def __init__(self, kind: ErrorKind) -> None:
        super().__init__(kind)
        self.kind: ErrorKind = kind


class EngineLoadError(EngineError):
    def __init__(self) -> None:
        super().__init__("load_failed")


class TtsEngine(Protocol):
    name: EngineName
    sample_rate: int
    voice_name: str

    def load(self) -> None:
        """Blocking (seconds). Raises `EngineLoadError`."""
        ...

    def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]: ...

    def cancel(self) -> None:
        """Thread-safe: stop generating at the next chunk."""
        ...
