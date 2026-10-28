"""Echo cancellation (VOIC-06): Snow's own voice is taken out of the mic signal.

WebRTC AEC3 through livekit's `AudioProcessingModule`, echo cancellation only (noise
suppression, AGC and the high-pass stay off: AGC shifts the VAD, wake and tone levels,
and AEC3 has its own high-pass). `capture()` cleans the mic and runs on the mic thread.
Audio lives in memory only (D-18) and no livekit room is created, so nothing touches
the network.

The reference (what the speaker plays) comes from one of two places:

- render: `render()` takes Snow's own blocks on PortAudio's output thread, before any
  output enhancer such as FxSound, so it stops matching the mic when one is on.
- loopback: `loopback_block()` takes a WASAPI loopback of the endpoint the sound finally
  reaches (`snow.voice.loopback`), after every enhancer. The blocks queue up (10 ms
  frames) and the mic thread feeds them to the APM just before each capture, zero frames
  when nothing played, so both sides share one clock. Every sound the PC plays is in
  that reference, so videos and music are cancelled from the mic too.

If livekit cannot load or the module errors, audio passes through unchanged and Snow
keeps listening and speaking.
"""

import collections
import logging
import time
from typing import Any

import numpy as np
import numpy.typing as npt

from snow.voice.sources import Frame

log = logging.getLogger("snow.voice")

# Measured cold-start residual still passes VAD 0.64-1.38 s after the first reference
# energy, so the canceller counts as warming until this much of Snow's voice has played.
WARMUP_S = 2.0
_REF_FLOOR = 10 ** (-50 / 20)  # reference blocks quieter than -50 dBFS are not voice
# 200 ms of loopback frames: a mic frame is 80 ms, so only a stalled mic (muted) hits it
_REF_QUEUE = 20


Pcm = npt.NDArray[np.int16]


def _to_int16(block: npt.NDArray[np.float32]) -> Pcm:
    return np.clip(block * 32768.0, -32768, 32767).astype(np.int16)


def _loud(block: npt.NDArray[np.float32]) -> bool:
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))) > _REF_FLOOR


class EchoCanceller:
    def __init__(self, capture_rate: int = 16000, render_rate: int = 24000) -> None:
        if capture_rate % 100 or render_rate % 100:
            raise ValueError("APM frames are 10 ms: rates must be multiples of 100")
        # lazy: ~0.5 s and 21 native threads, paid only if enabled
        from livekit import rtc

        self._rtc = rtc
        self._apm: rtc.AudioProcessingModule | None = rtc.AudioProcessingModule(
            echo_cancellation=True
        )
        self._capture_rate, self._render_rate = capture_rate, render_rate
        self._cn, self._rn = capture_rate // 100, render_rate // 100
        self._tail: npt.NDArray[np.int16] = np.zeros(0, dtype=np.int16)
        self.reference_s = 0.0
        self.loopback = (
            False  # True: the reference is the loopback, render() is ignored
        )
        self._queue: collections.deque[npt.NDArray[np.int16]] = collections.deque(
            maxlen=_REF_QUEUE
        )
        self._loop_tail: npt.NDArray[np.int16] = np.zeros(0, dtype=np.int16)
        self._loop_at = 0.0  # monotonic time of the last loopback block
        self._render_loud_at = 0.0  # ... and of the last audible render block
        # No set_stream_delay_ms: the hint changed nothing for true delays up to 500 ms,
        # and PortAudio's latencies understate the real path on this laptop.

    def warming(self) -> bool:
        return self.reference_s < WARMUP_S

    @property
    def render_rate(self) -> int:
        return self._render_rate

    def use_loopback(self, on: bool) -> None:
        """Switch the reference; the new one starts cold, so the canceller re-warms."""
        self.loopback = on
        self._queue.clear()
        self._loop_tail = np.zeros(0, dtype=np.int16)
        self._loop_at = time.monotonic()
        self.reference_s = 0.0

    def loopback_stale(self, after_s: float) -> bool:
        """Snow has been audible for `after_s` with no loopback packet: it is dead."""
        return self._render_loud_at - self._loop_at > after_s

    def loopback_block(self, block: npt.NDArray[np.float32]) -> None:
        """Loopback thread: mono float32 at the render rate. Raises on a bad block, the
        caller drops the loopback, not the canceller."""
        if not self.loopback or self._apm is None:
            return
        pcm = np.concatenate([self._loop_tail, _to_int16(block)])
        usable = len(pcm) - len(pcm) % self._rn
        for i in range(0, usable, self._rn):
            self._queue.append(pcm[i : i + self._rn])
        self._loop_tail = pcm[usable:]
        self._loop_at = time.monotonic()
        if _loud(block):
            self.reference_s += len(block) / self._render_rate

    def _reverse(self, apm: Any, frame: Pcm) -> None:
        apm.process_reverse_stream(
            self._rtc.AudioFrame(
                bytearray(frame.tobytes()), self._render_rate, 1, self._rn
            )
        )

    def render(self, block: npt.NDArray[np.float32]) -> None:
        """The reference: every block played, silent ones too. Never raises."""
        apm = self._apm
        if apm is None:
            return
        try:
            loud = _loud(block)
            if loud:
                self._render_loud_at = time.monotonic()
            if self.loopback:
                return
            pcm = np.concatenate([self._tail, _to_int16(block)])
            usable = len(pcm) - len(pcm) % self._rn
            for i in range(0, usable, self._rn):
                self._reverse(apm, pcm[i : i + self._rn])
            self._tail = pcm[usable:]
            if loud:
                self.reference_s += len(block) / self._render_rate
        except Exception as e:  # noqa: BLE001 - must never escape a PortAudio callback
            self._fail(e)

    def capture(self, frame: Frame) -> Frame:
        """The mic frame without Snow's voice (unchanged if the canceller is off)."""
        # A non-10 ms frame makes livekit's Rust side panic and kill the interpreter.
        if len(frame) % self._cn:
            raise ValueError("mic frame must be a whole number of 10 ms")
        apm = self._apm
        if apm is None:
            return frame
        try:
            if self.loopback:  # the loopback clock: feed what arrived, else silence
                n = len(self._queue)
                for _ in range(n):
                    self._reverse(apm, self._queue.popleft())
                if n == 0:
                    silence = np.zeros(self._rn, dtype=np.int16)
                    for _ in range(len(frame) // self._cn):
                        self._reverse(apm, silence)
            out = np.empty_like(frame)
            for i in range(0, len(frame), self._cn):
                # bytearray, not memoryview: processing is in place and a view is copied
                f = self._rtc.AudioFrame(
                    bytearray(frame[i : i + self._cn].tobytes()),
                    self._capture_rate,
                    1,
                    self._cn,
                )
                apm.process_stream(f)
                out[i : i + self._cn] = np.frombuffer(f.data, dtype=np.int16)
            return out
        except Exception as e:  # noqa: BLE001
            self._fail(e)
            return frame

    def _fail(self, e: Exception) -> None:
        if self._apm is not None:
            log.error("aec_failed kind=%s", type(e).__name__)
        self._apm = None  # both sides pass audio through from now on

    def close(self) -> None:
        self._apm = None  # dropping it avoids livekit's FfiHandle.__del__ error at exit
