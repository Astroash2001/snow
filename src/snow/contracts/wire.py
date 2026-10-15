"""WebSocket wire protocol between the hub and its clients.

Order on a connection: client Hello, hub SnapshotMsg, then live EventMsg traffic.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from snow.contracts.events import Event

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


class DevSay(_Strict):
    """Developer-only test input (D-07): a typed line standing in for speech."""

    type: Literal["cmd.dev.say"] = "cmd.dev.say"
    text: str = Field(max_length=2000)


# Plan 01-04 grows this into a discriminated union of commands.
Command = DevSay


class CommandMsg(_Strict):
    kind: Literal["command"] = "command"
    command: Command


class Snapshot(_Strict):
    """Plan 01-04 adds the remaining projection fields, each with a default."""

    last_seq: int = 0


class SnapshotMsg(_Strict):
    kind: Literal["snapshot"] = "snapshot"
    snapshot: Snapshot


WireMessage = Annotated[
    Hello | EventMsg | CommandMsg | SnapshotMsg,
    Field(discriminator="kind"),
]
