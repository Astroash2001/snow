"""Local tone of one finished user turn (D-35): prosody plus an optional emotion model.

In-memory only. The PCM arrives as bytes, becomes numpy arrays and is dropped; nothing
here opens a file for writing or a socket (the one-off model download is `fetch_model`,
run by hand, never by the worker). Cost is paid once per turn, off the audio thread.
"""

import hashlib
import logging
import statistics
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Literal

import numpy as np
import onnxruntime as ort

from snow.config.settings import repo_root
from snow.contracts.events import Tone
from snow.voice.config import ToneConfig

log = logging.getLogger("snow.voice")

Pace = Literal["slow", "normal", "fast"]
Loudness = Literal["quiet", "normal", "loud"]

_FRAME_S = 0.030  # voiced/unvoiced decision window
_PITCH_S = 0.040  # autocorrelation window
_VOICED_BELOW_PEAK_DB = 20  # a frame is voiced within this of the loud frames
_VOICED_FLOOR_DBFS = -50
_BRIDGE_FRAMES = 5  # a pause up to 2 x 150 ms between voiced frames is part of speech
_PITCH_RANGE_HZ = (60, 400)
_PITCH_MIN_PEAK = 0.3  # normalised autocorrelation peak that counts as a pitched window
_HISTORY = 20  # turns kept for the "relative to this user" categories
_MIN_HISTORY = 3  # below this the absolute thresholds decide


def model_dir() -> Path:
    return repo_root() / "models" / "tone"


def _check(data: bytes, sha256: str) -> bool:
    return hashlib.sha256(data).hexdigest() == sha256.lower()


def fetch_model(cfg: ToneConfig, dest: Path | None = None) -> Path:
    """Download the pinned model once and verify it (T-01-36). Run by hand:
    `python -m snow.voice.tone`. Raises if the URL is unset or the checksum differs."""
    if not cfg.model_url or not cfg.model_sha256:
        raise ValueError("[tone] model_url and model_sha256 must both be set")
    path = (dest or model_dir()) / cfg.model_url.rsplit("/", 1)[-1]
    if not cfg.model_url.startswith("https://"):
        raise ValueError("[tone] model_url must be https")
    with urllib.request.urlopen(cfg.model_url, timeout=60) as r:  # noqa: S310 - https checked above
        data = r.read()
    if not _check(data, cfg.model_sha256):
        raise ValueError("downloaded tone model failed its SHA-256 check")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)  # the model weights, not user audio
    return path


def _voiced(pcm: bytes, sample_rate: int) -> tuple[np.ndarray, float, float, float]:
    """(samples, voiced threshold, voiced seconds, voiced dBFS) of 16-bit mono PCM."""
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    n = int(_FRAME_S * sample_rate)
    frames = x[: len(x) // n * n].reshape(-1, n)
    rms = np.sqrt((frames**2).mean(axis=1)) if len(frames) else np.zeros(0)
    floor = 10 ** (_VOICED_FLOOR_DBFS / 20)
    thr = max(
        float(np.percentile(rms, 95)) * 10 ** (-_VOICED_BELOW_PEAK_DB / 20)
        if len(rms)
        else 0.0,
        floor,
    )
    voiced = rms > thr
    # Short pauses between words still count as speech for the pace.
    spoken = np.convolve(voiced, np.ones(2 * _BRIDGE_FRAMES + 1), "same") > 0
    if voiced.any():  # bridge gaps only: the clip's lead-in and tail are not speech
        on = np.flatnonzero(voiced)
        spoken[: on[0]] = spoken[on[-1] + 1 :] = False
    voiced_s = float(spoken.sum()) * _FRAME_S
    loudness = (
        20 * np.log10(max(float(np.sqrt((frames[voiced] ** 2).mean())), 1e-9))
        if voiced.any()
        else -100.0
    )
    return x, thr, voiced_s, float(loudness)


def voiced_level(pcm: bytes, sample_rate: int) -> tuple[float, float]:
    """(voiced seconds, voiced dBFS) of a turn; -100.0 dBFS when nothing is voiced."""
    _, _, voiced_s, dbfs = _voiced(pcm, sample_rate)
    return voiced_s, dbfs


class ToneAnalyzer:
    def __init__(self, cfg: ToneConfig, models_dir: Path | None = None) -> None:
        self._cfg = cfg
        self._history: deque[tuple[float, float]] = deque(maxlen=_HISTORY)
        self._session: Any = None  # onnxruntime ships no type stubs
        self._window = 0
        if cfg.model_url and cfg.model_sha256 and cfg.labels:
            self._load((models_dir or model_dir()) / cfg.model_url.rsplit("/", 1)[-1])

    def _load(self, path: Path) -> None:
        """Missing or tampered file: prosody only, never an error (the turn goes on)."""
        try:
            data = path.read_bytes()
            if not _check(data, self._cfg.model_sha256):
                log.warning("tone_model_rejected reason=checksum")
                return
            session: Any = ort.InferenceSession(
                data, providers=["CPUExecutionProvider"]
            )
            shape = session.get_inputs()[0].shape
            self._window = int(shape[-1])
            self._session = session
        except Exception as e:  # noqa: BLE001
            log.warning("tone_model_unavailable kind=%s", type(e).__name__)

    @property
    def has_model(self) -> bool:
        return self._session is not None

    def analyze(self, pcm: bytes, text: str, sample_rate: int = 16000) -> Tone:
        x, thr, voiced_s, loudness = _voiced(pcm, sample_rate)
        wpm = len(text.split()) / (voiced_s / 60) if voiced_s > 0 else 0.0
        pace, loud = self._categories(wpm, float(loudness))
        emotion, confidence = self._emotion(x)
        return Tone(
            emotion=emotion,
            emotion_confidence=confidence,
            pace=pace,
            loudness=loud,
            words_per_min=round(wpm, 1),
            loudness_dbfs=round(float(loudness), 1),
            pitch_hz_median=self._pitch(x, sample_rate, thr),
        )

    def _categories(self, wpm: float, db: float) -> tuple[Pace, Loudness]:
        c = self._cfg
        if len(self._history) >= _MIN_HISTORY:
            med_db = statistics.median(d for d, _ in self._history)
            med_wpm = statistics.median(w for _, w in self._history)
            fast, slow = wpm > med_wpm * 1.25, wpm < med_wpm * 0.75
        else:
            med_db = c.ref_loudness_dbfs
            fast, slow = wpm > c.fast_wpm, wpm < c.slow_wpm
        self._history.append((db, wpm))
        pace: Pace = "fast" if fast else "slow" if slow else "normal"
        if db > med_db + c.loud_offset_db:
            return pace, "loud"
        return pace, "quiet" if db < med_db - c.quiet_offset_db else "normal"

    def _pitch(self, x: np.ndarray, rate: int, thr: float) -> float | None:
        """Median of the pitched 40 ms windows' autocorrelation peaks, 60-400 Hz."""
        n = int(_PITCH_S * rate)
        w = x[: len(x) // n * n].reshape(-1, n)
        w = w[np.sqrt((w**2).mean(axis=1)) > thr]
        if not len(w):
            return None
        w = w - w.mean(axis=1, keepdims=True)
        size = 2 * n
        ac = np.fft.irfft(np.abs(np.fft.rfft(w, size)) ** 2, size)[:, :n]
        lo, hi = rate // _PITCH_RANGE_HZ[1], rate // _PITCH_RANGE_HZ[0]
        ac = ac / np.maximum(ac[:, :1], 1e-9)
        lag = lo + ac[:, lo:hi].argmax(axis=1)
        ok = ac[np.arange(len(w)), lag] > _PITCH_MIN_PEAK
        return round(float(np.median(rate / lag[ok])), 1) if ok.any() else None

    def _emotion(self, x: np.ndarray) -> tuple[str | None, float | None]:
        if self._session is None:
            return None, None
        # shortcut: only the last window of a long turn is scored; score every window
        # and average them if the end of a turn proves unrepresentative.
        win = np.zeros(self._window, np.float32)
        tail = x[-self._window :]
        win[: len(tail)] = tail
        name = self._session.get_inputs()[0].name
        out = np.asarray(self._session.run(None, {name: win[None]})[0])[0]
        z = out / self._cfg.temperature
        p = np.exp(z - z.max())
        p /= p.sum()
        i = int(p.argmax())
        if float(p[i]) < self._cfg.min_confidence or i >= len(self._cfg.labels):
            return None, None
        return self._cfg.labels[i], round(float(p[i]), 3)


if __name__ == "__main__":
    from snow.config.settings import load_config
    from snow.voice.config import VoiceConfig

    print(fetch_model(load_config("voice.toml", VoiceConfig).tone))  # noqa: T201
