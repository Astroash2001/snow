"""Conversation modes end to end on the 01-05 fixtures (real wake, VAD, Smart Turn)."""

from snow.contracts.events import (
    ConversationEnded,
    PresenceState,
    TranscriptFinal,
)
from tests.voice.conftest import FakeGroq, Run, RunFixture


def finals(run: Run) -> list[str]:
    return [e.text for e in run.hub.events if isinstance(e, TranscriptFinal)]


def presence(run: Run) -> list[tuple[str, str]]:
    return [(e.state, e.mode) for e in run.hub.events if isinstance(e, PresenceState)]


async def test_mid_thought_pause_is_one_turn(
    groq: FakeGroq, run_fixture: RunFixture
) -> None:
    text = "Hey Jarvis, I was thinking that we could maybe check the weather tomorrow."
    run = await run_fixture("mid_thought_pause", text)  # VOIC-05
    assert len(groq.requests) == 1
    assert len(finals(run)) == 1


async def test_wake_alone_asks_for_one_ack_and_stays_open(
    run_fixture: RunFixture,
) -> None:
    run = await run_fixture("wake_only", "Hey Jarvis.")
    assert run.hub.types().count("ack.requested") == 1
    assert "conversation.ended" not in run.hub.types()
    assert "transcript.final" not in run.hub.types()
    assert presence(run)[-1] == ("listening", "awake")


async def test_wake_with_a_command_requests_no_ack(run_fixture: RunFixture) -> None:
    run = await run_fixture("wake_cmd_gap150", "Hey Jarvis, what time is it?")
    assert "ack.requested" not in run.hub.types()


async def test_two_turns_in_one_conversation(
    run_fixture: RunFixture, groq: FakeGroq
) -> None:
    groq.texts = ["Hey Jarvis, what time is it?", "And what day is it?"]
    run = await run_fixture("conversation_two_turns", "", replies=True)
    assert finals(run) == ["what time is it?", "And what day is it?"]
    assert len(run.hits) == 1  # one wake
    assert run.hub.types().count("conversation.started") == 1
    assert "conversation.ended" not in run.hub.types()
    assert presence(run) == [
        ("listening", "awake"),
        ("thinking", "awake"),
        ("listening", "awake"),
        ("thinking", "awake"),
        ("listening", "awake"),
    ]


async def test_mic_level_only_while_listening(run_fixture: RunFixture) -> None:
    run = await run_fixture("conversation_two_turns", "Hey Jarvis, hi", replies=True)
    state = "sleeping"
    for e in run.hub.events:
        if isinstance(e, PresenceState):
            state = e.state
        elif e.type == "audio.level":
            assert state == "listening"
    assert "audio.level" in run.hub.types()


async def test_no_mic_level_while_asleep(run_fixture: RunFixture) -> None:
    run = await run_fixture("tv_negative", "never asked")
    assert "audio.level" not in run.hub.types()


async def test_thats_all_ends_the_conversation_without_a_transcript(
    run_fixture: RunFixture,
) -> None:
    run = await run_fixture("phrase_thats_all", "Hey Jarvis, that's all.")
    assert finals(run) == []
    ended = [e for e in run.hub.events if isinstance(e, ConversationEnded)]
    assert [e.end_reason for e in ended] == ["phrase"]
    assert presence(run)[-1] == ("sleeping", "awake")


async def test_go_to_sleep_is_soft_sleep(run_fixture: RunFixture) -> None:
    run = await run_fixture("phrase_go_to_sleep", "Hey Jarvis, go to sleep.")
    assert finals(run) == []
    ended = [e for e in run.hub.events if isinstance(e, ConversationEnded)]
    assert [e.end_reason for e in ended] == ["sleep"]
    assert presence(run)[-1] == ("sleeping", "soft_sleep")


async def test_mute_inside_a_sentence_is_a_request(run_fixture: RunFixture) -> None:
    run = await run_fixture(
        "phrase_mute_substring", "Hey Jarvis, mute the speaker in the call."
    )
    assert finals(run) == ["mute the speaker in the call."]
