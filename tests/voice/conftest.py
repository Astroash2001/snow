"""Voice fixtures: WAV loader, FakeHub, a fail-closed Groq network, a pipeline runner.

openai 3.x runs on httpx2, which respx cannot patch, so Groq is faked with an
`httpx2.MockTransport` injected into GroqStt (the 01-03 mechanism). Any request to an
unrouted host or path is a violation and fails the test at teardown, so no test can
send audio to the real Groq API.
"""

import io
import wave
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx2
import numpy as np
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.contracts.events import Event, ReplyFinal, TranscriptFinal
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import VoicePipeline
from snow.voice.sources import FileSource
from snow.voice.stt_groq import GroqStt
from snow.voice.turn import TurnEngine
from snow.voice.vad import EndOfTurn, VadDetector
from snow.voice.wake import WakeGate, WakeHit, model_files

SR = 16000
AUDIO = Path(__file__).resolve().parents[1] / "fixtures" / "audio"
GROQ_PATH = "/openai/v1/audio/transcriptions"


class FakeHub:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.pipeline: VoicePipeline | None = None  # set to answer every transcript

    async def publish(self, event: Event) -> None:
        self.events.append(event)
        if self.pipeline is not None and isinstance(event, TranscriptFinal):
            await self.pipeline.on_hub_event(reply_to(event))

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def reply_to(heard: TranscriptFinal) -> ReplyFinal:
    return ReplyFinal(
        ts_ns=0,
        source="brain",
        turn_id=heard.turn_id,
        text="ok",
        emotion="neutral",
        big_moment=False,
        reply_source="llm",
    )


@dataclass
class FakeGroq:
    """Records uploads; replies with `text` as the transcription."""

    text: str = ""
    texts: list[str] = field(default_factory=list[str])  # per request, then `text`
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    violations: list[str] = field(default_factory=list[str])

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if (
            request.method == "POST"
            and request.url.host == "api.groq.com"
            and request.url.path == GROQ_PATH
        ):
            self.requests.append(request)
            text = self.texts.pop(0) if self.texts else self.text
            return httpx2.Response(200, json={"text": text})
        self.violations.append(f"{request.method} {request.url}")
        return httpx2.Response(599)

    def uploaded_seconds(self, index: int = 0) -> float:
        body = self.requests[index].content
        start = body.index(b"RIFF")  # the WAV part inside the multipart body
        with wave.open(io.BytesIO(body[start:]), "rb") as w:
            return w.getnframes() / w.getframerate()


@pytest.fixture
def groq() -> Iterator[FakeGroq]:
    fake = FakeGroq()
    yield fake
    assert not fake.violations, f"requests to unrouted hosts: {fake.violations}"


@pytest.fixture(scope="session")
def wake_models() -> None:
    model_files("hey_jarvis")  # downloads the pretrained stand-in once (D-41)


def speech_end_s(name: str) -> float:
    """Where the last audible sample of a fixture is, in seconds."""
    with wave.open(str(AUDIO / f"{name}.wav"), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return float(np.flatnonzero(np.abs(pcm) > 300)[-1]) / SR


@dataclass
class Run:
    hub: FakeHub
    hits: list[WakeHit]
    engine: TurnEngine


RunFixture = Callable[..., Awaitable[Run]]


@pytest.fixture
def run_fixture(groq: FakeGroq, wake_models: None) -> RunFixture:
    async def run(name: str, text: str, *, replies: bool = False) -> Run:
        """`replies`: the hub answers every transcript, so the next turn is heard."""
        groq.text = text
        cfg = load_config("voice.toml", VoiceConfig)
        hub = FakeHub()
        w = cfg.wake
        wake = WakeGate(
            w.model, w.threshold, w.patience_frames, w.preroll_frames, w.refractory_s
        )
        engine = TurnEngine(
            cfg.turn, VadDetector(), EndOfTurn(), conversation=cfg.conversation
        )
        hits: list[WakeHit] = []
        on_wake = engine.on_wake

        def spy(hit: WakeHit) -> None:
            hits.append(hit)
            on_wake(hit)

        engine.on_wake = spy  # type: ignore[method-assign]
        stt = GroqStt(
            cfg.stt.groq,
            lambda _name: Secret("gsk_test_key_not_real"),
            transport=httpx2.MockTransport(groq.handler),
        )
        source = FileSource(AUDIO / f"{name}.wav")
        pipeline = VoicePipeline(cfg, hub, source, wake, engine, stt)
        if replies:
            hub.pipeline = pipeline
            source.hold = lambda: pipeline.waiting_reply
        await pipeline.start()
        await pipeline.wait_done()
        await pipeline.stop()
        return Run(hub, hits, engine)

    return run
