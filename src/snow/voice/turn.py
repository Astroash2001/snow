"""Wake and turn state machine, driven only by audio time (samples processed).

Never reads the wall clock, so a recorded file, the pre-roll burst and live audio all
behave identically. Framework-free: VAD and end-of-turn come in through small protocols.
"""

import math
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

from snow.voice.config import ConversationConfig, TurnConfig
from snow.voice.wake import WakeHit

Pcm = npt.NDArray[np.int16]
Presence = Literal["sleeping", "listening", "thinking", "speaking", "muted"]

CHUNK = 512  # Silero's chunk at 16 kHz
_PRE_SPEECH_S = 0.5  # follow-on turns keep this much audio before speech is confirmed
_LEVEL_FLOOR_DB = -60.0
_BARGE_LEAD_S = (
    0.3  # audio kept from before the speech that barged in, so no onset is lost
)


def mic_level(chunk: Pcm) -> float:
    """RMS of a chunk mapped from -60..0 dBFS to 0..1 (the HUD's audio.level)."""
    rms = float(np.sqrt(np.mean(np.square(chunk.astype(np.float64))))) / 32768.0
    db = 20.0 * math.log10(max(rms, 1e-9))
    return min(1.0, max(0.0, (db - _LEVEL_FLOOR_DB) / -_LEVEL_FLOOR_DB))


class State(Enum):
    SLEEPING = "sleeping"  # wake only
    AWAKE = "awake"  # a conversation is open
    MUTED = "muted"  # the mic is closed; only unmute() leaves it


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

    def on_barge_in(self) -> None: ...


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

    def on_barge_in(self) -> None: ...


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
    follow_on: bool = False  # opened without a wake phrase (D-08)


class TurnEngine:
    def __init__(
        self,
        cfg: TurnConfig,
        vad: Vad,
        eot: Eot,
        events: EngineEvents | None = None,
        sample_rate: int = 16000,
        conversation: ConversationConfig | None = None,
    ) -> None:
        self._cfg = cfg
        self._conv = conversation or ConversationConfig(silence_timeout_s=45)
        self._vad = vad
        self._eot = eot
        self.events: EngineEvents = events or NullEvents()
        self._sr = sample_rate
        self.state = State.SLEEPING
        self._turn: _Turn | None = None
        self._rem: Pcm = np.zeros(0, dtype=np.int16)
        self._waiting = False  # a reply is pending: deaf, silence timer paused
        self._waited = 0
        self._idle = 0  # listening samples without speech (audio time)
        self._replaying = False
        # Barge-in (VOIC-06): Snow is audibly speaking; the user's voice may cut it off.
        self._speaking_out = False
        self._barge_run = 0  # consecutive speech samples heard over the reply
        ring = math.ceil((cfg.barge_in_min_ms / 1000 + _BARGE_LEAD_S) * sample_rate)
        self._ring: deque[Pcm] = deque(maxlen=math.ceil(ring / CHUNK))
        # Loop thread -> audio thread requests; deque appends are thread-safe.
        self._inbox: deque[tuple[str, str]] = deque()

    def reply_finished(self) -> None:
        """Thread-safe: the reply is done; listen again, restart the silence timer."""
        self._inbox.append(("reply", ""))

    def end_conversation(self, reason: str) -> None:
        """Thread-safe: end the open conversation (phrase or sleep command)."""
        self._inbox.append(("end", reason))

    def set_speaking(self, speaking: bool) -> None:
        """Thread-safe: Snow's voice is audible (True) or has stopped (False). While it
        is, the user speaking for `barge_in_min_ms` interrupts it (VOIC-06)."""
        self._inbox.append(("speaking", "1" if speaking else ""))

    def mute(self) -> None:
        """Thread-safe: drop any open turn or conversation silently (D-10, VOIC-03)."""
        self._inbox.append(("mute", ""))

    def unmute(self) -> None:
        """Thread-safe: back to sleeping, wake phrase only."""
        self._inbox.append(("unmute", ""))

    def drain(self) -> None:
        while self._inbox:
            kind, arg = self._inbox.popleft()
            if kind == "reply":
                self._reply_done()
            elif kind == "speaking":
                self._speaking_out = bool(arg)
                self._barge_run = 0
                self._ring.clear()
            elif kind == "mute":
                self._close_turn()
                self._waiting = False
                self._speaking_out = False
                self._rem = np.zeros(0, dtype=np.int16)
                self.state = State.MUTED
            elif kind == "unmute":
                if self.state is State.MUTED:
                    self.state = State.SLEEPING
            else:
                self._end(arg)

    def _reply_done(self) -> None:
        self._idle = 0
        self._speaking_out = False
        if self._waiting and self.state is State.AWAKE:
            self._waiting = False
            self.events.on_presence("listening")

    def _end(self, reason: str) -> None:
        if self.state is not State.AWAKE:
            return
        self._close_turn()
        self._waiting = False
        self._speaking_out = False
        self.state = State.SLEEPING
        self.events.on_conversation_end(reason)
        self.events.on_presence("sleeping")

    def _samples(self, seconds: float) -> int:
        return int(seconds * self._sr)

    def on_wake(self, hit: WakeHit) -> None:
        self.drain()
        # A wake inside a turn is the user's own words, not a new conversation.
        if self.state is State.MUTED or self._turn is not None or self._waiting:
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
        self._idle = 0
        self._replaying = True  # the burst is old audio: no mic levels for it
        for frame in hit.preroll:  # D-09: the words right after the wake phrase count
            self._ingest(frame)
        self._replaying = False

    def feed(self, frame: Pcm) -> None:
        self.drain()
        if self.state is State.AWAKE:
            self._ingest(frame)

    def _ingest(self, frame: Pcm) -> None:
        buf = np.concatenate([self._rem, frame])
        usable = len(buf) - len(buf) % CHUNK
        self._rem = buf[usable:]
        for i in range(0, usable, CHUNK):
            if self.state is not State.AWAKE:  # the conversation just ended
                return
            self._next(buf[i : i + CHUNK])

    def _next(self, chunk: Pcm) -> None:
        if self._waiting:
            if self._speaking_out:  # deaf to commands, but not to being talked over
                self._listen_over(chunk)  # the reply is being spoken: no timeout either
                return
            self._waited += CHUNK
            if self._waited >= self._samples(self._conv.reply_timeout_s):
                self._reply_done()  # no reply is coming (providers down, STT failed)
            return
        if self._turn is None:  # between turns: stay listening, no re-wake (D-08)
            self._turn = _Turn(id=uuid.uuid4().hex[:12], boundary=0, follow_on=True)
        if not self._replaying:
            self.events.on_level(mic_level(chunk))
        if not self._turn.speaking:
            self._idle += CHUNK
            if self._idle >= self._samples(self._conv.silence_timeout_s):
                self._end("silence")
                return
        self._chunk(chunk)

    def _listen_over(self, chunk: Pcm) -> None:
        """A reply is audible and no turn is open: enough speech cuts it off."""
        self._ring.append(chunk)
        if self._vad.speech_prob(chunk) < self._cfg.vad_threshold:
            self._barge_run = 0
            return
        self._barge_run += CHUNK
        if self._barge_run >= self._samples(self._cfg.barge_in_min_ms / 1000):
            self._barge_in()

    def _barge_in(self) -> None:
        """Stop waiting and open the next turn on the audio that barged in."""
        seed = list(self._ring)
        self._ring.clear()
        self._speaking_out = False
        self._barge_run = 0
        self._waiting = False
        self._idle = 0
        self._eot.clear()
        t = _Turn(id=uuid.uuid4().hex[:12], boundary=0, follow_on=True)
        t.chunks, t.samples, t.speaking = seed, len(seed) * CHUNK, True
        t.last_speech_end = t.samples
        self._turn = t
        for kept in seed:
            self._eot.append(kept)
        self.events.on_barge_in()  # before the turn starts: the old reply is cut first
        self.events.on_presence("listening")
        self.events.on_turn_start(t.id)

    def _chunk(self, chunk: Pcm) -> None:
        t = self._turn
        assert t is not None  # noqa: S101 - callers check; narrows the type
        cfg = self._cfg
        t.chunks.append(chunk)
        t.samples += CHUNK
        if t.speaking or not t.follow_on:  # follow-on silence is not worth analysing
            self._eot.append(chunk)
        if t.samples <= t.boundary:  # pre-roll: kept as audio, not counted as speech
            return
        if self._vad.speech_prob(chunk) >= cfg.vad_threshold:
            t.silence = 0
            t.speech_run += CHUNK
            t.last_speech_end = t.samples
            if self._speaking_out and t.speech_run >= self._samples(
                cfg.barge_in_min_ms / 1000
            ):  # a short voice (a wake acknowledgement) is cut off by the next words
                self._speaking_out = False
                self.events.on_barge_in()
            if not t.speaking and t.speech_run >= self._samples(cfg.start_secs):
                t.speaking = True
                self._idle = 0
                if t.follow_on:
                    for kept in t.chunks:
                        self._eot.append(kept)
                self.events.on_turn_start(t.id)
        else:
            t.speech_run = 0
            if t.speaking:
                t.silence += CHUNK

        if not t.speaking:
            if t.follow_on:  # keep a short lead-in only, not 45 s of silence
                while t.samples > self._samples(_PRE_SPEECH_S):
                    t.chunks.pop(0)
                    t.samples -= CHUNK
            elif t.samples - t.boundary >= self._samples(cfg.wake_alone_window_s):
                self._close_turn()  # D-09: the conversation stays open
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
        self._waiting = (
            True  # deaf until the reply is done (plan 01-26: end of playback)
        )
        self._waited = 0
        self.events.on_presence("thinking")
        self.events.on_turn_end(
            t.id, pcm, t.samples * 1000 // self._sr, t.last_speech_end
        )
