"""Chatterbox, the GPU voice (D-33, D-39): richer everyday emotion, only when free.

Chatterbox speaks everyday replies only while the laptop is on mains power and the
GPU has the configured free VRAM and low utilisation (`GpuPolicy`). It lives in its
own uv environment and process (engines/chatterbox: chatterbox-tts pins numpy 1 and
torch 2.6, which cannot share the core environment). The process is started in the
background once the policy allows it, stopped as soon as the policy turns false
(freeing the VRAM) or after `unload_after_s` without a reply, and a crash or a
stalled server makes the router speak the rest in Pocket TTS (SPCH-03).

Wire protocol (engines/chatterbox/server.py has the other side): JSON lines on
stdin; on stdout `uint32 length + float32 PCM` frames, a zero length closing a
`speak`, and a length with bit 31 set announcing that many bytes of JSON (the answer
to `load` / `vram`, or `{"error"}` inside a `speak`). Audio crosses a pipe in memory
and is never written to disk (D-18). The process gets a minimal environment: no
keys, no hub token.

Shortcuts: a reply cut off by barge-in is not aborted inside the server (0.1.7
generates a whole sentence per call), so the next sentence waits for the one still
generating; the GPU look is the median of three readings, with no hysteresis.
"""

import asyncio
import json
import logging
import os
import shutil
import statistics
import struct
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import IO, Any, Literal

import numpy as np
import psutil

from snow.voice.tts.base import (
    EngineError,
    EngineLoadError,
    EngineName,
    Samples,
)
from snow.voice.tts.config import CONSENTS, ChatterboxConfig, PocketConfig, VoiceClip

log = logging.getLogger("snow.voice")

SwitchReason = Literal["power", "gpu_busy"]
AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".ogg")
_CONTROL = 0x80000000
_SPEAK_TIMEOUT_S = 60.0  # one sentence; a server that takes longer is treated as hung
_RETRY_S = 300.0  # after a failed start, how long before the next attempt
_COOLDOWN_S = 5.0  # utilisation this soon after our own speech is still ours
_SAMPLES = 3  # nvidia-smi readings per look; the median counts
_SAMPLE_GAP_S = 0.25
_STALE_FACTOR = 3  # allowed() looks again on its own after this many intervals
_DONE = object()
# What the server needs to find Python, CUDA and the Hugging Face cache, and no more.
_ENV_SET = {
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PYTHONUNBUFFERED": "1",
}
_ENV_KEEP = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "APPDATA",
    "PROGRAMDATA",
    "HF_HOME",
    "HF_HUB_CACHE",
    "TORCH_HOME",
)


def _smi_fallback() -> str | None:
    """Where the driver installs it, for a PATH that lacks System32 (a scheduled task,
    a trimmed shell)."""
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    for path in (
        Path(root) / "System32" / "nvidia-smi.exe",
        Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
    ):
        if path.is_file():
            return str(path)
    return None


def _nvidia_smi() -> tuple[float, float] | None:
    """(free VRAM in MB, GPU utilisation in percent) of the first GPU, or None."""
    exe = shutil.which("nvidia-smi") or _smi_fallback()
    if exe is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - a fixed query of the NVIDIA tool
            [
                exe,
                "--query-gpu=memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        free, util = out.strip().splitlines()[0].split(",")
        return float(free), float(util)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class GpuPolicy:
    """True only on mains power with enough free VRAM and a quiet GPU (D-33, D-39).

    Read-only: power comes from `psutil.sensors_battery()` (no battery means a
    desktop, which is always on mains) and the GPU from `nvidia-smi`. A missing
    `nvidia-smi` or an unreadable answer counts as busy: Snow never takes a GPU it
    cannot see.
    """

    def __init__(
        self,
        cfg: ChatterboxConfig,
        *,
        battery: Callable[[], Any] = psutil.sensors_battery,
        smi: Callable[[], tuple[float, float] | None] = _nvidia_smi,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = cfg
        self._battery = battery
        self._smi = smi
        self._clock = clock
        self._sleep = sleep
        self._ok = False
        self._reason: SwitchReason | None = "power"
        self._at: float | None = None
        # Set by the engine: the VRAM its own process holds (counted as free, it is
        # ours) and whether it is synthesising (its own utilisation is not "busy").
        self.own_vram_mb = 0.0
        self.self_busy = False
        self.free_mb: float | None = None  # of the latest look, for the engine

    @property
    def reason(self) -> SwitchReason | None:
        """Why the policy is false (power or gpu_busy), None while it is true."""
        return self._reason

    def refresh(self) -> bool:
        """Look now (blocking: runs `nvidia-smi`). Returns the new answer."""
        self._at = self._clock()
        battery = self._battery()
        if battery is not None and battery.power_plugged is not True:
            self._ok, self._reason = False, "power"
            return False
        gpu = self._look()
        if gpu is None:
            self.free_mb = None
            self._ok, self._reason = False, "gpu_busy"
            return False
        free, util = gpu
        self.free_mb = free
        busy = free + self.own_vram_mb < self._cfg.min_free_vram_mb or (
            not self.self_busy and util > self._cfg.max_gpu_util
        )
        self._ok, self._reason = (not busy), ("gpu_busy" if busy else None)
        return self._ok

    def _look(self) -> tuple[float, float] | None:
        """The median of a few quick readings: the desktop compositor makes the GPU
        spike for a moment, and one spike must not take the voice away."""
        looks: list[tuple[float, float]] = []
        for i in range(_SAMPLES):
            if i:
                self._sleep(_SAMPLE_GAP_S)
            gpu = self._smi()
            if gpu is None:
                return None
            looks.append(gpu)
        return (
            statistics.median(g[0] for g in looks),
            statistics.median(g[1] for g in looks),
        )

    def free_now(self) -> float | None:
        """Free VRAM in MB right now, without changing the policy's answer."""
        gpu = self._smi()
        return None if gpu is None else gpu[0]

    def allowed(self) -> bool:
        """The latest answer. The engine's upkeep looks every `check_interval_s`; this
        looks by itself only before the first look, or when upkeep has stopped."""
        if (
            self._at is None
            or self._clock() - self._at > _STALE_FACTOR * self._cfg.check_interval_s
        ):
            self.refresh()
        return self._ok


def resolve_reference(cfg: ChatterboxConfig, pocket: PocketConfig) -> VoiceClip | None:
    """The clip both local voices clone (D-05): Chatterbox's own, else Pocket's when
    that is an audio file (a preset name or a .safetensors state is Pocket-only), else
    None (Chatterbox's built-in default voice)."""
    if cfg.reference is not None:
        return cfg.reference
    ref = pocket.reference
    if ref.path.lower().endswith(AUDIO_SUFFIXES) and Path(ref.path).is_file():
        return ref
    return None


def _read_exact(pipe: IO[Any], n: int) -> bytes:
    data = pipe.read(n)
    if len(data) != n:
        raise EOFError
    return data


def _read_frame(pipe: IO[Any]) -> tuple[Literal["audio", "end", "control"], Any]:
    (head,) = struct.unpack("<I", _read_exact(pipe, 4))
    if head == 0:
        return "end", None
    if head & _CONTROL:
        return "control", json.loads(_read_exact(pipe, head & ~_CONTROL))
    return "audio", np.frombuffer(_read_exact(pipe, head), dtype="<f4").copy()


class ChatterboxEngine:
    name: EngineName = "chatterbox"

    def __init__(
        self,
        cfg: ChatterboxConfig,
        policy: GpuPolicy,
        root: Path,
        reference: VoiceClip | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = cfg
        self.policy = policy
        self._python = root / cfg.python
        self._server = root / cfg.server
        self._reference = reference
        self._clock = clock
        self.voice_name = Path(reference.path).stem if reference else "chatterbox"
        self.sample_rate = 24000  # replaced by the model's own rate once loaded
        self.peak_vram_mb = 0.0  # the server's torch peak, read after the load
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()  # one request on the pipes at a time
        self._starting = False
        self._want = True  # false after an idle unload, until the next reply
        self._retry_at = 0.0
        self._last_used = clock()
        self._last_check = float("-inf")
        self._speaking = False
        self._stop_when_quiet = False
        self._last_spoke = float("-inf")
        self._stop = threading.Event()

    # --- lifecycle ------------------------------------------------------------------

    def load(self) -> None:
        """Checks only: the environment exists, the reference is consented and a file.
        The model is loaded in the background by `maintain`, never at start-up."""
        if not self._python.is_file() or not self._server.is_file():
            log.error("tts_load_failed engine=chatterbox kind=environment_missing")
            raise EngineLoadError
        ref = self._reference
        if ref is not None and (
            ref.consent not in CONSENTS or not Path(ref.path).is_file()
        ):
            log.error("tts_load_failed engine=chatterbox kind=reference_refused")
            raise EngineLoadError

    def warm(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None and not self._starting

    def usable(self) -> bool:
        """What the router asks: the policy is true and the model is loaded."""
        return self.warm() and self.policy.allowed()

    def touch(self) -> None:
        """A reply is starting: keep the model, or bring it back after an unload."""
        self._last_used = self._clock()
        self._want = True

    def close(self) -> None:
        self._stop_server()

    async def maintain(self) -> SwitchReason | None:
        """Called every few seconds. Returns the reason exactly when it just stopped a
        loaded model because the policy turned false, so the router can say so once."""
        now = self._clock()
        if self._stop_when_quiet and not self._speaking:
            self._stop_when_quiet = False
            await asyncio.to_thread(self._stop_server)
        if self._starting or now - self._last_check < self._cfg.check_interval_s:
            return None
        self._last_check = now
        if self._proc is not None and self._proc.poll() is not None:
            log.error("chatterbox_process_died")
            await asyncio.to_thread(self._stop_server)
        was_warm = self.warm()
        # Our own synthesis (and the few seconds after it) is not "the GPU is busy".
        self.policy.self_busy = self._speaking or now - self._last_spoke < _COOLDOWN_S
        allowed = await asyncio.to_thread(self.policy.refresh)
        if was_warm and not allowed and self._stop_when_quiet:
            return None  # already announced; the process stops when the sentence ends
        if was_warm and not allowed:
            reason = self.policy.reason
            if (
                self._speaking
            ):  # let the sentence in hand finish; the next ones are Pocket's
                self._stop_when_quiet = True
            else:
                await asyncio.to_thread(self._stop_server)
            return reason
        if was_warm and now - self._last_used > self._cfg.unload_after_s:
            self._want = False
            await asyncio.to_thread(self._stop_server)
        elif allowed and not was_warm and self._want and now >= self._retry_at:
            self._starting = True
            asyncio.get_running_loop().run_in_executor(None, self._start_guarded)
        elif not allowed and self._proc is not None:  # still loading: give the GPU back
            await asyncio.to_thread(self._stop_server)
        return None

    # --- the server process ---------------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
        # No cached Hugging Face token (it breaks public repos), no telemetry.
        env.update(_ENV_SET)
        return env

    def _start_guarded(self) -> None:
        try:
            self._start()
        except Exception as e:  # noqa: BLE001 - a broken GPU voice must never break speech
            log.error("chatterbox_start_failed kind=%s", type(e).__name__)
            self._stop_server()
            self._retry_at = self._clock() + _RETRY_S
        finally:
            self._starting = False

    def _start(self) -> None:
        proc = subprocess.Popen(  # noqa: S603 - our own interpreter and script
            [str(self._python), str(self._server)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=self._env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._proc = proc
        free_before = self.policy.free_mb
        reference = self._reference.path if self._reference else None
        reply = self._ask(
            {"op": "load", "device": "cuda", "reference": reference},
            self._cfg.load_timeout_s,
        )
        if not reply.get("ok"):
            raise EngineError("load_failed")
        self.sample_rate = int(reply["sr"])
        vram = self._ask({"op": "vram"}, 10.0)
        self.peak_vram_mb = float(vram.get("peak_mb", 0.0))
        after = self.policy.free_now()
        if free_before is not None and after is not None:
            self.policy.own_vram_mb = max(0.0, free_before - after)
        self._last_used = self._clock()
        log.info(
            "chatterbox_ready load_s=%.1f warm_s=%.1f peak_vram_mb=%.0f",
            reply.get("load_s", 0),
            reply.get("warm_s", 0),
            self.peak_vram_mb,
        )

    def _ask(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        """One control request and its answer; a server that stalls is killed."""
        proc = self._proc
        assert proc is not None and proc.stdin and proc.stdout  # noqa: S101
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            proc.stdin.write((json.dumps(request) + "\n").encode())
            proc.stdin.flush()
            kind, data = _read_frame(proc.stdout)
        finally:
            timer.cancel()
        if kind != "control":
            raise EngineError("unreachable")
        return data

    def _stop_server(self) -> None:
        proc, self._proc = self._proc, None
        self.policy.own_vram_mb = 0.0
        if proc is None:
            return
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write(b'{"op":"quit"}\n')
                proc.stdin.flush()
                proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if proc.poll() is None:
                proc.kill()  # only the process this engine started
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    try:
                        pipe.close()
                    except OSError:
                        pass
            proc.wait()

    # --- speaking -------------------------------------------------------------------

    def cancel(self) -> None:
        self._stop.set()

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        """Mono float32 chunks of one sentence. A server that is not loaded, died or
        stalled raises `EngineError`, so the router speaks it in Pocket TTS."""
        proc = self._proc
        if proc is None or not self.warm():
            raise EngineError("unreachable")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = threading.Event()
        self._stop = stop
        request = {
            "op": "speak",
            "id": 0,
            "text": text,
            "exaggeration": self._cfg.exaggeration_for(emotion),
            "cfg_weight": self._cfg.cfg_weight,
        }

        def work() -> None:
            # Holds the pipes until the end frame, even for a cancelled reply, so the
            # next request never reads the tail of this one.
            with self._lock:
                self._speaking = True
                try:
                    assert proc.stdin and proc.stdout  # noqa: S101
                    proc.stdin.write((json.dumps(request) + "\n").encode())
                    proc.stdin.flush()
                    while True:
                        kind, data = _read_frame(proc.stdout)
                        if kind == "end":
                            break
                        if kind == "control":
                            loop.call_soon_threadsafe(
                                queue.put_nowait, EngineError("unreachable")
                            )
                        elif not stop.is_set():
                            loop.call_soon_threadsafe(queue.put_nowait, data)
                except (OSError, EOFError, struct.error, ValueError):
                    loop.call_soon_threadsafe(
                        queue.put_nowait, EngineError("unreachable")
                    )
                    proc.kill()  # pipes out of step; upkeep starts a new process
                finally:
                    self._speaking = False
                    self._last_spoke = self._clock()
                    loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        worker = loop.run_in_executor(None, work)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), _SPEAK_TIMEOUT_S)
                except TimeoutError:
                    proc.kill()  # unblocks the reader with an end of file
                    raise EngineError("unreachable") from None
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            stop.set()
            await worker
