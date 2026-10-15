"""Projection: a pure reducer from the event stream to the client snapshot (D-14)."""

import time
from collections.abc import Callable
from datetime import date, datetime

from snow.contracts.events import (
    ConversationEnded,
    ConversationStarted,
    Envelope,
    HealthProvider,
    HealthRole,
    HealthSubsystem,
    LlmBlockedPrivacy,
    LlmExhausted,
    LlmSwitch,
    MuteChanged,
    PresenceState,
    ReplyFinal,
    ReplyInterrupted,
    SttStatus,
    TranscriptFinal,
    TtsSpoken,
    VoiceStatus,
)
from snow.contracts.wire import Snapshot, TranscriptRow


def local_midnight_ns(now_ns: int) -> int:
    """Nanosecond timestamp of the most recent local midnight."""
    now = datetime.fromtimestamp(now_ns / 1e9)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1e9)


def _day(ts_ns: int) -> date:
    return datetime.fromtimestamp(ts_ns / 1e9).date()


class Projection:
    def __init__(self, clock: Callable[[], int] = time.time_ns) -> None:
        self._clock = clock
        self._presence: str = "sleeping"
        self._mode: str = "awake"
        self._muted = False
        self._conversation_id: str | None = None
        self._rows: list[TranscriptRow] = []
        self._subsystems: dict[str, HealthSubsystem] = {}
        self._providers: dict[str, HealthProvider] = {}
        self._roles: dict[str, HealthRole] = {}
        self._voice: VoiceStatus | None = None
        self._stt: SttStatus | None = None
        self._cartesia_chars: dict[date, int] = {}
        self._last_seq = 0

    def apply(self, event: Envelope) -> None:
        if event.seq is not None:
            self._last_seq = max(self._last_seq, event.seq)
        match event:
            case PresenceState():
                self._presence, self._mode = event.state, event.mode
            case MuteChanged():
                self._muted = event.muted
            case ConversationStarted():
                self._rows.clear()
                self._conversation_id = event.correlation_id or str(event.seq)
            case ConversationEnded():
                self._rows.clear()
                self._conversation_id = None
            case TranscriptFinal():
                self._rows.append(self._row(event, "user", event.text))
            case ReplyFinal():
                if event.text:
                    self._rows.append(self._row(event, "snow", event.text))
            case ReplyInterrupted():
                self._interrupt(event)
            case LlmSwitch():
                facts = (
                    f"role={event.role} from={event.from_provider}/{event.from_model}"
                    f" to={event.to_provider}/{event.to_model}"
                    f" reason={event.switch_reason}"
                )
                self._rows.append(self._row(event, "system", facts))
            case LlmBlockedPrivacy():
                facts = f"role={event.role} data_class={event.data_class}"
                self._rows.append(self._row(event, "system", facts))
            case LlmExhausted():
                self._rows.append(self._row(event, "system", f"role={event.role}"))
            case HealthSubsystem():
                self._subsystems[event.name] = event
            case HealthProvider():
                self._providers[event.provider] = event
            case HealthRole():
                self._roles[event.role] = event
            case VoiceStatus():
                self._voice = event
            case SttStatus():
                self._stt = event
            case TtsSpoken() if event.engine == "cartesia":
                day = _day(event.ts_ns)
                self._cartesia_chars[day] = (
                    self._cartesia_chars.get(day, 0) + event.chars
                )
            case _:
                pass

    def set_muted(self, muted: bool) -> None:
        """Restore persisted mute state at start-up (it wins over replay)."""
        self._muted = muted

    def snapshot(self) -> Snapshot:
        return Snapshot.model_validate(
            {
                "presence": self._presence,
                "mode": self._mode,
                "muted": self._muted,
                "conversation_id": self._conversation_id,
                "rows": list(self._rows),
                "subsystems": list(self._subsystems.values()),
                "providers": list(self._providers.values()),
                "roles": list(self._roles.values()),
                "voice": self._voice,
                "stt": self._stt,
                "cartesia_chars_today": self._cartesia_chars.get(
                    _day(self._clock()), 0
                ),
                "last_seq": self._last_seq,
            }
        )

    @staticmethod
    def _row(event: Envelope, kind: str, text: str) -> TranscriptRow:
        return TranscriptRow.model_validate(
            {
                "row_id": str(event.seq)
                if event.seq is not None
                else f"e{event.ts_ns}",
                "kind": kind,
                "text": text,
                "turn_id": event.turn_id,
                "ts_ns": event.ts_ns,
                "system_event": getattr(event, "type", None)
                if kind == "system"
                else None,
            }
        )

    def _interrupt(self, event: ReplyInterrupted) -> None:
        for i in range(len(self._rows) - 1, -1, -1):
            row = self._rows[i]
            if row.kind == "snow" and row.turn_id == event.turn_id:
                self._rows[i] = row.model_copy(
                    update={"text": event.spoken_text, "interrupted": True}
                )
                return
        # Interrupted before its reply.final was recorded: still show what was heard.
        if event.spoken_text:
            row = self._row(event, "snow", event.spoken_text)
            self._rows.append(row.model_copy(update={"interrupted": True}))
