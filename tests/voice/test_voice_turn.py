"""End to end on the plan 01-05 fixtures with real wake, VAD and Smart Turn (CPU)."""

import pytest

from snow.contracts.events import TranscriptFinal
from tests.voice.conftest import SR, FakeGroq, RunFixture, speech_end_s

WAKE_TEXT = "Hey Jarvis, what is the capital of France?"


@pytest.mark.parametrize(
    "name", ["wake_cmd_gap0", "wake_cmd_gap150", "wake_cmd_gap600"]
)
async def test_wake_plus_command_becomes_one_stripped_transcript(
    name: str, groq: FakeGroq, run_fixture: RunFixture
) -> None:
    run = await run_fixture(name, WAKE_TEXT)
    assert run.hub.types()[:3] == [
        "wake.detected",
        "conversation.started",
        "presence.state",
    ]
    finals = [e for e in run.hub.events if isinstance(e, TranscriptFinal)]
    assert len(finals) == 1
    assert finals[0].text == "what is the capital of France?"
    assert finals[0].stt_source == "groq"
    assert finals[0].turn_id and finals[0].correlation_id
    # The upload keeps the command's first word: pre-roll plus the whole command.
    command_s = speech_end_s(name) - run.hits[0].at_sample / SR
    assert len(groq.requests) == 1
    assert groq.uploaded_seconds() >= command_s + 0.3


async def test_mid_thought_pause_stays_one_turn(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    text = "Hey Jarvis, I was thinking that we could maybe check the weather tomorrow."
    run = await run_fixture("mid_thought_pause", text)
    finals = [e for e in run.hub.events if isinstance(e, TranscriptFinal)]
    assert [f.text for f in finals] == [
        "I was thinking that we could maybe check the weather tomorrow."
    ]
    assert len(groq.requests) == 1
    command_s = speech_end_s("mid_thought_pause") - run.hits[0].at_sample / SR
    assert groq.uploaded_seconds() >= command_s + 0.3  # both halves went up together


async def test_no_audio_leaves_the_pc_without_the_wake_phrase(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    run = await run_fixture("tv_negative", "should never be asked")
    assert run.hub.events == []
    assert groq.requests == []


async def test_wake_phrase_alone_sends_nothing(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    run = await run_fixture("wake_only", "Hey Jarvis.")
    assert run.hub.types()[0] == "wake.detected"
    assert "transcript.final" not in run.hub.types()
