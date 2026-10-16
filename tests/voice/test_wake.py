"""The wake gate on fixtures, and the developer WAV input (D-07), in process."""

import httpx2

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.contracts.events import TranscriptFinal
from snow.voice.config import VoiceConfig
from snow.voice.devinput import inject, play
from snow.voice.sources import read_wav
from snow.voice.stt_groq import GroqStt
from snow.voice.wake import WakeGate
from tests.voice.conftest import AUDIO, FakeGroq, FakeHub

CFG = load_config("voice.toml", VoiceConfig)


def hits(name: str) -> list[float]:
    w = CFG.wake
    gate = WakeGate(
        w.model, w.threshold, w.patience_frames, w.preroll_frames, w.refractory_s
    )
    pcm = read_wav(AUDIO / f"{name}.wav", CFG.audio.sample_rate)
    step = CFG.audio.frame_samples
    scores = (gate.process(pcm[i : i + step]) for i in range(0, len(pcm) - step, step))
    return [h.score for h in scores if h is not None]


def test_wake_fixture_fires_once_above_threshold(wake_models: None) -> None:
    scores = hits("wake_only")
    assert len(scores) == 1
    assert scores[0] >= CFG.wake.threshold


def test_tv_negative_never_fires(wake_models: None) -> None:
    assert hits("tv_negative") == []


async def test_inject_wav_drives_the_pipeline_as_dev(
    groq: FakeGroq, wake_models: None
) -> None:
    groq.text = "Hey Jarvis, what is the capital of France?"
    stt = GroqStt(
        CFG.stt.groq,
        lambda _n: Secret("gsk_test_key_not_real"),
        transport=httpx2.MockTransport(groq.handler),
    )
    hub = FakeHub()
    pipeline = inject(AUDIO / "wake_cmd_gap150.wav", CFG, hub, stt)
    hub.pipeline = pipeline  # a brain that answers, so the replay hears the end
    assert await play(pipeline, limit_s=60)
    assert hub.types().count("wake.detected") == 1
    finals = [e for e in hub.events if isinstance(e, TranscriptFinal)]
    assert [f.text for f in finals] == ["what is the capital of France?"]
    assert {e.source for e in hub.events} == {"dev"}
