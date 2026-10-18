"""Real-hardware echo cancellation (VOIC-06): Snow on laptop speakers, mic open.

Run by hand on the laptop, speakers on (no headphones) at normal volume, room quiet.
Quit or mute Snow first, so its worker neither hears this test nor answers it:

    uv run pytest -m hardware tests/hardware/test_echo_cancel.py -x -q -s

It plays fixture speech out loud through the default output while the real microphone
listens, with the real canceller in between. Nothing is recorded or written: every frame
stays in Python lists in memory. Report in the SUMMARY, for both variants (FxSound
Speakers as the default output, then FxSound effects off or another output device):
the printed device latencies, the ERLE, the cold-start residual and both verdicts.
"""

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pytest

from snow.config.settings import load_config
from snow.voice.aec import EchoCanceller
from snow.voice.config import VoiceConfig
from snow.voice.playout import Playout
from snow.voice.sources import Frame, MicSource
from snow.voice.tts.config import TtsConfig
from tests.voice.test_echo_cancel import far_of, longest_run_ms

pytestmark = pytest.mark.hardware

CFG = load_config("voice.toml", VoiceConfig)
TTS = load_config("tts.toml", TtsConfig)
RATE, TTS_RATE = CFG.audio.sample_rate, 24000
FRAME_S = CFG.audio.frame_samples / RATE
ERLE_MIN_DB = 15.0  # looser than the synthetic 20 dB: a real room, FxSound, a driver
WARM_S = 3.0


def db(x: npt.NDArray[np.int16]) -> float:
    rms = float(np.sqrt(np.mean(np.square(x.astype(np.float64))))) / 32768.0
    return 20 * float(np.log10(max(rms, 1e-9)))


@dataclass
class Rig:
    """A real canceller between a real playout and a real microphone."""

    raw: list[Frame] = field(default_factory=list[Frame])
    clean: list[Frame] = field(default_factory=list[Frame])
    drained: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self.aec = EchoCanceller(RATE, TTS_RATE)
        self.out = Playout(
            TTS_RATE,
            TTS.playout,
            on_drained=self.drained.set,
            on_render=self.aec.render,
        )
        self.mic = MicSource(CFG.audio.input_device, RATE, CFG.audio.frame_samples)

    def on_frame(self, frame: Frame) -> None:
        self.raw.append(frame)
        self.clean.append(self.aec.capture(frame))

    def play(self, seconds: float) -> int:
        """Start `seconds` of fixture speech; returns the frame index it starts at."""
        names = ("phrase_thats_all", "tone_calm", "phrase_go_to_sleep")
        speech = far_of(*names, gap_s=0.4)[0].astype(np.float32) / 32768.0
        speech = np.tile(speech, int(seconds * TTS_RATE // len(speech)) + 1)
        speech = speech[: int(seconds * TTS_RATE)]
        self.drained.clear()
        start = len(self.raw)
        self.out.start_utterance()
        self.out.push(speech)
        self.out.end_utterance()
        return start

    def close(self) -> None:
        self.mic.close()
        self.out.close()
        self.aec.close()


@pytest.fixture
def rig() -> Iterator[Rig]:
    r = Rig()
    r.mic.open(r.on_frame)
    time.sleep(1.0)  # the microphone settles before anything plays
    yield r
    r.close()


def pcm(frames: list[Frame], a: int, b: int | None = None) -> npt.NDArray[np.int16]:
    return np.concatenate(frames[a:b])


def test_snow_alone_on_speakers_is_not_heard_by_itself(rig: Rig) -> None:
    start = rig.play(12.0)
    time.sleep(0.5)  # the output stream exists once the first utterance starts
    out_s, in_s = rig.out._stream, rig.mic._stream  # noqa: SLF001
    print(
        f"\nstream latency: output {getattr(out_s, 'latency', '?')} s, "
        f"input {getattr(in_s, 'latency', '?')} s (query values, real path longer)"
    )
    assert rig.drained.wait(30), "the playback never finished"
    end = len(rig.raw)

    per_s = int(1 / FRAME_S)
    for i in range(start, end - per_s, per_s):
        raw, clean = pcm(rig.raw, i, i + per_s), pcm(rig.clean, i, i + per_s)
        print(
            f"  t={i - start:3d}s raw {db(raw):6.1f} dBFS  clean {db(clean):6.1f} dBFS"
        )

    cold = longest_run_ms(pcm(rig.clean, start), 0.0, WARM_S)
    print(f"cold-start residual (first {WARM_S:.0f} s), longest VAD run: {cold} ms")

    warm = start + int(WARM_S / FRAME_S)
    erle = db(pcm(rig.raw, warm, end)) - db(pcm(rig.clean, warm, end))
    run = longest_run_ms(pcm(rig.clean, warm, end))
    print(f"ERLE after {WARM_S:.0f} s: {erle:.1f} dB; longest VAD run: {run} ms")
    assert erle >= ERLE_MIN_DB, (
        f"ERLE {erle:.1f} dB < {ERLE_MIN_DB} dB. Measure the real loopback delay, then "
        "retry with FxSound effects off or another output (research pitfalls 3 and 4)"
    )
    assert run < CFG.turn.barge_in_min_ms, f"residual run {run} ms barges in on Snow"


def test_talking_over_snow_on_speakers_still_gets_through(rig: Rig) -> None:
    rig.play(10.0)
    time.sleep(WARM_S)  # let the canceller converge on Snow's voice
    start = len(rig.raw)
    print("\n>>> SAY A SENTENCE OVER SNOW NOW (about 4 seconds) <<<")
    time.sleep(6.0)
    run = longest_run_ms(pcm(rig.clean, start))
    print(f"longest VAD run on the cleaned mic while you talked: {run} ms")
    assert run >= CFG.turn.barge_in_min_ms, (
        "your voice did not get through the canceller"
    )
    rig.drained.wait(10)
