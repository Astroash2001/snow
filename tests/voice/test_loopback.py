"""FxSound-proof echo cancellation (VOIC-06): the loopback reference.

Nothing is played, no audio device is opened and nothing is written: PyAudioWPatch is a
fake module, the room is the seeded impulse response of test_echo_cancel, and the
"enhancer" is a deterministic gain-pumping and saturation stage. The numbers are
deterministic for the pinned livekit and a fixed seed.
"""

import builtins
import logging
import time
import wave
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest
import soxr

from snow.voice.aec import EchoCanceller
from snow.voice.loopback import LoopbackReference, is_enhancer, pick_endpoint
from tests.voice.test_echo_cancel import (
    FRAME,
    MIN_RUN_MS,
    SR,
    TR,
    Pcm,
    Scene,
    drive,
    echo_of,
    erle_db,
    longest_run_ms,
    noise,
    to_pcm,
)

REAL = "Speakers (Realtek(R) Audio)"
FX = "FxSound Speakers (FxSound Audio Enhancer)"
ENHANCERS = ["FxSound"]


def wait_for(cond: Callable[[], bool], limit: float = 3.0) -> None:
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.005)


# --- a fake PyAudioWPatch ------------------------------------------------------------


class FakeStream:
    def __init__(self, callback: Callable[..., Any]) -> None:
        self.callback = callback
        self.active = True
        self.closed = False

    def is_active(self) -> bool:
        return self.active

    def stop_stream(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True

    def packet(self, x: npt.NDArray[np.float32]) -> tuple[Any, int]:
        return self.callback(x.astype(np.float32).tobytes(), len(x), None, 0)


class FakePyAudio:
    """The module and the PyAudio class in one; `module` goes to LoopbackReference."""

    def __init__(
        self,
        outputs: tuple[str, ...] = (REAL,),
        default: str = REAL,
        rate: int = 48000,
        channels: int = 2,
        raises: BaseException | None = None,
    ) -> None:
        self.outputs, self.default = outputs, default
        self.rate, self.channels, self.raises = rate, channels, raises
        self.streams: list[FakeStream] = []
        self.opens: list[dict[str, Any]] = []
        self.attempts = 0
        self.terminated = 0
        self.module = SimpleNamespace(
            PyAudio=self._pyaudio, paWASAPI=13, paFloat32=1, paContinue=0, paAbort=2
        )

    def _pyaudio(self) -> "FakePyAudio":
        self.attempts += 1
        if self.raises is not None:
            raise self.raises
        return self

    def _device(self, i: int, name: str, loop: bool) -> dict[str, Any]:
        return {
            "index": i,
            "name": name + (" [Loopback]" if loop else ""),
            "maxInputChannels": self.channels if loop else 0,
            "maxOutputChannels": 0 if loop else self.channels,
            "defaultSampleRate": float(self.rate),
            "isLoopbackDevice": loop,
        }

    def get_device_info_generator_by_host_api(
        self, *, host_api_type: int
    ) -> Iterator[dict[str, Any]]:
        assert host_api_type == 13
        for i, n in enumerate(self.outputs):
            yield self._device(i, n, False)
        for i, n in enumerate(self.outputs):
            yield self._device(100 + i, n, True)

    def get_default_wasapi_device(self, *, d_out: bool) -> dict[str, Any]:
        assert d_out
        return self._device(self.outputs.index(self.default), self.default, False)

    def get_wasapi_loopback_analogue_by_dict(
        self, info: dict[str, Any]
    ) -> dict[str, Any]:
        return self._device(100 + int(info["index"]), info["name"], True)

    def open(self, **kw: Any) -> FakeStream:
        self.opens.append(kw)
        stream = FakeStream(kw["stream_callback"])
        self.streams.append(stream)
        return stream

    def terminate(self) -> None:
        self.terminated += 1


def start(
    aec: EchoCanceller, fake: FakePyAudio, **kw: Any
) -> tuple[LoopbackReference, FakeStream]:
    opts: dict[str, Any] = {"check_s": 0.01, "retry_s": 0.05, "stale_s": 0.5}
    ref = LoopbackReference(aec, "", ENHANCERS, pa=fake.module, **(opts | kw))
    ref.start()
    wait_for(lambda: aec.loopback)
    return ref, fake.streams[0]


# --- the enhancer ---------------------------------------------------------------------


def enhance(x: npt.NDArray[np.float64], rate: int) -> npt.NDArray[np.float64]:
    """FxSound-style: pumping gain of about +-9 dB at 3 Hz, then tanh saturation."""
    gain = 10 ** (9 * np.sin(2 * np.pi * 3 * np.arange(len(x)) / rate) / 20)
    y = np.tanh(4.0 * x * gain / max(np.abs(x).max(), 1e-9))
    return y * 0.5


class FxScene:
    """`Scene` where the room echoes the enhanced voice, not the voice Snow rendered."""

    def __init__(self) -> None:
        base = Scene()
        self.utt2_s = base.utt2_s
        self.far24 = base.far24  # what Snow renders: before the enhancer
        fx24 = enhance(self.far24.astype(np.float64) / 32768.0, TR)
        self.fx24 = fx24.astype(np.float32)
        fx16 = to_pcm(soxr.resample(fx24, TR, SR) * 32768.0)
        echo = echo_of(fx16, 120, -26.0, 0)
        self.echo = echo
        self.n = len(echo) // FRAME * FRAME
        self.mic = to_pcm(echo + noise(len(echo), 0))[: self.n]

    def loopback_packets(self) -> npt.NDArray[np.float32]:
        """What the speakers play, as the 48 kHz stereo the sound card runs at."""
        x48 = soxr.resample(self.fx24, TR, 48000)
        return np.stack([x48, x48], axis=1).astype(np.float32)


def drive_loopback(aec: EchoCanceller, scene: FxScene, stream: FakeStream) -> Pcm:
    """The same clock as `drive`: 80 ms of speaker audio, then 80 ms of mic. Snow's
    own render blocks keep arriving too (the canceller must ignore them)."""
    frames = scene.n // FRAME
    packets = np.zeros((frames * 8 * 480, 2), dtype=np.float32)
    got = scene.loopback_packets()[: len(packets)]
    packets[: len(got)] = got
    far = np.zeros(frames * 4 * 480, dtype=np.float32)
    n = min(len(scene.far24), len(far))
    far[:n] = scene.far24[:n] / 32768.0
    out = np.empty(scene.n, dtype=np.int16)
    for f in range(frames):
        for b in range(8):  # 10 ms of 48 kHz audio each
            i = (f * 8 + b) * 480
            stream.packet(packets[i : i + 480])
        for b in range(4):
            j = (f * 4 + b) * 480
            aec.render(far[j : j + 480])
        out[f * FRAME : (f + 1) * FRAME] = aec.capture(
            scene.mic[f * FRAME : (f + 1) * FRAME]
        )
    return out


def test_fx_echo_is_cancelled_through_the_loopback_reference(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracer: the enhancer breaks the render reference; the loopback fixes it."""
    scene = FxScene()
    echo = to_pcm(scene.echo)

    render_aec = EchoCanceller(SR, TR)
    via_render = drive(render_aec, scene.far24, scene.mic)
    render_aec.close()
    render_run = longest_run_ms(via_render, scene.utt2_s)
    render_erle = erle_db(echo, via_render, scene.utt2_s + 1.0)

    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio()
    with caplog.at_level(logging.INFO, logger="snow.voice"):
        ref, stream = start(aec, fake)
        out = drive_loopback(aec, scene, stream)
    ref.close()
    aec.close()
    loop_run = longest_run_ms(out, scene.utt2_s)
    loop_erle = erle_db(echo, out, scene.utt2_s + 1.0)
    print(  # noqa: T201 - the measured numbers go in the SUMMARY
        f"render: run={render_run} ms erle={render_erle:.1f} dB; "
        f"loopback: run={loop_run} ms erle={loop_erle:.1f} dB"
    )

    assert "aec_reference=loopback device='Speakers (Realtek(R) Audio)" in caplog.text
    assert loop_run < MIN_RUN_MS
    assert loop_erle >= 20
    # the bug: the render reference leaves a pause-length run or 6 dB more echo
    assert render_run >= MIN_RUN_MS or loop_erle - render_erle >= 6


# --- switching, silence, bounds -------------------------------------------------------


class Counting:
    """Stands in for the APM: counts what each side was given."""

    def __init__(self) -> None:
        self.reverse: list[bytes] = []
        self.captured = 0

    def process_stream(self, frame: Any) -> None:
        self.captured += 1

    def process_reverse_stream(self, frame: Any) -> None:
        self.reverse.append(bytes(frame.data))


def counting_aec() -> tuple[EchoCanceller, Counting]:
    aec = EchoCanceller(SR, TR)
    apm = Counting()
    aec._apm = apm  # type: ignore[assignment]  # noqa: SLF001
    return aec, apm


LOUD = np.full(480, 0.3, dtype=np.float32)
MIC = np.zeros(FRAME, dtype=np.int16)


def test_switching_the_reference_moves_where_the_blocks_come_from() -> None:
    aec, apm = counting_aec()
    aec.render(LOUD)
    assert len(apm.reverse) == 2  # 480 samples = two 10 ms frames
    assert aec.reference_s > 0

    aec.use_loopback(True)
    assert aec.reference_s == 0.0
    aec.render(LOUD)  # ignored
    assert len(apm.reverse) == 2
    aec.loopback_block(np.full(240, 0.1, dtype=np.float32))
    aec.capture(MIC)
    assert len(apm.reverse) == 3  # the one queued frame, no zero fill
    assert apm.captured == FRAME // (SR // 100)

    aec.loopback_block(np.full(480, 0.1, dtype=np.float32))
    aec.use_loopback(False)
    assert aec.reference_s == 0.0
    aec.capture(MIC)
    assert len(apm.reverse) == 3  # the queue was dropped
    aec.render(LOUD)
    assert len(apm.reverse) == 5
    aec.close()


def test_loopback_blocks_are_ignored_until_the_loopback_is_on() -> None:
    aec, apm = counting_aec()
    aec.loopback_block(np.full(480, 0.1, dtype=np.float32))
    aec.use_loopback(True)
    aec.capture(MIC)
    assert len(apm.reverse) == FRAME // (SR // 100)  # silence only
    aec.close()


def test_an_empty_loopback_keeps_the_reference_flowing_as_zeros() -> None:
    aec, apm = counting_aec()
    aec.use_loopback(True)
    aec.capture(MIC)
    assert len(apm.reverse) == FRAME // (SR // 100) == 8
    assert all(f == bytes(2 * (TR // 100)) for f in apm.reverse)
    aec.close()


def test_a_stalled_mic_cannot_build_a_backlog_over_200_ms() -> None:
    aec, _ = counting_aec()
    aec.use_loopback(True)
    aec.loopback_block(np.full(TR, 0.1, dtype=np.float32))  # 1 s, no capture
    assert len(aec._queue) == 20  # noqa: SLF001
    aec.close()


def test_loopback_staleness_needs_audible_render_and_a_silent_loopback() -> None:
    aec, _ = counting_aec()
    aec.use_loopback(True)
    assert not aec.loopback_stale(0.05)
    aec.render(LOUD)
    time.sleep(0.1)
    aec.render(LOUD)
    assert aec.loopback_stale(0.05)
    aec.loopback_block(np.full(240, 0.1, dtype=np.float32))
    assert not aec.loopback_stale(0.05)
    aec.close()


# --- downmix and resample -------------------------------------------------------------


def tone(n: int, rate: int = 48000) -> npt.NDArray[np.float32]:
    return (0.5 * np.sin(2 * np.pi * 1000 * np.arange(n) / rate)).astype(np.float32)


def arrival(left: bool) -> npt.NDArray[np.float32]:
    """What reaches the canceller for half a second of a stereo tone."""
    aec = EchoCanceller(SR, TR)
    got: list[npt.NDArray[np.float32]] = []
    original = aec.loopback_block

    def spy(block: npt.NDArray[np.float32]) -> None:
        got.append(block)
        original(block)

    aec.loopback_block = spy  # type: ignore[method-assign]
    ref, stream = start(aec, FakePyAudio())
    t = tone(24000)
    pair = np.stack([t, np.zeros_like(t) if left else t], axis=1)
    for i in range(0, 24000, 480):
        stream.packet(pair[i : i + 480])
    ref.close()
    aec.close()
    return np.concatenate(got)


def rms(x: npt.NDArray[np.float32]) -> float:
    return float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))


def test_loopback_is_downmixed_to_mono_and_resampled_to_the_render_rate() -> None:
    both = arrival(left=False)
    assert abs(rms(both) - 0.5 / np.sqrt(2)) < 0.05 * 0.5 / np.sqrt(2)
    assert abs(len(both) - 12000) <= 480  # 24000 samples at 48 kHz, now at 24 kHz


def test_a_left_only_tone_arrives_at_half_amplitude() -> None:
    both, left = arrival(left=False), arrival(left=True)
    assert abs(rms(left) / rms(both) - 0.5) < 0.03  # a channel mean, not channel 0


def test_the_device_is_opened_with_its_own_rate_and_channels() -> None:
    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio(rate=44100, channels=6)
    ref, _ = start(aec, fake)
    ref.close()
    aec.close()
    (opened,) = fake.opens
    assert (opened["rate"], opened["channels"], opened["input"]) == (44100, 6, True)
    assert opened["frames_per_buffer"] == 441
    assert opened["input_device_index"] == 100  # the loopback analogue of output 0
    assert fake.terminated >= 1


# --- loss, liveness, unavailability ---------------------------------------------------


def test_a_lost_device_falls_back_to_render_and_is_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio()
    with caplog.at_level(logging.INFO, logger="snow.voice"):
        ref, stream = start(aec, fake)
        stream.active = False
        wait_for(lambda: not aec.loopback)
        assert "aec_reference=render reason=loopback_lost" in caplog.text
        wait_for(lambda: aec.loopback and len(fake.streams) == 2)
    assert len(fake.opens) == 2
    ref.close()
    aec.close()


def test_a_loopback_that_goes_silent_while_snow_speaks_falls_back_to_render() -> None:
    aec = EchoCanceller(SR, TR)
    ref, stream = start(aec, FakePyAudio(), retry_s=30.0, stale_s=0.05)
    assert stream.active
    end = time.monotonic() + 3
    while aec.loopback and time.monotonic() < end:
        aec.render(LOUD)  # Snow is audible, the loopback delivers nothing
        time.sleep(0.01)
    assert not aec.loopback
    ref.close()
    aec.close()


def test_an_unavailable_loopback_stays_on_render_and_says_so_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio(raises=OSError("no wasapi"))
    with caplog.at_level(logging.INFO, logger="snow.voice"):
        ref = LoopbackReference(
            aec, "", ENHANCERS, pa=fake.module, check_s=0.01, retry_s=0.02
        )
        ref.start()
        wait_for(lambda: fake.attempts >= 3)
        ref.close()
    aec.close()
    assert not aec.loopback
    assert caplog.text.count("aec_reference=render reason=OSError") == 1


def test_an_ambiguous_endpoint_never_guesses(caplog: pytest.LogCaptureFixture) -> None:
    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio(outputs=(FX, REAL, "Headphones (USB)"), default=FX)
    with caplog.at_level(logging.INFO, logger="snow.voice"):
        ref = LoopbackReference(
            aec, "", ENHANCERS, pa=fake.module, check_s=0.01, retry_s=0.02
        )
        ref.start()
        wait_for(lambda: fake.attempts >= 3)
        ref.close()
    aec.close()
    assert not aec.loopback and not fake.opens
    assert caplog.text.count("reason=no_endpoint") == 1
    assert fake.terminated >= 3  # every failed attempt let go of PortAudio


def test_a_missing_module_is_a_render_fallback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(__import__("sys").modules, "pyaudiowpatch", None)
    aec = EchoCanceller(SR, TR)
    with caplog.at_level(logging.INFO, logger="snow.voice"):
        ref = LoopbackReference(aec, "", ENHANCERS, retry_s=0.02)
        ref.start()
        wait_for(lambda: "reason=ImportError" in caplog.text)
        ref.close()
    aec.close()
    assert not aec.loopback


@pytest.mark.parametrize("nbytes", [9, 12])
def test_a_malformed_packet_aborts_the_stream_without_raising(
    nbytes: int, caplog: pytest.LogCaptureFixture
) -> None:
    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio()
    with caplog.at_level(logging.INFO, logger="snow.voice"):
        ref, stream = start(aec, fake, retry_s=30.0)
        for _ in range(2):
            result = stream.callback(bytes(nbytes), 3, None, 0)
            assert result == (None, fake.module.paAbort)
        wait_for(lambda: not aec.loopback)
        ref.close()
    aec.close()
    assert caplog.text.count("aec_loopback_failed kind=ValueError") == 1


# --- picking the endpoint -------------------------------------------------------------


@pytest.mark.parametrize(
    ("outputs", "default", "device", "expected"),
    [
        ([REAL, "HDMI"], REAL, "", REAL),
        ([FX, REAL], FX, "", REAL),
        ([FX, REAL, "HDMI"], FX, "", None),
        ([FX], FX, "", None),
        ([FX, REAL, "HDMI"], FX, "hdmi", "HDMI"),
        ([FX, REAL], REAL, "REALTEK", REAL),
        ([FX, REAL], REAL, "no such speaker", None),
    ],
)
def test_pick_endpoint(
    outputs: list[str], default: str, device: str, expected: str | None
) -> None:
    assert pick_endpoint(outputs, default, device, ENHANCERS) == expected


def test_is_enhancer_is_a_case_insensitive_substring() -> None:
    assert is_enhancer(FX, ["fxsound"])
    assert not is_enhancer(REAL, ENHANCERS)
    assert not is_enhancer(FX, [])
    assert not is_enhancer(FX, [""])


# --- memory only ----------------------------------------------------------------------


def test_a_whole_loopback_session_writes_nothing_and_logs_no_audio(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    writes: list[str] = []
    real_open = builtins.open

    def spy_open(file: Any, mode: str = "r", *a: Any, **kw: Any) -> Any:
        if any(c in mode for c in "wax+"):
            writes.append(f"open {file!r} {mode}")
        return real_open(file, mode, *a, **kw)

    real_wave = wave.open

    def spy_wave(f: Any, mode: str | None = None) -> Any:
        if mode and mode.startswith("w"):
            writes.append("wave.open w")
        return real_wave(f, mode)  # type: ignore[call-overload]

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(wave, "open", spy_wave)
    monkeypatch.setattr(
        "soundfile.write", lambda *a, **k: writes.append("soundfile.write")
    )

    aec = EchoCanceller(SR, TR)
    fake = FakePyAudio()
    with caplog.at_level(logging.DEBUG, logger="snow.voice"):
        ref, stream = start(aec, fake)
        packet = np.stack([tone(480)] * 2, axis=1)
        for _ in range(100):  # 1 s
            stream.packet(packet)
        for _ in range(3):
            aec.capture(MIC)
        stream.active = False
        wait_for(lambda: not aec.loopback)
        ref.close()
    aec.close()

    assert writes == []
    mine = [r for r in caplog.records if r.name == "snow.voice"]
    assert mine
    assert all(r.getMessage().startswith("aec_") for r in mine)
    assert all(len(r.getMessage()) < 200 for r in mine)
