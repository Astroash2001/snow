"""Typed adapters around Pipecat's Silero VAD and Smart Turn v3.2 analyzers.

This is the only module that imports Pipecat, so the framework stays removable.
Pipecat's frame pipeline is not used (the brain is a separate process, D-40); only
its CPU models are.
"""

import numpy as np
import numpy.typing as npt
from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
    LocalSmartTurnAnalyzerV3,  # pyright: ignore[reportMissingTypeStubs]
)
from pipecat.audio.vad.silero import SileroVADAnalyzer  # pyright: ignore[reportMissingTypeStubs]

Pcm = npt.NDArray[np.int16]

logger.remove()  # Pipecat logs DEBUG to stderr by default; we log our own events

VAD_CHUNK = 512  # samples Silero consumes at 16 kHz
_SMART_TURN_WINDOW_S = 8  # the model looks at the last 8 s


class VadDetector:
    def __init__(self, sample_rate: int = 16000) -> None:
        self._a = SileroVADAnalyzer(sample_rate=sample_rate)
        self._a.set_sample_rate(sample_rate)

    def speech_prob(self, chunk: Pcm) -> float:
        """Probability that a 512-sample chunk is speech."""
        return float(np.ravel(self._a.voice_confidence(chunk.tobytes()))[0])

    def reset(self) -> None:
        self._a._model.reset_states()  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType]


class EndOfTurn:
    """Smart Turn v3.2: does the audio so far sound like a finished thought?

    Pipecat's own buffering is bypassed because it timestamps with the wall clock, which
    would make recorded files behave differently from live audio; we hold the audio and
    ask the model directly.
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self._a = LocalSmartTurnAnalyzerV3(sample_rate=sample_rate)
        self._max = _SMART_TURN_WINDOW_S * sample_rate
        self._buf: list[Pcm] = []
        self._len = 0

    def append(self, pcm: Pcm) -> None:
        self._buf.append(pcm)
        self._len += len(pcm)
        while self._len - len(self._buf[0]) >= self._max:  # drop what the model ignores
            self._len -= len(self._buf.pop(0))

    def is_complete(self) -> bool:
        if not self._buf:
            return False
        audio = np.concatenate(self._buf)[-self._max :].astype(np.float32) / 32768.0
        result = self._a._predict_endpoint(audio)  # pyright: ignore[reportPrivateUsage, reportUnknownMemberType, reportUnknownVariableType]
        return bool(result["prediction"] == 1)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]

    def clear(self) -> None:
        self._buf = []
        self._len = 0
