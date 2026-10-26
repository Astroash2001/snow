"""Local streaming speech-to-text on the CPU with Moonshine (VOIC-04/08, D-38, D-39).

It gives the HUD live words while the user speaks and a local final transcript for the
turns Groq cannot take. Audio stays in memory and never leaves the PC. All Moonshine
calls run in one worker thread fed by a queue, so the wake/VAD thread never waits on it.
The model downloads once from Moonshine's own CDN into the gitignored `models/` cache.
"""

import logging
import queue
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from moonshine_voice import ModelArch, get_model_for_language

from snow.config.settings import repo_root
from snow.voice.config import LocalSttConfig

log = logging.getLogger("snow.voice")

_ARCH = {
    "tiny": ModelArch.TINY_STREAMING,
    "small": ModelArch.SMALL_STREAMING,
    "medium": ModelArch.MEDIUM_STREAMING,
}
_STOP = object()


def _join(lines: dict[int, str]) -> str:
    return " ".join(t.strip() for _, t in sorted(lines.items()) if t.strip())


class LocalStt:
    def __init__(
        self,
        cfg: LocalSttConfig,
        sample_rate: int = 16000,
        models_dir: Path | None = None,
    ) -> None:
        self._arch = _ARCH[cfg.model]
        self._interval_s = cfg.partial_interval_ms / 1000
        self._rate = sample_rate
        self._dir = models_dir or repo_root() / "models" / "moonshine"
        self._q: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()
        self._lines: dict[int, str] = {}  # line id -> text, written by the worker
        self._seen = ""  # what partial() last returned
        self._thread = threading.Thread(target=self._run, name="snow-moonshine")
        self._thread.daemon = True
        self._thread.start()

    # --- audio thread: all of these return immediately ----------------------------

    def start_turn(self) -> None:
        self._q.put(("start", None))

    def feed(self, frame: npt.NDArray[np.int16]) -> None:
        self._q.put(("frame", frame))

    def partial(self) -> str | None:
        """The words so far, only when they changed since the last call."""
        with self._lock:
            text = _join(self._lines)
            if text == self._seen:
                return None
            self._seen = text
            return text

    def finish(self) -> "Future[str]":
        """End the turn; the future holds the local final once queued audio is done."""
        done: Future[str] = Future()
        self._q.put(("finish", done))
        return done

    def transcribe(self, pcm: npt.NDArray[np.int16]) -> "Future[str]":
        """The words in an in-memory window, apart from any open turn (barge-in)."""
        done: Future[str] = Future()
        self._q.put(("transcribe", (pcm, done)))
        return done

    def cancel(self) -> None:
        """Drop the open turn without a transcript (wake alone, mute)."""
        self._q.put(("cancel", None))

    def close(self) -> None:
        self._q.put((_STOP, None))
        self._thread.join(timeout=5)

    # --- worker thread --------------------------------------------------------------

    def _run(self) -> None:
        try:
            from moonshine_voice.transcriber import Transcriber  # noqa: PLC0415

            path, arch = get_model_for_language("en", self._arch, cache_root=self._dir)
            transcriber = Transcriber(path, arch)
        except Exception:
            log.exception("local_stt_unavailable")
            self._drain_failed()
            return
        stream: Any = None
        while True:
            kind, arg = self._q.get()
            try:
                if kind is _STOP:
                    break
                if kind in ("start", "cancel") and stream is not None:
                    stream.close()  # a turn that never finished: drop it
                    stream = None
                if kind == "start":
                    self._reset()
                    stream = transcriber.create_stream(update_interval=self._interval_s)
                    stream.add_listener(self._on_event)
                    stream.start()
                elif kind == "frame" and stream is not None:
                    stream.add_audio(
                        (arg.astype(np.float32) / 32768.0).tolist(), self._rate
                    )
                elif kind == "transcribe":
                    window, done = arg
                    done.set_result(self._words(transcriber, window))
                elif kind == "finish":
                    arg.set_result(self._final(stream))
                    stream = None
                elif kind == "cancel":
                    self._reset()
            except Exception as e:  # noqa: BLE001 - one bad turn must not kill the worker
                log.warning("local_stt_failed kind=%s", type(e).__name__)
                if kind == "finish" and not arg.done():
                    arg.set_exception(e)
                if kind == "transcribe" and not arg[1].done():
                    arg[1].set_exception(e)
                    continue  # the open turn is untouched
                stream = None
        if stream is not None:
            stream.close()
        transcriber.close()

    def _words(self, transcriber: Any, pcm: npt.NDArray[np.int16]) -> str:
        samples = (pcm.astype(np.float32) / 32768.0).tolist()
        result = transcriber.transcribe_without_streaming(samples, self._rate)
        return " ".join(
            t for line in getattr(result, "lines", []) if (t := line.text.strip())
        )

    def _final(self, stream: Any) -> str:
        if stream is None:
            return ""
        result = stream.stop()
        lines = dict(self._lines)
        for line in getattr(result, "lines", []):
            lines[line.line_id] = line.text
        stream.close()
        self._reset()
        return _join(lines)

    def _on_event(self, event: Any) -> None:
        with self._lock:
            self._lines[event.line.line_id] = event.line.text

    def _reset(self) -> None:
        with self._lock:
            self._lines = {}
            self._seen = ""

    def _drain_failed(self) -> None:
        """The model never loaded: each turn's local final fails (the router knows)."""
        while True:
            kind, arg = self._q.get()
            if kind is _STOP:
                return
            if kind == "finish":
                arg.set_exception(RuntimeError("local speech model unavailable"))
            elif kind == "transcribe":
                arg[1].set_exception(RuntimeError("local speech model unavailable"))
