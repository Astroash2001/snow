"""Voice fixtures: WAV loader, FakeHub, a fail-closed Groq network, a pipeline runner.

openai 3.x runs on httpx2, which respx cannot patch, so Groq is faked with an
`httpx2.MockTransport` injected into GroqStt (the 01-03 mechanism). Any request to an
unrouted host or path is a violation and fails the test at teardown, so no test can
send audio to the real Groq API.
"""

import asyncio
import io
import wave
from collections.abc import Awaitable, Callable, Iterator
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import numpy as np
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.contracts.events import (
    Event,
    HealthSubsystem,
    ReplyFinal,
    SttStatus,
    TranscriptFinal,
)
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import LocalSource, VoicePipeline
from snow.voice.sources import FileSource, Frame, OnFrame
from snow.voice.stt_groq import GroqStt
from snow.voice.tts.config import PolishConfig, TtsConfig
from snow.voice.turn import TurnEngine
from snow.voice.vad import EndOfTurn, VadDetector
from snow.voice.wake import WakeGate, WakeHit, model_files

SR = 16000
AUDIO = Path(__file__).resolve().parents[1] / "fixtures" / "audio"
HEY_SNOW = Path(__file__).resolve().parents[2] / "models" / "wakeword" / "hey_snow.onnx"


def voice_cfg() -> VoiceConfig:
    """voice.toml waking on the pretrained hey_jarvis stand-in: the fixtures say
    "Hey Jarvis", and the trained hey_snow model is gitignored (CI never has it)."""
    cfg = load_config("voice.toml", VoiceConfig)
    wake = cfg.wake.model_copy(update={"model": "hey_jarvis", "model_sha256": ""})
    return cfg.model_copy(update={"wake": wake})


CFG = voice_cfg()
GROQ_PATH = "/openai/v1/audio/transcriptions"


class FakeHub:
    def __init__(self) -> None:
        self.events: list[Event] = []  # without health rows, so flow tests stay exact
        self.health: list[HealthSubsystem] = []
        self.stt: list[SttStatus] = []  # source changes, also kept out of `events`
        self.pipeline: VoicePipeline | None = None  # set to answer every transcript

    async def publish(self, event: Event) -> None:
        if isinstance(event, HealthSubsystem):
            self.health.append(event)
            return
        if isinstance(event, SttStatus):
            self.stt.append(event)
            return
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


def verbose_segment(
    text: str, no_speech_prob: float, avg_logprob: float
) -> dict[str, Any]:
    """One segment of a Groq verbose_json answer (all TranscriptionSegment fields)."""
    return {
        "id": 0,
        "seek": 0,
        "start": 0.0,
        "end": 1.0,
        "text": text,
        "tokens": [1, 2],
        "temperature": 0.0,
        "avg_logprob": avg_logprob,
        "compression_ratio": 1.0,
        "no_speech_prob": no_speech_prob,
    }


@dataclass
class FakeGroq:
    """Records uploads; replies with `text` as the transcription."""

    text: str = ""
    texts: list[str] = field(default_factory=list[str])  # per request, then `text`
    fail_with: int | None = None  # answer every request with this HTTP status
    retry_after: str | None = None
    no_speech_prob: float = 0.01  # confident speech unless a test says otherwise
    avg_logprob: float = -0.2
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    violations: list[str] = field(default_factory=list[str])

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if (
            request.method == "POST"
            and request.url.host == "api.groq.com"
            and request.url.path == GROQ_PATH
        ):
            self.requests.append(request)
            if self.fail_with is not None:
                headers = {"retry-after": self.retry_after} if self.retry_after else {}
                return httpx2.Response(
                    self.fail_with, json={"error": {"message": "no"}}, headers=headers
                )
            text = self.texts.pop(0) if self.texts else self.text
            return httpx2.Response(
                200,
                json={
                    "text": text,
                    "language": "en",
                    "duration": 1.0,
                    "segments": [
                        verbose_segment(text, self.no_speech_prob, self.avg_logprob)
                    ],
                },
            )
        self.violations.append(f"{request.method} {request.url}")
        return httpx2.Response(599)

    def uploaded_seconds(self, index: int = 0) -> float:
        body = self.requests[index].content
        start = body.index(b"RIFF")  # the WAV part inside the multipart body
        with wave.open(io.BytesIO(body[start:]), "rb") as w:
            return w.getnframes() / w.getframerate()


@pytest.fixture(autouse=True)
def no_device_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The voice keeps its own rate in tests: no real audio device is ever queried."""
    monkeypatch.setattr("snow.voice.pipeline.device_rate", lambda: None)


def polish_off() -> PolishConfig:
    """Every polish part off (the device-rate resample is not one): exact maths."""
    return PolishConfig(
        trim_edges=False,
        compressor=False,
        makeup_db=0.0,
        pace=1.0,
        sentence_pause_ms=0,
        comma_pause_ms=0,
        eq=False,
        warmth_db=3.0,
        presence_db=2.0,
        reverb_wet=0.0,
    )


def tts_cfg_polish_off(cfg: TtsConfig) -> TtsConfig:
    return cfg.model_copy(update={"polish": polish_off()})


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
    source: FileSource


RunFixture = Callable[..., Awaitable[Run]]
SourceFactory = Callable[[Path], FileSource]


@pytest.fixture
def run_fixture(groq: FakeGroq, wake_models: None) -> RunFixture:
    async def run(
        name: str,
        text: str,
        *,
        replies: bool = False,
        source_factory: SourceFactory = FileSource,
        local: LocalSource | None = None,
        configured_wake: bool = False,
    ) -> Run:
        """`replies`: the hub answers every transcript, so the next turn is heard.
        `configured_wake`: wake on voice.toml's own model instead of the stand-in."""
        groq.text = text
        cfg = voice_cfg()
        hub = FakeHub()
        w = load_config("voice.toml", VoiceConfig).wake if configured_wake else cfg.wake
        wake = WakeGate(
            w.model,
            w.threshold,
            w.patience_frames,
            w.preroll_frames,
            w.refractory_s,
            model_sha256=w.model_sha256,
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
        source = source_factory(AUDIO / f"{name}.wav")
        pipeline = VoicePipeline(cfg, hub, source, wake, engine, stt, local=local)
        if replies:
            hub.pipeline = pipeline
            source.hold = lambda: pipeline.waiting_reply
        await pipeline.start()
        await pipeline.wait_done()
        await pipeline.stop()
        return Run(hub, hits, engine, source)

    return run


class StubSource:
    """A microphone that only records what the pipeline asked of it."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.is_open = False

    def open(self, on_frame: OnFrame) -> None:
        self.calls.append("open")
        self.is_open = True

    def close(self) -> None:
        self.calls.append("close")
        self.is_open = False


SAID = "Jarvis what is the capital of France"


class FakeLocalStt:
    """Hears one word per 0.4 s of audio; records when it was asked for partials."""

    def __init__(self) -> None:
        self.words = SAID.split()
        self.fed = 0
        self.turns = 0
        self.cancelled = 0
        self.finished = False
        self.fed_after_finish = 0
        self.asked_at: list[int] = []  # samples fed so far at each partial() call
        self._seen = ""

    def start_turn(self) -> None:
        self.turns += 1
        self.fed, self.finished, self._seen = 0, False, ""

    def feed(self, frame: Frame) -> None:
        self.fed_after_finish += self.finished
        self.fed += len(frame)

    def partial(self) -> str | None:
        self.asked_at.append(self.fed)
        text = " ".join(self.words[: self.fed // 6400])
        if text == self._seen:
            return None
        self._seen = text
        return text

    def finish(self) -> "Future[str]":
        self.finished = True
        done: Future[str] = Future()
        done.set_result(SAID)
        return done

    def cancel(self) -> None:
        self.cancelled += 1


async def until(cond: Callable[[], bool], limit: float = 5.0) -> None:
    async with asyncio.timeout(limit):
        while not cond():  # noqa: ASYNC110 - polling a flag set by another task
            await asyncio.sleep(0.01)


def make_pipeline(hub: Any, source: Any, key: bool = True) -> VoicePipeline:
    w = CFG.wake
    wake = WakeGate(
        w.model, w.threshold, w.patience_frames, w.preroll_frames, w.refractory_s
    )
    engine = TurnEngine(
        CFG.turn, VadDetector(), EndOfTurn(), conversation=CFG.conversation
    )
    stt = GroqStt(
        CFG.stt.groq,
        lambda _n: Secret("gsk_test_key_not_real") if key else None,
        transport=httpx2.MockTransport(lambda _r: httpx2.Response(599)),
    )
    return VoicePipeline(CFG, hub, source, wake, engine, stt, "voice")
