"""The echo canceller's reference from a WASAPI loopback (VOIC-06).

Output enhancers such as FxSound are a virtual default output: they change what Snow
plays (EQ, gain, saturation) and forward it to the real speakers. The canceller's render
reference (Snow's blocks before the enhancer) then no longer matches what the mic hears,
and Snow hears and pauses for itself. A loopback of the real speaker endpoint is the
signal after the enhancer, which is what the mic hears.

`LoopbackReference` opens that loopback with PyAudioWPatch, downmixes it to mono,
resamples it to the canceller's render rate and hands it to
`EchoCanceller.loopback_block`. Whenever the loopback is unavailable, lost, ambiguous or
silently dead the canceller goes back to the render reference at once and the loopback
is retried in the background. The audio lives in memory only (D-18): logs carry device
names, rates and reasons, never audio.
"""

import importlib
import logging
import threading
from collections.abc import Sequence
from typing import Any

import numpy as np
import soxr

from snow.voice.aec import EchoCanceller

log = logging.getLogger("snow.voice")


def is_enhancer(name: str, enhancers: Sequence[str]) -> bool:
    low = name.lower()
    return any(e and e.lower() in low for e in enhancers)


def pick_endpoint(
    outputs: Sequence[str], default: str, device: str, enhancers: Sequence[str]
) -> str | None:
    """The speaker endpoint whose loopback is the reference, or None when unclear.

    An enhancer's virtual device is loopback *before* processing; the real speakers
    behind it are after, so behind an enhancer only a single real output is safe to
    guess."""
    if device:
        return next((o for o in outputs if device.lower() in o.lower()), None)
    if not is_enhancer(default, enhancers):
        return default
    real = [o for o in outputs if not is_enhancer(o, enhancers)]
    return real[0] if len(real) == 1 else None


class _Unavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LoopbackReference:
    def __init__(
        self,
        aec: EchoCanceller,
        device: str = "",
        enhancers: Sequence[str] = (),
        *,
        pa: Any = None,
        check_s: float = 1.0,
        retry_s: float = 10.0,
        stale_s: float = 1.0,
    ) -> None:
        self._aec = aec
        self._device, self._enhancers = device, tuple(enhancers)
        self._pa = pa
        self._check_s, self._retry_s, self._stale_s = check_s, retry_s, stale_s
        self._stop = threading.Event()
        self._dead = threading.Event()  # set by the callback when it gives up
        self._logged: set[str] = set()
        self._thread = threading.Thread(
            target=self._run, name="snow-aec-loopback", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    # --- supervisor thread: every PyAudio call is made here (COM is per thread) ---

    def _run(self) -> None:
        last: str | None = None
        while not self._stop.is_set():
            reason = self._session()
            if reason != "loopback_lost" and reason != last:
                hint = (
                    " (set audio.aec_reference_device)"
                    if reason == "no_endpoint"
                    else ""
                )
                log.warning("aec_reference=render reason=%s%s", reason, hint)
            last = reason
            self._stop.wait(self._retry_s)

    def _session(self) -> str:
        """One open-and-watch cycle. Returns why it ended."""
        pa: Any = None
        stream: Any = None
        live = False
        device = ""
        try:
            try:
                mod: Any = self._pa or importlib.import_module("pyaudiowpatch")
            except ImportError:
                return "ImportError"
            pa = mod.PyAudio()
            info = self._endpoint(mod, pa)
            rate, channels = (
                int(info["defaultSampleRate"]),
                int(info["maxInputChannels"]),
            )
            resampler = (
                None
                if rate == self._aec.render_rate
                else soxr.ResampleStream(
                    rate, self._aec.render_rate, 1, dtype="float32"
                )
            )
            self._dead.clear()
            stream = pa.open(
                format=mod.paFloat32,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=info["index"],
                frames_per_buffer=rate // 100,
                stream_callback=self._callback(mod, channels, resampler),
            )
            self._aec.use_loopback(True)
            live, device = True, str(info["name"])
            log.info(
                "aec_reference=loopback device=%r rate=%d channels=%d",
                device,
                rate,
                channels,
            )
            self._watch(stream)
            return "loopback_lost"
        except _Unavailable as e:
            return e.reason
        except Exception as e:  # noqa: BLE001 - any failure means the render reference
            return type(e).__name__
        finally:
            if live:
                self._aec.use_loopback(False)
                if not self._stop.is_set():
                    log.warning(
                        "aec_reference=render reason=loopback_lost device=%r", device
                    )
            for step in (
                getattr(stream, "stop_stream", None),
                getattr(stream, "close", None),
                getattr(pa, "terminate", None),
            ):
                if step is not None:
                    try:
                        step()
                    except Exception:  # noqa: BLE001, S110 - already tearing down
                        pass

    def _endpoint(self, mod: Any, pa: Any) -> Any:
        outputs = {
            d["name"]: d
            for d in pa.get_device_info_generator_by_host_api(
                host_api_type=mod.paWASAPI
            )
            if d["maxOutputChannels"] > 0 and not d["isLoopbackDevice"]
        }
        default = str(pa.get_default_wasapi_device(d_out=True)["name"])
        name = pick_endpoint(list(outputs), default, self._device, self._enhancers)
        if name is None or name not in outputs:
            raise _Unavailable("no_endpoint")
        return pa.get_wasapi_loopback_analogue_by_dict(outputs[name])

    def _watch(self, stream: Any) -> None:
        while not self._stop.wait(self._check_s):
            try:
                active = bool(stream.is_active())
            except Exception:  # noqa: BLE001 - a stream that cannot answer is dead
                active = False
            if (
                not active
                or self._dead.is_set()
                or self._aec.loopback_stale(self._stale_s)
            ):
                return

    # --- PortAudio thread ---------------------------------------------------------

    def _callback(self, mod: Any, channels: int, resampler: Any) -> Any:
        def callback(
            in_data: Any, frame_count: int, time_info: Any, status: Any
        ) -> Any:
            del frame_count, time_info, status
            try:
                x = np.frombuffer(in_data, dtype=np.float32).reshape(-1, channels)
                mono = x.mean(axis=1, dtype=np.float32)
                if resampler is not None:
                    mono = resampler.resample_chunk(mono)
                if len(mono) == 0:  # the resampler is still filling its first chunk
                    return None, mod.paContinue
                self._aec.loopback_block(np.asarray(mono, dtype=np.float32))
                return None, mod.paContinue
            except Exception as e:  # noqa: BLE001 - must never escape a PortAudio callback
                kind = type(e).__name__
                if kind not in self._logged:
                    self._logged.add(kind)
                    log.warning("aec_loopback_failed kind=%s", kind)
                self._dead.set()
                return None, mod.paAbort

        return callback
