"""Live words while the user speaks (VOIC-08, D-38): cadence, wake strip, turn end."""

import re
from concurrent.futures import Future
from functools import partial

import pytest

from snow.config.settings import load_config
from snow.contracts.events import TranscriptFinal, TranscriptPartial
from snow.voice.config import VoiceConfig
from snow.voice.sources import FileSource, Frame
from snow.voice.stt_local import LocalStt
from tests.voice.conftest import SR, RunFixture

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


async def test_partials_grow_with_the_turn_and_stop_at_its_end(
    run_fixture: RunFixture,
) -> None:
    local = FakeLocalStt()
    run = await run_fixture(
        "wake_cmd_gap150", "Hey Jarvis, what is the capital of France?", local=local
    )
    types = run.hub.types()
    partials = [e for e in run.hub.events if isinstance(e, TranscriptPartial)]
    final = next(e for e in run.hub.events if isinstance(e, TranscriptFinal))
    assert len(partials) >= 2
    assert all(
        types.index("transcript.final") > i
        for i, t in enumerate(types)
        if t == "transcript.partial"
    )
    assert all(p.turn_id == final.turn_id for p in partials)
    # The wake word is stripped, and each partial extends the one before it.
    assert not any(p.text.lower().startswith("jarvis") for p in partials)
    texts = [p.text for p in partials]
    assert all(
        b.startswith(a) and b != a for a, b in zip(texts, texts[1:], strict=False)
    )
    # Cadence is measured in audio time: no two looks closer than 250 ms.
    gaps = [b - a for a, b in zip(local.asked_at, local.asked_at[1:], strict=False)]
    assert gaps and min(gaps) >= SR // 4
    # Nothing is fed to the local model after the turn ended, and it ran exactly once.
    assert local.turns == 1
    assert local.fed_after_finish == 0


async def test_wake_alone_drops_the_local_turn_without_partials(
    run_fixture: RunFixture,
) -> None:
    local = FakeLocalStt()
    run = await run_fixture("wake_only", "Hey Jarvis.", local=local)
    assert local.cancelled == 1
    assert not local.finished
    assert "transcript.partial" not in run.hub.types()


async def test_no_local_model_means_no_partials(run_fixture: RunFixture) -> None:
    run = await run_fixture(
        "wake_cmd_gap150", "Hey Jarvis, what is the capital of France?"
    )
    assert "transcript.partial" not in run.hub.types()
    assert "transcript.final" in run.hub.types()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower()))


@pytest.mark.slow
async def test_real_moonshine_shows_words_before_the_final(
    run_fixture: RunFixture,
) -> None:
    cfg = load_config("voice.toml", VoiceConfig)
    local = LocalStt(cfg.stt.local)
    try:
        run = await run_fixture(
            "wake_cmd_gap150",
            "Hey Jarvis, what is the capital of France?",
            source_factory=partial(FileSource, realtime=True),
            local=local,
        )
    finally:
        local.close()
    partials = [e for e in run.hub.events if isinstance(e, TranscriptPartial)]
    final = next(e for e in run.hub.events if isinstance(e, TranscriptFinal))
    assert len(partials) >= 2
    last = _words(partials[-1].text)
    assert len(last & _words(final.text)) * 2 >= len(last)
