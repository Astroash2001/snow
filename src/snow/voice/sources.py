"""Audio sources: the live microphone and WAV files (tests, dev replay).

Audio is only ever held in memory (D-18). Both sources deliver fixed-size int16 frames
to one callback on one processing thread, so downstream code is single-threaded.
"""

import logging
import queue
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt
import sounddevice as sd  # pyright: ignore[reportMissingTypeStubs]

log = logging.getLogger("snow.voice")

Frame = npt.NDArray[np.int16]
OnFrame = Callable[[Frame], None]

_HOLD_MAX_S = 30.0
_REOPEN_START_S = 1.0  # microphone reopen backoff: doubles up to the max
_REOPEN_MAX_S = 30.0
_SILENCE_TAIL_S = 2.0  # lets the last turn of a recording end like live audio does


class AudioSource(Protocol):
    def open(self, on_frame: OnFrame) -> None: ...

    def close(self) -> None: ...

    @property
    def is_open(self) -> bool: ...


class _Pump:
    """Runs `on_frame` on a single thread; one bad frame never kills the thread."""

    def __init__(self, on_frame: OnFrame) -> None:
        self._on_frame = on_frame

    def deliver(self, frame: Frame) -> None:
        try:
            self._on_frame(frame)
        except Exception as e:  # noqa: BLE001 - a deaf worker is worse than a dropped frame
            log.error("frame_failed kind=%s", type(e).__name__)


def _wasapi_input(name: str) -> int | None:
    """Index of the WASAPI input device matching `name` (empty = the default one)."""
    wasapi = next(
        (h for h in sd.query_hostapis() if "WASAPI" in h["name"]),  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportGeneralTypeIssues]
        None,
    )
    if wasapi is None:
        return None
    if not name:
        return int(wasapi["default_input_device"])  # pyright: ignore[reportUnknownArgumentType]
    for index in wasapi["devices"]:  # pyright: ignore[reportUnknownVariableType]
        info = sd.query_devices(index)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if info["max_input_channels"] > 0 and name.lower() in info["name"].lower():  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            return int(index)  # pyright: ignore[reportUnknownArgumentType]
    return None


class MicSource:
    """The live microphone; a lost or missing device is retried with backoff.

    `on_health(ok)` is called from the audio thread: False when the stream is lost or
    cannot open, True once it runs again.
    """

    def __init__(
        self, device: str = "", sample_rate: int = 16000, frame_samples: int = 1280
    ) -> None:
        self._device = device
        self._rate = sample_rate
        self._frame = frame_samples
        self._q: queue.Queue[Frame] = queue.Queue(maxsize=200)  # 16 s of audio
        self._stop = threading.Event()
        self._lost = threading.Event()  # the stream ended on its own (unplugged)
        self._stream: sd.InputStream | None = None  # pyright: ignore[reportUnknownMemberType, reportInvalidTypeForm]
        self._thread: threading.Thread | None = None
        self.on_health: Callable[[bool], None] | None = None

    @property
    def is_open(self) -> bool:
        return self._thread is not None

    def _callback(self, indata: npt.NDArray[np.int16], *_: object) -> None:
        # PortAudio thread: copy and return, nothing else (Pitfall 10).
        try:
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            log.warning("mic_frame_dropped")

    def _start_stream(self) -> None:
        index = _wasapi_input(self._device)
        stream = sd.InputStream(  # pyright: ignore[reportUnknownMemberType]
            samplerate=self._rate,
            channels=1,
            dtype="int16",
            blocksize=self._frame,
            device=index,
            callback=self._callback,
            finished_callback=self._lost.set,
            # Without auto_convert WASAPI rejects 16 kHz on a 48 kHz device.
            extra_settings=sd.WasapiSettings(auto_convert=True)
            if index is not None
            else None,  # pyright: ignore[reportUnknownMemberType]
        )
        try:
            stream.start()
        except sd.PortAudioError:
            stream.close()
            raise
        self._stream = stream

    def _drop_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except sd.PortAudioError:
                log.warning("mic_close_failed")  # the device is gone; nothing to free

    def _report(self, ok: bool) -> None:
        if self.on_health is not None:
            self.on_health(ok)

    def _run(self, pump: _Pump) -> None:
        delay, next_try = _REOPEN_START_S, 0.0
        while not self._stop.is_set():
            if self._lost.is_set():
                self._lost.clear()
                self._drop_stream()
                self._report(False)
                next_try = time.monotonic() + delay
            if self._stream is None and time.monotonic() >= next_try:
                try:
                    self._start_stream()
                except sd.PortAudioError as e:
                    log.warning("mic_open_failed kind=%s", type(e).__name__)
                    self._report(False)
                    next_try = time.monotonic() + delay
                    delay = min(delay * 2, _REOPEN_MAX_S)
                else:
                    delay = _REOPEN_START_S
                    self._report(True)
            try:
                pump.deliver(self._q.get(timeout=0.1))
            except queue.Empty:
                continue

    def open(self, on_frame: OnFrame) -> None:
        self._q = queue.Queue(maxsize=200)  # nothing heard before a mute survives it
        self._stop.clear()
        self._lost.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(_Pump(on_frame),),
            name="snow-voice-audio",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._drop_stream()


def read_wav(path: Path, sample_rate: int) -> npt.NDArray[np.int16]:
    """Read a 16-bit PCM WAV as mono int16 at `sample_rate`."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: only 16-bit PCM WAV is supported")
        channels, rate = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    mono = (
        pcm.reshape(-1, channels).mean(axis=1)
        if channels > 1
        else pcm.astype(np.float64)
    )
    if rate != sample_rate:
        # shortcut: linear interpolation, use a polyphase filter if quality matters.
        target = np.arange(int(len(mono) * sample_rate / rate)) * rate / sample_rate
        mono = np.interp(target, np.arange(len(mono)), mono)
    return mono.astype(np.int16)


class FileSource:
    def __init__(
        self,
        path: Path,
        *,
        realtime: bool = False,
        sample_rate: int = 16000,
        frame_samples: int = 1280,
        hold: Callable[[], bool] | None = None,
    ) -> None:
        self._gave_up = False
        self.hold = hold  # True = wait: a reply is pending, like a user listening
        self._path = path
        self._realtime = realtime
        self._rate = sample_rate
        self._frame = frame_samples
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def is_open(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def open(self, on_frame: OnFrame) -> None:
        silence = np.zeros(int(_SILENCE_TAIL_S * self._rate), dtype=np.int16)
        audio = np.concatenate([read_wav(self._path, self._rate), silence])
        pump = _Pump(on_frame)
        self._stop.clear()

        def run() -> None:
            for start in range(0, len(audio) - self._frame + 1, self._frame):
                if self._stop.is_set():
                    return
                pump.deliver(audio[start : start + self._frame])
                self._wait_while_held()
                if self._realtime:
                    time.sleep(self._frame / self._rate)

        self._thread = threading.Thread(target=run, name="snow-voice-file", daemon=True)
        self._thread.start()

    def _wait_while_held(self) -> None:
        # shortcut: one capped wall wait per pending reply, so a silent brain cannot
        # hang a replay; after it the file just plays on.
        if not (self.hold and self.hold()):
            self._gave_up = False
            return
        deadline = time.monotonic() + _HOLD_MAX_S
        while not self._gave_up and self.hold() and not self._stop.is_set():
            if time.monotonic() >= deadline:
                self._gave_up = True
            time.sleep(0.005)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
