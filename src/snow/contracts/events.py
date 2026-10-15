"""Typed event contract (CORE-03). Every action Snow takes is one of these events.

This is the complete Phase 1 catalog (plan 01-04). Rules for the whole phase:
- Every event inherits `Envelope`; field names must not collide with envelope
  fields (`source`, `reason`, `result`, ...), hence `channel`, `stt_source`,
  `end_reason`, `switch_reason` and friends.
- Durable events are stored in SQLite; ephemeral ones are broadcast only.
- Speech text is the only thing stored in the `content` column (`content_field`).
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


class _Part(BaseModel):
    """A nested value object (not an event)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


Worker = Literal["voice", "brain", "hud"]
LlmRole = Literal["brain", "fast", "vision"]
Engine = Literal["pocket_tts", "cartesia", "chatterbox", "kokoro"]
ProviderStatus = Literal["ready", "active", "cooling_down", "failing", "not_configured"]


# --- Wake and conversation ---------------------------------------------------


class WakeDetected(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["wake.detected"] = "wake.detected"
    score: float
    model: str


class ConversationStarted(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["conversation.started"] = "conversation.started"
    trigger: Literal["wake", "dev"]


class ConversationEnded(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["conversation.ended"] = "conversation.ended"
    end_reason: Literal["silence", "phrase", "sleep", "mute", "dev"]


class PresenceState(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["presence.state"] = "presence.state"
    state: Literal["sleeping", "listening", "thinking", "speaking", "muted"]
    mode: Literal["awake", "soft_sleep"]


class MuteChanged(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["mute.changed"] = "mute.changed"
    muted: bool
    by: Literal["voice", "hud", "tray", "startup"]


class AudioLevel(Envelope):
    durable: ClassVar[bool] = False

    type: Literal["audio.level"] = "audio.level"
    # `channel`, not `source`: `source` is the envelope's emitting process.
    channel: Literal["mic", "tts"]
    level: float = Field(ge=0.0, le=1.0)


# --- Speech and replies ------------------------------------------------------


class TranscriptPartial(Envelope):
    durable: ClassVar[bool] = False

    type: Literal["transcript.partial"] = "transcript.partial"
    text: str


class Tone(_Part):
    """Locally detected tone of the user's utterance (D-32 to D-39)."""

    emotion: str | None = None
    emotion_confidence: float | None = None
    pace: Literal["slow", "normal", "fast"]
    loudness: Literal["quiet", "normal", "loud"]
    words_per_min: float
    loudness_dbfs: float
    pitch_hz_median: float | None = None


class TranscriptFinal(Envelope):
    durable: ClassVar[bool] = True
    content_field: ClassVar[str | None] = "text"

    type: Literal["transcript.final"] = "transcript.final"
    text: str
    # Defaults to "dev" so the plan 01-01 dev path and callers written against it
    # keep working; real speech-to-text always sets it explicitly.
    stt_source: Literal["groq", "local", "dev"] = "dev"
    duration_ms: int = 0
    tone: Tone | None = None


class ReplyDelta(Envelope):
    durable: ClassVar[bool] = False

    type: Literal["reply.delta"] = "reply.delta"
    text: str


class ReplyFinal(Envelope):
    durable: ClassVar[bool] = True
    content_field: ClassVar[str | None] = "text"

    type: Literal["reply.final"] = "reply.final"
    # Empty text means nothing is spoken: only the silent all-providers-down case
    # (D-41, D-09: no spoken literal, no earcon).
    text: str = ""
    emotion: str
    big_moment: bool
    reply_source: Literal["llm", "ack_pool", "fallback"]
    provider: str | None = None
    model: str | None = None


class ReplyInterrupted(Envelope):
    durable: ClassVar[bool] = True
    content_field: ClassVar[str | None] = "spoken_text"

    type: Literal["reply.interrupted"] = "reply.interrupted"
    spoken_text: str


class TurnCancelled(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["turn.cancelled"] = "turn.cancelled"
    cancel_reason: Literal["barge_in", "conversation_end", "mute"]


class AckRequested(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["ack.requested"] = "ack.requested"


# --- LLM routing -------------------------------------------------------------


class LlmCall(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["llm.call"] = "llm.call"
    role: LlmRole
    provider: str
    model: str
    data_class: Literal["general", "private"]
    ttft_ms: int | None = None
    total_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    outcome: Literal["ok", "error", "cancelled"]
    error_kind: str | None = None


class LlmSwitch(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["llm.switch"] = "llm.switch"
    role: LlmRole
    from_provider: str
    from_model: str
    to_provider: str
    to_model: str
    switch_reason: Literal[
        "rate_limit",
        "out_of_quota",
        "service_error",
        "timeout",
        "unreachable",
        "bad_key",
        "config_error",
    ]


class LlmBlockedPrivacy(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["llm.blocked_privacy"] = "llm.blocked_privacy"
    role: LlmRole
    data_class: Literal["general", "private"]


class LlmExhausted(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["llm.exhausted"] = "llm.exhausted"
    role: LlmRole


# --- Health ------------------------------------------------------------------


class HealthSubsystem(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["health.subsystem"] = "health.subsystem"
    name: str
    label: str
    owner: Literal["hub", "voice", "brain", "hud"]
    status: Literal["running", "starting", "restarting", "down"]
    detail: str | None = None


class HealthProvider(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["health.provider"] = "health.provider"
    provider: str
    label: str
    status: ProviderStatus
    cooling_until_ns: int | None = None
    detail: str | None = None
    requests_today: int = 0
    tokens_today: int = 0


class ChainEntryStatus(_Part):
    provider: str
    provider_label: str
    model: str
    status: ProviderStatus
    cooling_until_ns: int | None = None
    detail: str | None = None


class HealthRole(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["health.role"] = "health.role"
    role: LlmRole
    status: Literal[
        "active",
        "fallback",
        "cooling_down",
        "failing",
        "not_configured",
        "not_used_yet",
    ]
    active_provider: str | None = None
    active_model: str | None = None
    active_index: int | None = None
    entries: list[ChainEntryStatus] = Field(default_factory=list[ChainEntryStatus])


class SttStatus(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["stt.status"] = "stt.status"
    stt_source: Literal["groq", "local"]
    status_reason: Literal[
        "primary", "unreachable", "rate_limited", "no_key", "offline"
    ]
    retry_after_ns: int | None = None


class VoiceStatus(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["voice.status"] = "voice.status"
    engine: Engine
    voice_name: str
    voice_role: Literal["everyday", "big_moment", "gpu", "fallback"]
    credits_remaining: int | None = None
    cartesia_available: bool
    cartesia_reason: (
        Literal["ok", "out_of_credits", "unreachable", "no_key", "budget_reached"]
        | None
    ) = None


class VoiceSwitch(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["voice.switch"] = "voice.switch"
    from_engine: Engine
    to_engine: Engine
    switch_reason: Literal[
        "out_of_credits",
        "unreachable",
        "no_key",
        "budget_reached",
        "power",
        "gpu_busy",
        "load_failed",
    ]


class TtsSpoken(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["tts.spoken"] = "tts.spoken"
    engine: Engine
    chars: int
    first_audio_ms: int | None = None


class TurnTiming(Envelope):
    """Wall-clock nanoseconds so values compare across processes."""

    durable: ClassVar[bool] = True

    type: Literal["turn.timing"] = "turn.timing"
    vad_stop_ns: int | None = None
    stt_final_ns: int | None = None
    llm_first_token_ns: int | None = None
    tts_first_audio_ns: int | None = None
    audio_out_first_ns: int | None = None


# --- Process supervision -----------------------------------------------------


class WorkerStarted(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["worker.started"] = "worker.started"
    worker: Worker
    pid: int
    restart_count: int = 0


class WorkerExited(Envelope):
    durable: ClassVar[bool] = True

    type: Literal["worker.exited"] = "worker.exited"
    worker: Worker
    pid: int
    exit_code: int | None = None
    cause: Literal["crash", "hang", "killed", "quit"]


class Heartbeat(Envelope):
    durable: ClassVar[bool] = False

    type: Literal["heartbeat"] = "heartbeat"
    worker: str


Event = Annotated[
    WakeDetected
    | ConversationStarted
    | ConversationEnded
    | PresenceState
    | MuteChanged
    | AudioLevel
    | TranscriptPartial
    | TranscriptFinal
    | ReplyDelta
    | ReplyFinal
    | ReplyInterrupted
    | TurnCancelled
    | AckRequested
    | LlmCall
    | LlmSwitch
    | LlmBlockedPrivacy
    | LlmExhausted
    | HealthSubsystem
    | HealthProvider
    | HealthRole
    | SttStatus
    | VoiceStatus
    | VoiceSwitch
    | TtsSpoken
    | TurnTiming
    | WorkerStarted
    | WorkerExited
    | Heartbeat,
    Field(discriminator="type"),
]

ENVELOPE_FIELDS: frozenset[str] = frozenset(Envelope.model_fields)
