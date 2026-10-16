"""SPCH-01/02, D-01 to D-06, D-35, D-36: persona, tone tag, guardrails, history."""

import json
import time
from typing import Any

import pytest

from snow.brain.persona import (
    Fact,
    History,
    PersonaConfig,
    apply_overrides,
    build_messages,
)
from snow.brain.worker import BrainWorker
from snow.config.settings import load_config
from snow.contracts.events import Event, ReplyDelta, ReplyFinal, Tone, TranscriptFinal
from snow.contracts.wire import TranscriptRow
from tests.brain.conftest import Routes, sse_route
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


def test_history_is_seeded_from_snapshot_rows() -> None:
    def row(kind: str, text: str, n: int) -> TranscriptRow:
        return TranscriptRow(
            row_id=str(n),
            kind=kind,  # pyright: ignore[reportArgumentType]
            text=text,
            ts_ns=n,
        )

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
