"""Typed event contract (CORE-03). Every action Snow takes is one of these events.

Plan 01-04 completes the catalog; it must not rename anything defined here.
"""

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    """Fields shared by every event. `seq` is assigned by the hub for durable events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Durable events are written to SQLite; ephemeral ones are broadcast only.
    durable: ClassVar[bool]
    # Name of the payload field stored in the `content` column (speech text), or None.
    content_field: ClassVar[str | None] = None

    seq: int | None = None
    ts_ns: int
    source: Literal["hub", "voice", "brain", "hud", "dev"]
    correlation_id: str | None = None
    turn_id: str | None = None
    causation_id: int | None = None
    user_id: str = "owner"
    risk_tier: Literal["free", "announce", "ask", "always_ask"] = "free"
    reason: str | None = None
    result: str | None = None


class TranscriptFinal(Envelope):
    durable: ClassVar[bool] = True
    content_field: ClassVar[str | None] = "text"

    type: Literal["transcript.final"] = "transcript.final"
    text: str


class ReplyDelta(Envelope):
    durable: ClassVar[bool] = False

    type: Literal["reply.delta"] = "reply.delta"
    text: str


class ReplyFinal(Envelope):
    durable: ClassVar[bool] = True
    content_field: ClassVar[str | None] = "text"

    type: Literal["reply.final"] = "reply.final"
    text: str
    emotion: str
    big_moment: bool
    reply_source: Literal["llm", "ack_pool", "fallback"]
    provider: str | None = None
    model: str | None = None


class Heartbeat(Envelope):
    durable: ClassVar[bool] = False

    type: Literal["heartbeat"] = "heartbeat"
    worker: str


Event = Annotated[
    TranscriptFinal | ReplyDelta | ReplyFinal | Heartbeat,
    Field(discriminator="type"),
]

ENVELOPE_FIELDS: frozenset[str] = frozenset(Envelope.model_fields)
