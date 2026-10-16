"""Wake and turn state machine, driven only by audio time (samples processed).

Never reads the wall clock, so a recorded file, the pre-roll burst and live audio all
behave identically. Framework-free: VAD and end-of-turn come in through small protocols.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

from snow.voice.config import TurnConfig
from snow.voice.wake import WakeHit

Pcm = npt.NDArray[np.int16]
Presence = Literal["sleeping", "listening", "thinking", "speaking", "muted"]

CHUNK = 512  # Silero's chunk at 16 kHz


class State(Enum):
    SLEEPING = "sleeping"  # wake only
    AWAKE = "awake"  # a conversation is open
    MUTED = "muted"  # used by plan 01-20


class Vad(Protocol):
    def speech_prob(self, chunk: Pcm) -> float: ...

    def reset(self) -> None: ...


class Eot(Protocol):
    def append(self, pcm: Pcm) -> None: ...

    def is_complete(self) -> bool: ...

    def clear(self) -> None: ...


class EngineEvents(Protocol):
    """Callbacks from the audio thread. Plans 01-18 and 01-20 fill the flow ones."""

    def on_wake(self, hit: WakeHit) -> None: ...

    def on_conversation_start(self) -> None: ...

    def on_turn_start(self, turn_id: str) -> None: ...

    def on_turn_end(
        self, turn_id: str, pcm: bytes, duration_ms: int, vad_stop_sample: int
    ) -> None: ...

    def on_wake_alone(self) -> None: ...

    def on_conversation_end(self, reason: str) -> None: ...

    def on_presence(self, state: Presence) -> None: ...

    def on_level(self, level: float) -> None: ...


class NullEvents:
    def on_wake(self, hit: WakeHit) -> None: ...

    def on_conversation_start(self) -> None: ...

    def on_turn_start(self, turn_id: str) -> None: ...

    def on_turn_end(
        self, turn_id: str, pcm: bytes, duration_ms: int, vad_stop_sample: int
    ) -> None: ...

    def on_wake_alone(self) -> None: ...

    def on_conversation_end(self, reason: str) -> None: ...

    def on_presence(self, state: Presence) -> None: ...

    def on_level(self, level: float) -> None: ...


@dataclass
class _Turn:
    id: str
    boundary: int  # samples of pre-roll; audio after this point is post-wake
    chunks: list[Pcm] = field(default_factory=list[Pcm])
    samples: int = 0
    speech_run: int = 0
    speaking: bool = False
    silence: int = 0
    asked: bool = False  # Smart Turn already answered for this stretch of silence
    last_speech_end: int = 0


class TurnEngine:
    def __init__(
        self,
        cfg: TurnConfig,
        vad: Vad,
        eot: Eot,
        events: EngineEvents | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self._cfg = cfg
        self._vad = vad
        self._eot = eot
        self.events: EngineEvents = events or NullEvents()
        self._sr = sample_rate
        self.state = State.SLEEPING
        self._turn: _Turn | None = None
        self._rem: Pcm = np.zeros(0, dtype=np.int16)

    def _samples(self, seconds: float) -> int:
        return int(seconds * self._sr)

    def on_wake(self, hit: WakeHit) -> None:
        # A wake inside a turn is the user's own words, not a new conversation.
        if self.state is State.MUTED or self._turn is not None:
            return
        self.events.on_wake(hit)
        if self.state is State.SLEEPING:
            self.state = State.AWAKE
            self.events.on_conversation_start()
            self.events.on_presence("listening")
        boundary = sum(len(f) for f in hit.preroll)
        self._turn = _Turn(id=uuid.uuid4().hex[:12], boundary=boundary)
        self._vad.reset()
        self._eot.clear()
        self._rem = np.zeros(0, dtype=np.int16)
        for frame in hit.preroll:  # D-09: the words right after the wake phrase count
            self._ingest(frame)

    def feed(self, frame: Pcm) -> None:
        if self.state is State.AWAKE and self._turn is not None:
            self._ingest(frame)

    def _ingest(self, frame: Pcm) -> None:
        buf = np.concatenate([self._rem, frame])
        usable = len(buf) - len(buf) % CHUNK
        self._rem = buf[usable:]
        for i in range(0, usable, CHUNK):
            if self._turn is None:  # the previous chunk ended the turn
                return
            self._chunk(buf[i : i + CHUNK])

    def _chunk(self, chunk: Pcm) -> None:
        t = self._turn
        assert t is not None  # noqa: S101 - callers check; narrows the type
        cfg = self._cfg
        t.chunks.append(chunk)
        t.samples += CHUNK
        self._eot.append(chunk)
        if t.samples <= t.boundary:  # pre-roll: kept as audio, not counted as speech
            return
        if self._vad.speech_prob(chunk) >= cfg.vad_threshold:
            t.silence = 0
            t.speech_run += CHUNK
            t.last_speech_end = t.samples
            if not t.speaking and t.speech_run >= self._samples(cfg.start_secs):
                t.speaking = True
                self.events.on_turn_start(t.id)
        else:
            t.speech_run = 0
            if t.speaking:
                t.silence += CHUNK

        if not t.speaking:
            if t.samples - t.boundary >= self._samples(cfg.wake_alone_window_s):
                self._close_turn()
                self.events.on_wake_alone()
            return
        if t.silence == 0:
            t.asked = False
        elif t.silence >= self._samples(cfg.max_silence_secs):
            self._end_turn(t)
        elif t.silence >= self._samples(cfg.stop_secs) and not t.asked:
            # Asked once per silence, like Pipecat: Smart Turn is trained on clips that
            # end at the last word, so long silence appended to them is out of range.
            t.asked = True
            if self._eot.is_complete():
                self._end_turn(t)
            else:
                # Measured: after a mid-thought pause the model rates the next segment
                # far better alone than with the earlier words (0.93 vs 0.23 complete).
                self._eot.clear()
        if self._turn is t and t.samples >= self._samples(cfg.max_turn_secs):
            self._end_turn(t)

    def _close_turn(self) -> None:
        self._turn = None
        self._vad.reset()
        self._eot.clear()

    def _end_turn(self, t: _Turn) -> None:
        pcm = np.concatenate(t.chunks).tobytes()
        self._close_turn()
        self.events.on_turn_end(
            t.id, pcm, t.samples * 1000 // self._sr, t.last_speech_end
        )
