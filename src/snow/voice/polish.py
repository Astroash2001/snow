"""Voice polish: the streaming stage between a TTS engine and the playout ring buffer.

Chain, in order (every part but the device-rate resample has a switch in [polish] of
config/tts.toml): edge trim with 5 ms fades -> clause pause zeros -> one soxr stream
(device rate and pace) -> EQ and reverb as one convolution -> compressor, makeup gain
and a lookahead limiter.

Every sample is processed before `Playout.push`, never in the audio callback, so
`Playout.on_render` (the echo canceller's reference) still receives exactly what plays
(VOIC-06). A new `Polish` is made per reply: an aborted reply's tail never reaches the
next one. Audio stays in memory only (D-18); nothing here logs or stores it.

Streaming: each engine chunk is processed as it arrives; filter, resampler, compressor
and reverb state carries across chunks, so the result does not depend on chunk sizes.
"""

from functools import lru_cache

import numpy as np
import numpy.typing as npt
import soxr

from snow.voice.tts.base import Samples
from snow.voice.tts.config import PolishConfig

# Below -50 dBFS a sample is silence: the engine's lead-in and tail-out, not speech.
_SILENCE = 10 ** (-50 / 20)
# 10 ms of lead keeps an onset's breath; 30 ms of tail keeps a natural decay.
_LEAD_S, _TRAIL_S = 0.010, 0.030
# 5 ms removes the click of cutting a waveform mid-cycle, without softening speech.
_FADE_S = 0.005
# Dynamics work on 10 ms frames, like the echo canceller's.
_FRAME_S = 0.010
# Compressor: gentle 2.5:1 above -26 dBFS; fast attack keeps peaks in, slow release
# avoids pumping between words.
_THRESHOLD_DB, _RATIO = -26.0, 2.5
_ATTACK_S, _RELEASE_S = 0.005, 0.120
# Limiter ceiling -1 dBFS; the gain comes back toward 1 over about 80 ms.
_CEILING = 10 ** (-1 / 20)
_LIMITER_RELEASE_S = 0.080
# Punctuation that ends a clause: the pause that follows it.
_SENTENCE_END, _COMMA_END = ".?!\u2026", ",;:-\u2013\u2014"
_CLOSERS = " \t\r\n\"')]}\u201d\u2019"
# EQ: a linear-phase FIR designed by frequency sampling (warmth shelf, presence bell,
# 4th-order Butterworth low-pass at 10 kHz).
_EQ_TAPS, _EQ_GRID = 1025, 16384
_WARMTH_HZ, _PRESENCE_HZ, _PRESENCE_OCT, _LOWPASS_HZ = 180.0, 2800.0, 0.6, 10000.0
# Reverb: 12 ms pre-delay, 300 ms of noise decaying 60 dB, darkened, unit energy.
_PREDELAY_S, _REVERB_S, _REVERB_SEED = 0.012, 0.300, 1
# A convolution tail quieter than -66 dBFS is inaudible: flush stops there.
_TAIL_FLOOR = 10 ** (-66 / 20)
_EMPTY: Samples = np.zeros(0, dtype=np.float32)


def _db(power: float) -> float:
    return 10.0 * float(np.log10(max(power, 1e-12)))


@lru_cache(maxsize=8)
def _impulse(
    rate: int, eq: bool, warmth_db: float, presence_db: float, wet: float
) -> npt.NDArray[np.float64]:
    """EQ and reverb as one impulse response (the unit impulse when both are off)."""
    fir = np.zeros(_EQ_TAPS)
    fir[_EQ_TAPS // 2] = 1.0
    if eq:
        f = np.maximum(np.arange(_EQ_GRID // 2 + 1) * rate / _EQ_GRID, 1e-3)
        bell = np.exp(-0.5 * (np.log2(f / _PRESENCE_HZ) / _PRESENCE_OCT) ** 2)
        gain_db = warmth_db / (1 + (f / _WARMTH_HZ) ** 2) + presence_db * bell
        mag = 10 ** (gain_db / 20) / np.sqrt(1 + (f / _LOWPASS_HZ) ** 8)
        zero_phase = np.fft.irfft(mag, _EQ_GRID)
        half = _EQ_TAPS // 2
        fir = np.concatenate([zero_phase[-half:], zero_phase[: half + 1]])
        fir *= np.hanning(_EQ_TAPS)
    if wet <= 0:
        return fir
    t = np.arange(int(_REVERB_S * rate)) / rate
    noise = np.random.default_rng(_REVERB_SEED).standard_normal(len(t))
    tail = noise * np.exp(-t * np.log(1000) / _REVERB_S)
    tail = np.convolve(tail, np.ones(4) / 4, mode="same")
    tail *= wet / np.sqrt(np.sum(tail**2))
    wet_ir = np.concatenate([np.zeros(int(_PREDELAY_S * rate)), tail])
    wet_ir[0] += 1.0  # the dry path
    size = 1 << (len(fir) + len(wet_ir)).bit_length()
    both = np.fft.irfft(np.fft.rfft(fir, size) * np.fft.rfft(wet_ir, size), size)
    return both[: len(fir) + len(wet_ir) - 1]


class _Convolver:
    """FFT overlap-add convolution of a stream, for any block size."""

    def __init__(self, ir: npt.NDArray[np.float64], delay: int) -> None:
        self._ir = ir
        self._tail = np.zeros(len(ir) - 1)
        self._skip = delay  # a linear-phase FIR's delay is removed from the start
        self._spectra: dict[int, npt.NDArray[np.complex128]] = {}

    def run(self, x: Samples) -> Samples:
        n, m = len(x), len(self._ir)
        if n == 0:
            return x
        size = 1 << (n + m - 2).bit_length()
        if size not in self._spectra:
            self._spectra[size] = np.fft.rfft(self._ir, size)
        y = np.fft.irfft(np.fft.rfft(x, size) * self._spectra[size], size)[: n + m - 1]
        y[: m - 1] += self._tail
        self._tail = y[n:]
        return self._drop_delay(y[:n])

    def flush(self) -> Samples:
        """The ring-out after the last input, up to where it falls below audibility."""
        tail, self._tail = self._tail, np.zeros(0)
        loud = np.flatnonzero(np.abs(tail) > _TAIL_FLOOR)
        return self._drop_delay(tail[: int(loud[-1]) + 1] if len(loud) else tail[:0])

    def _drop_delay(self, y: npt.NDArray[np.float64]) -> Samples:
        skip = min(self._skip, len(y))
        self._skip -= skip
        return y[skip:].astype(np.float32)


class Polish:
    def __init__(self, cfg: PolishConfig, in_rate: int, out_rate: int) -> None:
        self._cfg = cfg
        self._in_rate, self._out_rate = in_rate, out_rate
        # The device-rate resample is always on; with equal rates and every part off the
        # whole chain is a pass-through.
        # Pace is the resampler's rate: played at out_rate the speech is longer and
        # lower together. shortcut: a pure time-stretch needs a phase vocoder; revisit
        # if the pitch drop is unwanted.
        self._resampler = (
            soxr.ResampleStream(
                float(in_rate),
                out_rate / cfg.pace,
                1,
                dtype="float32",
                quality="VHQ",
            )
            if in_rate != out_rate or cfg.pace < 1.0
            else None
        )
        self._dynamics = not cfg.all_off
        self._passthrough = self._resampler is None and cfg.all_off
        # EQ and reverb at out_rate as one convolution; skipped when both are off.
        self._conv = (
            _Convolver(
                _impulse(
                    out_rate, cfg.eq, cfg.warmth_db, cfg.presence_db, cfg.reverb_wet
                ),
                _EQ_TAPS // 2 if cfg.eq else 0,
            )
            if cfg.eq or cfg.reverb_wet > 0
            else None
        )
        # edges (at in_rate)
        self._lead = int(in_rate * _LEAD_S)
        self._trail = int(in_rate * _TRAIL_S)
        self._fade = max(1, int(in_rate * _FADE_S))
        self._fade_in = np.linspace(0.0, 1.0, self._fade, dtype=np.float32)
        self._fade_out = self._fade_in[::-1].copy()
        self._open = False  # the clause's first loud sample has been seen
        self._quiet_lead: Samples = _EMPTY  # last lead-margin samples before the onset
        self._held: Samples = _EMPTY  # tail not yet emitted: always ends the clause
        self._faded = 0  # samples emitted since the clause opened (fade-in position)
        # dynamics (at out_rate)
        self._frame = int(out_rate * _FRAME_S)
        self._carry: Samples = _EMPTY  # a partial frame waits for the next push
        self._attack = float(np.exp(-_FRAME_S / _ATTACK_S))
        self._release = float(np.exp(-_FRAME_S / _RELEASE_S))
        self._lim_release = float(np.exp(-_FRAME_S / _LIMITER_RELEASE_S))
        self._env_db = -100.0
        self._comp_gain = 1.0  # gain at the end of the previous frame
        self._lim_gain = (
            1.0  # applied limiter gain at the end of the last emitted frame
        )
        # the frame waiting for its successor's peak: (samples, gain it needs)
        self._wait: tuple[Samples, float] | None = None

    # --- public ---------------------------------------------------------------------

    def process(self, audio: Samples) -> Samples:
        """One engine chunk in; whatever is ready out (may be empty)."""
        if self._passthrough:
            return audio
        return self._after_edges(self._edges(audio) if self._cfg.trim_edges else audio)

    def end_clause(self, text: str) -> Samples:
        """The clause `text` started is fully synthesized: release its held tail."""
        if self._passthrough:
            return _EMPTY
        tail = self._end_edges() if self._cfg.trim_edges else _EMPTY
        # The pause is silence at the voice rate, scaled so it plays as configured.
        ms = self._pause_ms(text)
        pause = np.zeros(int(self._in_rate * ms / 1000 * self._cfg.pace), np.float32)
        return self._after_edges(np.concatenate([tail, pause]))

    def flush(self) -> Samples:
        """The reply is over: everything still held, then nothing more."""
        if self._passthrough:
            return _EMPTY
        x = self._end_edges() if self._cfg.trim_edges else _EMPTY
        if self._resampler is not None:
            x = self._resample(x, last=True)
        if self._conv is not None:
            x = np.concatenate([self._conv.run(x), self._conv.flush()])
        return np.concatenate([self._through_dynamics(x), self._dynamics_flush()])

    def _pause_ms(self, text: str) -> int:
        end = text.rstrip(_CLOSERS)[-1:]
        if end and end in _SENTENCE_END:
            return self._cfg.sentence_pause_ms
        return self._cfg.comma_pause_ms if end and end in _COMMA_END else 0

    # --- edges ----------------------------------------------------------------------

    def _edges(self, x: Samples) -> Samples:
        if not self._open:
            buf = np.concatenate([self._quiet_lead, x])
            loud = np.flatnonzero(np.abs(buf) > _SILENCE)
            if (
                len(loud) == 0
            ):  # still in the engine's silence: keep only the lead margin
                self._quiet_lead = buf[max(0, len(buf) - self._lead) :]
                return _EMPTY
            self._open, self._quiet_lead = True, _EMPTY
            x = buf[max(0, int(loud[0]) - self._lead) :]
        held = np.concatenate([self._held, x])
        loud = np.flatnonzero(np.abs(held) > _SILENCE)
        last = int(loud[-1]) + 1 if len(loud) else 0
        emit = min(last, len(held) - self._fade)  # always hold the last fade-length
        if emit <= 0:
            self._held = held
            return _EMPTY
        out, self._held = held[:emit].copy(), held[emit:]
        n = min(len(out), max(0, self._fade - self._faded))
        if n:
            out[:n] *= self._fade_in[self._faded : self._faded + n]
        self._faded += len(out)
        return out

    def _end_edges(self) -> Samples:
        held = self._held
        loud = np.flatnonzero(np.abs(held) > _SILENCE)
        last = int(loud[-1]) + 1 if len(loud) else 0
        out = held[: min(len(held), last + self._trail)].copy()
        n = min(len(out), self._fade)
        if n:
            out[len(out) - n :] *= self._fade_out[self._fade - n :]
        self._open, self._held, self._quiet_lead, self._faded = (
            False,
            _EMPTY,
            _EMPTY,
            0,
        )
        return out

    # --- rate, then dynamics --------------------------------------------------------

    def _after_edges(self, x: Samples) -> Samples:
        if self._resampler is not None:
            x = self._resample(x)
        if self._conv is not None:
            x = self._conv.run(x)
        return self._through_dynamics(x)

    def _resample(self, x: Samples, last: bool = False) -> Samples:
        assert self._resampler is not None  # noqa: S101
        return self._resampler.resample_chunk(x, last=last).astype(
            np.float32, copy=False
        )

    def _through_dynamics(self, x: Samples) -> Samples:
        if not self._dynamics:
            return x
        buf = np.concatenate([self._carry, x])
        whole = len(buf) - len(buf) % self._frame
        self._carry = buf[whole:]
        out = [
            done
            for i in range(0, whole, self._frame)
            if (done := self._frame_step(buf[i : i + self._frame])) is not None
        ]
        return np.concatenate(out) if out else _EMPTY

    def _dynamics_flush(self) -> Samples:
        pad = len(self._carry)
        if not pad:
            return self._finish_wait()
        frame = np.concatenate(
            [self._carry, np.zeros(self._frame - pad, dtype=np.float32)]
        )
        self._carry = _EMPTY
        done = self._frame_step(frame)
        # the padded frame is the last one: its padding is dropped from the end
        return np.concatenate(
            [_EMPTY if done is None else done, self._finish_wait()[:pad]]
        )

    def _finish_wait(self) -> Samples:
        if self._wait is None:
            return _EMPTY
        return self._emit_waiting(1.0)

    def _frame_step(self, frame: Samples) -> Samples | None:
        """Compress a frame; the previous one is released once this peak is known."""
        gain = 10 ** (self._cfg.makeup_db / 20)
        if self._cfg.compressor:
            level = _db(float(np.mean(np.square(frame, dtype=np.float64))))
            coef = self._attack if level > self._env_db else self._release
            self._env_db = coef * self._env_db + (1.0 - coef) * level
            reduction = max(0.0, self._env_db - _THRESHOLD_DB) * (1.0 - 1.0 / _RATIO)
            gain *= 10 ** (-reduction / 20)
        ramp = np.linspace(self._comp_gain, gain, self._frame + 1, dtype=np.float32)[1:]
        self._comp_gain = gain
        shaped = frame * ramp
        peak = float(np.max(np.abs(shaped)))
        need = min(1.0, _CEILING / peak) if peak > 0 else 1.0
        done = self._emit_waiting(need) if self._wait is not None else None
        self._wait = (shaped, need)
        return done

    def _emit_waiting(self, next_need: float) -> Samples:
        assert self._wait is not None  # noqa: S101
        shaped, need = self._wait
        released = self._lim_gain + (1.0 - self._lim_gain) * (1.0 - self._lim_release)
        target = min(need, next_need, released)
        ramp = np.linspace(self._lim_gain, target, len(shaped) + 1, dtype=np.float32)[
            1:
        ]
        self._lim_gain, self._wait = target, None
        return np.clip(shaped * ramp, -_CEILING, _CEILING)
