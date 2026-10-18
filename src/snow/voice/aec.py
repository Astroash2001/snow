"""Echo cancellation (VOIC-06): Snow's own voice is taken out of the mic signal.

WebRTC AEC3 through livekit's `AudioProcessingModule`, echo cancellation only (noise
suppression, AGC and the high-pass stay off: AGC shifts the VAD, wake and tone levels,
and AEC3 has its own high-pass). `render()` takes what the speaker plays and runs on
PortAudio's output thread; `capture()` cleans the mic and runs on the mic thread, the
render/capture threading WebRTC is built for. Audio lives in memory only (D-18) and no
livekit room is created, so nothing touches the network.

If livekit cannot load or the module errors, audio passes through unchanged and Snow
keeps listening and speaking.
"""

import logging

import numpy as np
import numpy.typing as npt

from snow.voice.sources import Frame

log = logging.getLogger("snow.voice")

# Measured cold-start residual still passes VAD 0.64-1.38 s after the first reference
# energy, so the canceller counts as warming until this much of Snow's voice has played.
WARMUP_S = 2.0
_REF_FLOOR = 10 ** (-50 / 20)  # reference blocks quieter than -50 dBFS are not voice


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
        # No set_stream_delay_ms: the hint changed nothing for true delays up to 500 ms,
        # and PortAudio's latencies understate the real path on this laptop.

    def warming(self) -> bool:
        return self.reference_s < WARMUP_S

    def render(self, block: npt.NDArray[np.float32]) -> None:
        """The reference: every block played, silent ones too. Never raises."""
        apm = self._apm
        if apm is None:
            return
        try:
            pcm = np.concatenate(
                [self._tail, np.clip(block * 32768.0, -32768, 32767).astype(np.int16)]
            )
            usable = len(pcm) - len(pcm) % self._rn
            for i in range(0, usable, self._rn):
                apm.process_reverse_stream(
                    self._rtc.AudioFrame(
                        bytearray(pcm[i : i + self._rn].tobytes()),
                        self._render_rate,
                        1,
                        self._rn,
                    )
                )
            self._tail = pcm[usable:]
            if float(np.sqrt(np.mean(np.square(block, dtype=np.float64)))) > _REF_FLOOR:
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
