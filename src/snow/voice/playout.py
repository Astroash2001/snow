"""Speaker output: a ring buffer behind one WASAPI stream, with levels and drain events.

Audio only ever lives in memory (D-18). The device callback runs on PortAudio's thread,
so the callbacks (`on_render`, `on_first_audio`, `on_level`, `on_drained`) run there
and must only hop onto the event loop. `on_render` gets every block played, silent ones
too: it is the echo canceller's reference (VOIC-06) and must be fast and never raise.
"""

import collections
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]

from snow.voice.tts.config import PlayoutConfig

log = logging.getLogger("snow.voice")

_BLOCK_S = 0.02
_LEVEL_EVERY_S = 0.031
_FLOOR_DB = -60.0


class OutputStream(Protocol):
    def start(self) -> None: ...

    def abort(self) -> None: ...

    def close(self) -> None: ...


StreamFactory = Callable[[int, int, Callable[..., None]], OutputStream]


def _device_stream(
    rate: int, block: int, callback: Callable[..., None]
) -> OutputStream:
    index = _wasapi_output()
    stream: Any = sd.OutputStream(  # pyright: ignore[reportUnknownMemberType]
        samplerate=rate,
        channels=1,
        dtype="float32",
        blocksize=block,
        callback=callback,
        device=index,
        # WasapiSettings on a non-WASAPI device fails with PaErrorCode -9984.
        extra_settings=sd.WasapiSettings(auto_convert=True)  # pyright: ignore[reportUnknownMemberType]
        if index is not None
        else None,
    )
    return stream


def _wasapi_output() -> int | None:
    """Index of the WASAPI default output; PortAudio's own default is MME on Windows."""
    wasapi = next(
        (h for h in sd.query_hostapis() if "WASAPI" in h["name"]),  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportGeneralTypeIssues]
        None,
    )
    return None if wasapi is None else int(wasapi["default_output_device"])  # pyright: ignore[reportUnknownArgumentType]


def level_of(block: npt.NDArray[np.float32]) -> float:
    """RMS of a block mapped from -60..0 dBFS to 0..1 (the HUD's audio.level)."""
    rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
    db = 20.0 * np.log10(max(rms, 1e-9))
    return float(min(1.0, max(0.0, (db - _FLOOR_DB) / -_FLOOR_DB)))


class Playout:
    def __init__(
        self,
        sample_rate: int,
        cfg: PlayoutConfig,
        *,
        on_first_audio: Callable[[int], None] = lambda ts_ns: None,
        on_level: Callable[[float], None] = lambda level: None,
        on_drained: Callable[[], None] = lambda: None,
        on_render: Callable[[npt.NDArray[np.float32]], None] = lambda block: None,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self._prebuffer = sample_rate * cfg.prebuffer_ms // 1000
        self._block = int(sample_rate * _BLOCK_S)
        self.on_first_audio = on_first_audio
        self.on_level = on_level
        self.on_drained = on_drained
        self.on_render = on_render
        self._factory = stream_factory or _device_stream
        self._stream: OutputStream | None = None
        self._lock = threading.Lock()
        self._chunks: collections.deque[npt.NDArray[np.float32]] = collections.deque()
        self._buffered = 0
        self._reset_utterance()
        self._since_level = 0

    def _reset_utterance(self) -> None:
        self._playing = False  # prebuffer reached (or the utterance ended early)
        self._ended = False
        self._started = False  # first audible sample delivered
        self._chunks.clear()
        self._buffered = 0
        self._played = 0

    @property
    def played(self) -> int:
        """Samples handed to the device in this utterance; `abort` resets it."""
        return self._played

    # --- event loop side ----------------------------------------------------------

    def start_utterance(self) -> None:
        with self._lock:
            self._reset_utterance()
            if self._stream is None:
                self._stream = self._factory(
                    self.sample_rate, self._block, self._callback
                )
                self._stream.start()

    def push(self, chunk: npt.NDArray[np.float32]) -> None:
        with self._lock:
            self._chunks.append(chunk)
            self._buffered += len(chunk)
            if self._buffered >= self._prebuffer:
                self._playing = True

    def end_utterance(self) -> None:
        """No more audio: play what is buffered, then fire `on_drained`."""
        with self._lock:
            self._ended = True
            self._playing = True

    def abort(self) -> None:
        """Silence now. The tail is at most one block; `on_drained` does not fire."""
        with self._lock:
            self._reset_utterance()
            stream = self._stream
        if stream is not None:
            stream.abort()
            stream.start()

    def close(self) -> None:
        with self._lock:
            self._reset_utterance()
            stream, self._stream = self._stream, None
        if stream is not None:
            stream.abort()
            stream.close()

    # --- audio thread -------------------------------------------------------------

    def _callback(self, outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        del time_info
        if status:
            log.warning("playout_status flags=%s", status)
        out = outdata[:, 0]
        out[:] = 0.0
        first = drained = False
        with self._lock:
            filled = 0
            if self._playing:
                while filled < frames and self._chunks:
                    head = self._chunks[0]
                    take = min(frames - filled, len(head))
                    out[filled : filled + take] = head[:take]
                    filled += take
                    if take == len(head):
                        self._chunks.popleft()
                    else:
                        self._chunks[0] = head[take:]
                self._buffered -= filled
                self._played += filled
                if filled and not self._started:
                    self._started = first = True
                if filled < frames and self._ended:
                    drained = True
                    self._reset_utterance()
            speaking = filled > 0
        self.on_render(out)  # speech or zeros: the reference has no gaps
        if first:
            self.on_first_audio(time.time_ns())
        if speaking:
            self._since_level += frames
            if self._since_level >= self.sample_rate * _LEVEL_EVERY_S:
                self._since_level = 0
                self.on_level(level_of(out[:filled]))
        if drained:
            self.on_drained()
