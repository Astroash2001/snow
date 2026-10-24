"""Persona config, conversation history and message building (D-01 to D-06, D-35, D-36).

The persona file holds instructions for the model only. Every word Snow speaks is
written by the LLM (SPCH-01); nothing in this module is a spoken line.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict

from snow.contracts.events import Tone
from snow.contracts.wire import TranscriptRow

CALM = "calm"
_KEEP_PAIRS = 50  # storage bound; the per-turn window is trimmed by the persona caps


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system_prompt: str
    allowed_emotions: list[str]
    fallback_emotion: str
    calm_override_tones: list[str]
    error_emotions: list[str]
    history_turns: int
    history_token_budget: int
    max_reply_tokens: int
    ack_pool_size: int
    ack_pool_min: int
    ack_prompt: str


@dataclass(frozen=True)
class Fact:
    """Something the next reply should mention once, in character."""

    text: str
    error: bool = False  # a failure: sarcasm and big emotions are off (D-03)


def _tokens(text: str) -> int:
    return (
        len(text) // 4
    )  # shortcut: chars/4 estimate, swap for a tokenizer if budgets get tight


class History:
    """Past (user, reply) pairs, oldest first, trimmed by turn and token caps."""

    def __init__(self) -> None:
        self._pairs: list[tuple[str, str]] = []

    def __len__(self) -> int:
        return len(self._pairs)

    def add(self, user: str, reply: str) -> None:
        self._pairs.append((user, reply))
        del self._pairs[:-_KEEP_PAIRS]

    def seed(self, rows: Iterable[TranscriptRow]) -> None:
        """Rebuild pairs from a hub snapshot so a restarted brain keeps its thread."""
        pending: str | None = None
        for row in rows:
            if row.kind == "user":
                pending = row.text
            elif row.kind == "snow" and pending is not None:
                self.add(pending, row.text)
                pending = None

    def window(self, turns: int, token_budget: int) -> list[tuple[str, str]]:
        kept = self._pairs[-turns:] if turns > 0 else []
        while (
            len(kept) > 1
            and sum(_tokens(u) + _tokens(r) for u, r in kept) > token_budget
        ):
            kept = kept[1:]
        return kept


def tone_line(tone: Tone) -> str:
    return f"[user tone: {tone.emotion or 'unknown'}, {tone.pace}, {tone.loudness}]"


def build_messages(
    persona: PersonaConfig,
    history: History,
    text: str,
    tone: Tone | None,
    facts: Sequence[Fact],
    now: datetime | None = None,
) -> list[ChatCompletionMessageParam]:
    # The model has no clock: give it this PC's local time on every turn.
    when = (now or datetime.now().astimezone()).strftime("%A %d %B %Y, %I:%M %p %Z")
    system = f"{persona.system_prompt}\n\nCurrent local date and time: {when}."
    if facts:
        listed = "\n".join(f"- {f.text}" for f in facts)
        system += (
            "\n\nContext facts for this reply (mention once, briefly, in character):\n"
            + listed
        )
    messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
    for user, reply in history.window(
        persona.history_turns, persona.history_token_budget
    ):
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": reply})
    turn = f"{tone_line(tone)}\n{text}" if tone else text
    messages.append({"role": "user", "content": turn})
    return messages


def apply_overrides(
    persona: PersonaConfig, emotion: str, tone: Tone | None, facts: Sequence[Fact]
) -> str:
    """Deterministic guardrails over the model's choice (D-03, D-36)."""
    if any(f.error for f in facts):
        return (
            emotion if emotion in persona.error_emotions else persona.fallback_emotion
        )
    if tone and tone.emotion in persona.calm_override_tones:
        return CALM
    return emotion
