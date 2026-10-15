"""WebSocket wire protocol between the hub and its clients.

Order on a connection: client Hello, hub SnapshotMsg, then live EventMsg traffic.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from snow.contracts.events import (
    Event,
    HealthProvider,
    HealthRole,
    HealthSubsystem,
    SttStatus,
    VoiceStatus,
)

Role = Literal["voice", "brain", "hud", "dev"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Hello(_Strict):
    kind: Literal["hello"] = "hello"
    role: Role
    token: str
    protocol: int = 1


class EventMsg(_Strict):
    kind: Literal["event"] = "event"
    event: Event


# --- Commands ----------------------------------------------------------------


class MuteSet(_Strict):
    type: Literal["cmd.mute.set"] = "cmd.mute.set"
    muted: bool
    by: Literal["hud", "tray"]


class AppQuit(_Strict):
    type: Literal["cmd.app.quit"] = "cmd.app.quit"


class SnapshotRequest(_Strict):
    type: Literal["cmd.snapshot"] = "cmd.snapshot"


class DevSay(_Strict):
    """Developer-only test input (D-07): a typed line standing in for speech."""

    type: Literal["cmd.dev.say"] = "cmd.dev.say"
    text: str = Field(max_length=2000)


class DevKill(_Strict):
    """Developer-only: kill a worker to test supervision (plan 01-14 implements it)."""

    type: Literal["cmd.dev.kill"] = "cmd.dev.kill"
    worker: Literal["voice", "brain", "hud"]


Command = Annotated[
    MuteSet | AppQuit | SnapshotRequest | DevSay | DevKill,
    Field(discriminator="type"),
]

# Which roles may send which command; anything else closes the socket with 4403.
COMMAND_ROLES: dict[str, frozenset[Role]] = {
    "cmd.mute.set": frozenset({"hud"}),
    "cmd.app.quit": frozenset({"hud"}),
    "cmd.snapshot": frozenset({"voice", "brain", "hud", "dev"}),
    "cmd.dev.say": frozenset({"dev"}),
    "cmd.dev.kill": frozenset({"dev"}),
}


class CommandMsg(_Strict):
    kind: Literal["command"] = "command"
    command: Command


# --- Snapshot ----------------------------------------------------------------


class TranscriptRow(_Strict):
    row_id: str
    kind: Literal["user", "snow", "system"]
    # For system rows: space-separated key=value facts; the HUD owns the wording.
    text: str
    turn_id: str | None = None
    interrupted: bool = False
    ts_ns: int
    system_event: str | None = None


class Snapshot(_Strict):
    """Everything a client needs to draw the current state; all fields have defaults."""

    presence: Literal["sleeping", "listening", "thinking", "speaking", "muted"] = (
        "sleeping"
    )
    mode: Literal["awake", "soft_sleep"] = "awake"
    muted: bool = False
    conversation_id: str | None = None
    rows: list[TranscriptRow] = Field(default_factory=list[TranscriptRow])
    subsystems: list[HealthSubsystem] = Field(default_factory=list[HealthSubsystem])
    providers: list[HealthProvider] = Field(default_factory=list[HealthProvider])
    roles: list[HealthRole] = Field(default_factory=list[HealthRole])
    voice: VoiceStatus | None = None
    stt: SttStatus | None = None
    cartesia_chars_today: int = 0
    last_seq: int = 0


class SnapshotMsg(_Strict):
    kind: Literal["snapshot"] = "snapshot"
    snapshot: Snapshot


WireMessage = Annotated[
    Hello | EventMsg | CommandMsg | SnapshotMsg,
    Field(discriminator="kind"),
]
