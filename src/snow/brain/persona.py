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
# A note for the model only, never spoken (SPCH-01); config/persona.toml explains it.
INTERRUPTED_MARK = "[the user interrupted you here]"
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


def _cut(spoken: str) -> str:
    """What the user heard, then the marker (only the marker if nothing was heard)."""
    heard = spoken.rstrip()
    return f"{heard} {INTERRUPTED_MARK}" if heard else INTERRUPTED_MARK


class MarkFilter:
    """Strips INTERRUPTED_MARK from streamed text, even when chunks split it."""

    def __init__(self) -> None:
        self._held = ""

    def feed(self, piece: str) -> str:
        text = (self._held + piece).replace(INTERRUPTED_MARK, "")
        for k in range(min(len(text), len(INTERRUPTED_MARK) - 1), 0, -1):
            if INTERRUPTED_MARK.startswith(text[-k:]):
                self._held = text[-k:]
                return text[:-k]
        self._held = ""
        return text

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held


class History:
    """Past (user, reply) pairs, oldest first, trimmed by turn and token caps.

    A reply the user cut off keeps only the words they heard, then INTERRUPTED_MARK.
    """

    def __init__(self) -> None:
        self._pairs: list[tuple[str, str, str | None]] = []
        self._cuts: dict[str, str] = {}  # interrupt that arrived before its turn's add

    def __len__(self) -> int:
        return len(self._pairs)

    def add(self, user: str, reply: str, turn_id: str | None = None) -> None:
        if turn_id is not None:
            reply = self._cuts.pop(turn_id, reply)
        self._pairs.append((user, reply, turn_id))
        del self._pairs[:-_KEEP_PAIRS]

    def interrupt(self, turn_id: str, spoken: str) -> None:
        cut = _cut(spoken)
        for i in range(len(self._pairs) - 1, -1, -1):
            user, _, tid = self._pairs[i]
            if tid == turn_id:
                self._pairs[i] = (user, cut, tid)
                return
        self._cuts[turn_id] = cut
        while len(self._cuts) > _KEEP_PAIRS:
            del self._cuts[next(iter(self._cuts))]

    def seed(self, rows: Iterable[TranscriptRow]) -> None:
        """Rebuild pairs from a hub snapshot so a restarted brain keeps its thread."""
        pending: str | None = None
        for row in rows:
            if row.kind == "user":
                pending = row.text
            elif row.kind == "snow" and pending is not None:
                text = _cut(row.text) if row.interrupted else row.text
                self.add(pending, text, row.turn_id)
                pending = None

    def window(self, turns: int, token_budget: int) -> list[tuple[str, str]]:
        kept = self._pairs[-turns:] if turns > 0 else []
        while (
            len(kept) > 1
            and sum(_tokens(u) + _tokens(r) for u, r, _ in kept) > token_budget
        ):
            kept = kept[1:]
        return [(u, r) for u, r, _ in kept]


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
