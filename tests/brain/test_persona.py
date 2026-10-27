"""SPCH-01/02, D-01 to D-06, D-35, D-36: persona, tone tag, guardrails, history."""

import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from snow.brain.persona import (
    INTERRUPTED_MARK,
    Fact,
    History,
    MarkFilter,
    PersonaConfig,
    apply_overrides,
    build_messages,
)
from snow.brain.worker import BrainWorker
from snow.config.settings import load_config
from snow.contracts.events import (
    Event,
    ReplyDelta,
    ReplyFinal,
    ReplyInterrupted,
    Tone,
    TranscriptFinal,
    TurnCancelled,
)
from snow.contracts.wire import TranscriptRow
from tests.brain.conftest import Routes, sse_route, stall_route
from tests.conftest import InMemoryKeyring, SnowDirs


@pytest.fixture
def persona(snow_dirs: SnowDirs) -> PersonaConfig:
    return load_config("persona.toml", PersonaConfig)


def tone(emotion: str | None = "stressed", pace: str = "fast") -> Tone:
    return Tone(
        emotion=emotion,
        pace=pace,  # pyright: ignore[reportArgumentType]
        loudness="loud",
        words_per_min=190,
        loudness_dbfs=-18,
    )


def test_persona_file_describes_the_character(persona: PersonaConfig) -> None:
    assert "sir" in persona.system_prompt
    assert "no tools" in persona.system_prompt
    assert "neutral" in persona.allowed_emotions
    assert persona.fallback_emotion in persona.allowed_emotions


def test_tone_tag_sits_on_the_user_turn_only_when_tone_exists(
    persona: PersonaConfig,
) -> None:
    with_tone = build_messages(persona, History(), "what time is it", tone(), [])
    assert with_tone[-1] == {
        "role": "user",
        "content": "[user tone: stressed, fast, loud]\nwhat time is it",
    }
    without = build_messages(persona, History(), "what time is it", None, [])
    assert without[-1]["content"] == "what time is it"


def test_unknown_tone_emotion_is_labelled_unknown(persona: PersonaConfig) -> None:
    msgs = build_messages(persona, History(), "hi", tone(None, "slow"), [])
    assert str(msgs[-1]["content"]).startswith("[user tone: unknown, slow, loud]")


def test_facts_are_added_to_the_system_message_once_listed(
    persona: PersonaConfig,
) -> None:
    facts = [Fact("The voice engine changed.")]
    msgs = build_messages(persona, History(), "hi", None, facts)
    assert "Context facts for this reply" in str(msgs[0]["content"])
    assert "The voice engine changed." in str(msgs[0]["content"])
    plain = build_messages(persona, History(), "hi", None, [])
    assert "for this reply (mention once" not in str(plain[0]["content"])


def test_stressed_tone_forces_calm_whatever_the_model_chose(
    persona: PersonaConfig,
) -> None:
    assert apply_overrides(persona, "excited", tone("stressed"), []) == "calm"
    assert apply_overrides(persona, "excited", tone("angry"), []) == "calm"
    assert apply_overrides(persona, "excited", tone("happy"), []) == "excited"
    assert apply_overrides(persona, "excited", None, []) == "excited"


def test_error_context_allows_only_neutral_or_sympathetic(
    persona: PersonaConfig,
) -> None:
    error = [Fact("The provider failed.", error=True)]
    assert apply_overrides(persona, "excited", None, error) == "neutral"
    assert apply_overrides(persona, "sympathetic", None, error) == "sympathetic"
    assert apply_overrides(persona, "excited", tone("stressed"), error) == "neutral"


def test_history_keeps_the_newest_turns_and_drops_oldest_first() -> None:
    h = History()
    for i in range(8):
        h.add(f"q{i}", f"a{i}")
    assert [u for u, _ in h.window(6, 10_000)] == [f"q{i}" for i in range(2, 8)]


def test_history_drops_oldest_when_the_token_budget_is_exceeded() -> None:
    h = History()
    h.add("a" * 400, "b" * 400)  # ~200 tokens
    h.add("c" * 400, "d" * 400)
    h.add("e" * 40, "f" * 40)
    kept = h.window(6, 250)
    assert [u[0] for u, _ in kept] == ["c", "e"]


def row(
    kind: str,
    text: str,
    n: int,
    turn_id: str | None = None,
    interrupted: bool = False,
) -> TranscriptRow:
    return TranscriptRow(
        row_id=str(n),
        kind=kind,  # pyright: ignore[reportArgumentType]
        text=text,
        ts_ns=n,
        turn_id=turn_id,
        interrupted=interrupted,
    )


def test_history_is_seeded_from_snapshot_rows() -> None:
    h = History()
    h.seed(
        [
            row("user", "hello", 1),
            row("snow", "good evening", 2),
            row("system", "voice_switch", 3),
            row("user", "unanswered", 4),
        ]
    )
    assert h.window(6, 1000) == [("hello", "good evening")]


CUT = "One. " + INTERRUPTED_MARK


def test_interrupt_after_add_keeps_only_the_heard_words() -> None:
    h = History()
    h.add("other", "kept")
    h.add("count to three", "One. Two. Three.", "t1")
    h.interrupt("t1", "One.")
    assert h.window(6, 1000) == [("other", "kept"), ("count to three", CUT)]


def test_interrupt_before_add_gives_the_same_window() -> None:
    h = History()
    h.interrupt("t1", "One.")
    assert len(h) == 0  # an unknown turn adds no pair by itself
    h.add("count to three", "One. Two. Three.", "t1")
    assert h.window(6, 1000) == [("count to three", CUT)]


def test_interrupt_with_nothing_heard_stores_just_the_marker() -> None:
    h = History()
    h.add("q", "Long answer.", "t1")
    h.interrupt("t1", "  ")
    assert h.window(6, 1000) == [("q", INTERRUPTED_MARK)]


def test_seed_respects_interrupted_rows() -> None:
    h = History()
    h.seed(
        [
            row("user", "q", 1),
            row("snow", "One.", 2, turn_id="t1", interrupted=True),
            row("user", "r", 3),
            row("snow", "Whole.", 4, turn_id="t2"),
        ]
    )
    assert h.window(6, 1000) == [("q", CUT), ("r", "Whole.")]


def test_persona_explains_the_marker_without_scripting_a_line(
    persona: PersonaConfig,
) -> None:
    prompt = persona.system_prompt
    assert INTERRUPTED_MARK in prompt
    lowered = prompt.lower()
    for words in ("never apologise", "never repeat", "offer to continue"):
        assert words in lowered


def test_mark_filter_strips_the_marker_even_when_split() -> None:
    f = MarkFilter()
    out = "".join(
        f.feed(c) for c in ["One. [the us", "er interrupted", " you here] Two.", " [th"]
    )
    assert out + f.flush() == "One.  Two. [th"
    assert INTERRUPTED_MARK not in out


# --- worker: the conversation request and reply ---------------------------------


def make_worker(
    routes: Routes, memory_keyring: InMemoryKeyring
) -> tuple[BrainWorker, list[Event]]:
    memory_keyring.set_password("snow", "groq", "gsk_test")
    published: list[Event] = []

    async def collect(ev: Event) -> None:
        published.append(ev)

    return BrainWorker(collect, client_factory=routes.client_factory), published


def heard(text: str, tone_: Tone | None = None) -> TranscriptFinal:
    return TranscriptFinal(ts_ns=time.time_ns(), source="voice", text=text, tone=tone_)


def request_body(routes: Routes, n: int = -1) -> dict[str, Any]:
    return json.loads(routes.bodies["api.groq.com"][n])


async def test_reply_header_never_reaches_deltas_and_sets_emotion_and_big(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, "api.groq.com", ["[[excit", "ed|big]] Wel", "come back, sir."])
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(heard("hello"))
    deltas = [e.text for e in published if isinstance(e, ReplyDelta)]
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    assert "".join(deltas) == "Welcome back, sir." and "[" not in "".join(deltas)
    # every delta already carries the header's emotion and big-moment flag, so the
    # voice router picks Cartesia before the final event exists (SPCH-02)
    flags = {(e.emotion, e.big_moment) for e in published if isinstance(e, ReplyDelta)}
    assert flags == {("excited", True)}
    assert (final.text, final.emotion, final.big_moment, final.reply_source) == (
        "Welcome back, sir.",
        "excited",
        True,
        "llm",
    )


async def test_conversation_request_has_no_tools_is_private_and_carries_tone(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, "api.groq.com", ["[[calm]] Understood, sir."])
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(heard("my build broke again", tone()))
    body = request_body(routes)
    assert "tools" not in body and "tool_choice" not in body
    assert body["max_tokens"] == 400
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1]["content"].startswith(
        "[user tone: stressed, fast, loud]"
    )
    [call] = [e for e in published if e.type == "llm.call"]
    assert call.data_class == "private"
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    assert final.emotion == "calm"


async def test_stressed_user_overrides_an_excited_reply(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, "api.groq.com", ["[[excited]] Marvellous!"])
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(heard("nothing works", tone("angry")))
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    assert final.emotion == "calm"


async def test_next_turn_sends_the_previous_exchange_without_headers(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, "api.groq.com", ["[[content]] Hello, sir."])
    sse_route(routes, "api.groq.com", ["[[content]] Quite well."])
    worker, _ = make_worker(routes, memory_keyring)
    await worker.on_event(heard("hello"))
    await worker.on_event(heard("how are you"))
    msgs = request_body(routes)["messages"]
    assert [(m["role"], m["content"]) for m in msgs[1:]] == [
        ("user", "hello"),
        ("assistant", "Hello, sir."),
        ("user", "how are you"),
    ]


def test_the_local_date_and_time_is_in_every_system_prompt(
    persona: PersonaConfig,
) -> None:
    now = datetime(2026, 10, 24, 14, 5, tzinfo=UTC)
    msgs = build_messages(persona, History(), "what time is it", None, [], now=now)
    want = "Current local date and time: Saturday 24 October 2026, 02:05 PM UTC."
    assert want in str(msgs[0]["content"])


# --- interruption: the next request carries only what was heard ---------------


def heard_turn(text: str, turn_id: str) -> TranscriptFinal:
    return TranscriptFinal(
        ts_ns=time.time_ns(), source="voice", text=text, turn_id=turn_id
    )


def assert_next_turn_carries_the_cut(routes: Routes) -> None:
    msgs = request_body(routes)["messages"]
    assert [(m["role"], m["content"]) for m in msgs[1:]] == [
        ("user", "count to three"),
        ("assistant", CUT),
        ("user", "and then?"),
    ]
    blob = json.dumps(msgs[1:])
    assert "Two." not in blob and "Three." not in blob


async def test_interrupt_after_the_stream_ended_trims_the_next_request(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(routes, "api.groq.com", ["[[calm]] One.", " Two.", " Three."])
    sse_route(routes, "api.groq.com", ["[[calm]] Quite."])
    worker, _ = make_worker(routes, memory_keyring)
    await worker.on_event(heard_turn("count to three", "t1"))
    await worker.on_event(
        ReplyInterrupted(
            ts_ns=time.time_ns(), source="voice", turn_id="t1", spoken_text="One."
        )
    )
    await worker.on_event(heard_turn("and then?", "t2"))
    assert_next_turn_carries_the_cut(routes)


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_interrupt_mid_stream_records_the_turn_and_publishes_no_final(
    snow_dirs: SnowDirs,
    memory_keyring: InMemoryKeyring,
    routes: Routes,
    cancel_first: bool,
) -> None:
    stall_route(routes, "api.groq.com", ["[[calm]] One.", " Two.", " Three."])
    sse_route(routes, "api.groq.com", ["[[calm]] Quite."])
    worker, published = make_worker(routes, memory_keyring)
    task = asyncio.create_task(worker.on_event(heard_turn("count to three", "t1")))
    async with asyncio.timeout(5):
        while not any(isinstance(e, ReplyDelta) for e in published):  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    cancelled = TurnCancelled(
        ts_ns=time.time_ns(), source="voice", turn_id="t1", cancel_reason="barge_in"
    )
    cut = ReplyInterrupted(
        ts_ns=time.time_ns(), source="voice", turn_id="t1", spoken_text="One."
    )
    if cancel_first:
        await worker.on_event(cancelled)
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await worker.on_event(cut)
    else:
        await worker.on_event(cut)
        await worker.on_event(cancelled)
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert not [e for e in published if isinstance(e, ReplyFinal)]
    await worker.on_event(heard_turn("and then?", "t2"))
    assert_next_turn_carries_the_cut(routes)


async def test_a_reply_containing_the_marker_is_published_without_it(
    snow_dirs: SnowDirs, memory_keyring: InMemoryKeyring, routes: Routes
) -> None:
    sse_route(
        routes,
        "api.groq.com",
        ["[[calm]] Yes. [the user inter", "rupted you here] Sir."],
    )
    worker, published = make_worker(routes, memory_keyring)
    await worker.on_event(heard("hello"))
    [final] = [e for e in published if isinstance(e, ReplyFinal)]
    said = "".join(e.text for e in published if isinstance(e, ReplyDelta))
    assert INTERRUPTED_MARK not in said and INTERRUPTED_MARK not in str(final.text)
    assert "Yes." in said and "Sir." in said
