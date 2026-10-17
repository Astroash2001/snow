"""Real-hardware latency (SPCH-04): VAD stop to the first sample leaving the speaker.

Run by hand on the laptop, with headphones plugged in and the keys stored:

    uv run pytest -m hardware tests/hardware/test_latency.py -x -q -s

It drives real turns through the whole stack in one process: command recordings injected
as the microphone, the real wake gate and turn engine, Groq speech-to-text, the brain's
fast chain over the network, Pocket TTS, and the real default output device (it speaks
out loud). Nothing is recorded or written. Numbers come from the `turn.timing` events.
"""

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from snow.brain.worker import BrainWorker
from snow.config.secrets import get_secret
from snow.config.settings import load_config, repo_root
from snow.contracts.events import (
    AckRequested,
    Event,
    ReplyDelta,
    ReplyFinal,
    TranscriptFinal,
    TurnCancelled,
    TurnTiming,
)
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import VoicePipeline, build_pipeline
from snow.voice.sources import Frame, OnFrame, read_wav
from snow.voice.stt_groq import GroqStt
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.pocket import PocketEngine
from tests.conftest import SnowDirs

pytestmark = pytest.mark.hardware

AUDIO = repo_root() / "tests" / "fixtures" / "audio"
COMMANDS = ["wake_cmd_gap0", "wake_cmd_gap150", "wake_cmd_gap600"]
TURNS = 20  # the budgeted run (Groq primary); the comparison run uses 10
P50_S, P95_S = 1.0, 1.6
GAP_S = 1.0  # silence after each command, as a user would pause
REPLY_WAIT_S = 40.0
FRAME = 1280
RATE = 16000


class Loopback:
    """Stands in for the hub: voice events reach the brain, brain events reach voice."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.pipeline: VoicePipeline | None = None
        self.brain: BrainWorker | None = None
        self._tasks: set[asyncio.Future[None]] = set()

    async def publish(self, event: Event) -> None:  # voice -> brain
        self.events.append(event)
        if isinstance(event, TranscriptFinal | AckRequested | TurnCancelled):
            assert self.brain is not None
            task = asyncio.ensure_future(self.brain.on_event(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def from_brain(self, event: Event) -> None:  # brain -> voice
        self.events.append(event)
        if isinstance(event, ReplyDelta | ReplyFinal):
            assert self.pipeline is not None
            await self.pipeline.on_hub_event(event)

    def timings(self) -> list[TurnTiming]:
        return [e for e in self.events if isinstance(e, TurnTiming)]


class CommandSource:
    """The microphone: each recording in real time, then a pause, then it waits for
    Snow's reply to be heard (its `turn.timing` arrives) before the next one."""

    def __init__(self, clips: list[Path], answered: Callable[[], int]) -> None:
        self._clips = clips
        self._answered = answered
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_open(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def open(self, on_frame: OnFrame) -> None:
        def feed(audio: Frame) -> None:
            for start in range(0, len(audio) - FRAME + 1, FRAME):
                if self._stop.is_set():
                    return
                on_frame(audio[start : start + FRAME])
                time.sleep(FRAME / RATE)

        def run() -> None:
            silence = np.zeros(int(GAP_S * RATE), dtype=np.int16)
            for i, clip in enumerate(self._clips):
                feed(np.concatenate([read_wav(clip, RATE), silence]))
                deadline = time.monotonic() + REPLY_WAIT_S
                while self._answered() <= i and time.monotonic() < deadline:
                    if self._stop.is_set():
                        return
                    time.sleep(0.02)
                feed(silence)  # the user listens to the end of the reply

        self._thread = threading.Thread(target=run, name="snow-latency", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


@dataclass
class Result:
    totals: list[float] = field(default_factory=list[float])  # VAD stop -> first sample
    stages: dict[str, list[float]] = field(default_factory=dict[str, list[float]])

    def p(self, q: float) -> float:
        return float(np.percentile(self.totals, q))

    def report(self, label: str) -> str:
        lines = [
            f"{label}: n={len(self.totals)} "
            f"p50={self.p(50):.3f}s p95={self.p(95):.3f}s "
            f"min={min(self.totals):.3f}s max={max(self.totals):.3f}s"
        ]
        for name, values in self.stages.items():
            lines.append(f"    {name}: median {np.median(values):.3f}s")
        return "\n".join(lines)


def fast_first(models_toml: str, model: str) -> str:
    """The same models.toml with `model` moved to the front of the fast chain."""
    lines = models_toml.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "[roles.fast]")
    opened = next(
        i for i in range(start, len(lines)) if lines[i].strip().startswith("chain = [")
    )
    closed = next(i for i in range(opened + 1, len(lines)) if lines[i].strip() == "]")
    groups: list[list[str]] = []
    current: list[str] = []
    for ln in lines[opened + 1 : closed]:  # comments stay with the entry below them
        current.append(ln)
        if ln.lstrip().startswith("{"):
            groups.append(current)
            current = []
    first = next(g for g in groups if any(f'model = "{model}"' in ln for ln in g))
    groups.remove(first)
    groups.insert(0, first)
    kept = [ln for g in groups for ln in g]
    return "\n".join([*lines[: opened + 1], *kept, *lines[closed:]]) + "\n"


async def run_turns(turns: int) -> Result:
    """`turns` spoken commands through the running stack; the result is per turn."""
    cfg = load_config("voice.toml", VoiceConfig)
    tts_cfg = load_config("tts.toml", TtsConfig)
    loop = Loopback()
    loop.brain = BrainWorker(loop.from_brain)
    clips = [AUDIO / f"{COMMANDS[i % len(COMMANDS)]}.wav" for i in range(turns)]
    source = CommandSource(clips, lambda: len(loop.timings()))
    pipeline = build_pipeline(
        cfg,
        loop,
        source,
        GroqStt(cfg.stt.groq, get_secret),
        tts={"pocket_tts": PocketEngine(tts_cfg.engines.pocket_tts)},
        tts_cfg=tts_cfg,
    )
    loop.pipeline = pipeline
    await pipeline.start()
    try:
        async with asyncio.timeout(turns * (REPLY_WAIT_S + 10)):
            await pipeline.wait_done()
    finally:
        await pipeline.stop()
    assert pipeline._playout is not None, "the voice never loaded"  # noqa: SLF001

    result = Result()
    stage_names = ["stt", "llm first token", "tts first audio", "device"]
    for t in loop.timings():
        marks = [
            t.vad_stop_ns,
            t.stt_final_ns,
            t.llm_first_token_ns,
            t.tts_first_audio_ns,
            t.audio_out_first_ns,
        ]
        if None in marks:
            continue
        ns = [m for m in marks if m is not None]
        result.totals.append((ns[-1] - ns[0]) / 1e9)
        for name, (a, b) in zip(
            stage_names, zip(ns, ns[1:], strict=False), strict=True
        ):
            result.stages.setdefault(name, []).append((b - a) / 1e9)
    return result


def require_keys() -> None:
    for name in ("groq", "experiential"):
        if get_secret(name) is None:
            pytest.skip(f"no {name} key in Credential Manager (run `snow setup`)")


async def test_vad_stop_to_first_audio_and_the_fast_primary_comparison(
    snow_dirs: SnowDirs, capsys: pytest.CaptureFixture[str]
) -> None:
    require_keys()
    models = snow_dirs.config / "models.toml"
    original = models.read_text(encoding="utf-8")

    groq = await run_turns(TURNS)  # config as shipped: Groq gpt-oss-120b first
    models.write_text(fast_first(original, "deepseek-v4-flash"), encoding="utf-8")
    experiential = await run_turns(10)  # Experiential deepseek-v4-flash first

    assert groq.totals and experiential.totals, "no turn produced a full turn.timing"
    with capsys.disabled():
        print()  # noqa: T201 - the measurements are the point of this test
        print(groq.report("fast primary groq openai/gpt-oss-120b"))  # noqa: T201
        print(experiential.report("fast primary experiential deepseek-v4-flash"))  # noqa: T201
        print(  # noqa: T201
            f"time to first audio, median: groq {np.median(groq.totals):.3f}s, "
            f"experiential {np.median(experiential.totals):.3f}s"
        )

    assert len(groq.totals) >= TURNS - 2, "too many turns lost to compare"
    assert groq.p(50) <= P50_S, f"p50 {groq.p(50):.3f}s over {P50_S}s"
    assert groq.p(95) <= P95_S, f"p95 {groq.p(95):.3f}s over {P95_S}s"
