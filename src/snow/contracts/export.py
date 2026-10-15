"""Generate the committed wire-protocol JSON Schema and golden samples.

    python -m snow.contracts.export            # (re)write contracts/
    python -m snow.contracts.export --check    # exit 1 if a committed file is stale

The HUD's TypeScript types are generated from `contracts/events.schema.json`
(plan 01-07); `--check` is the drift gate that keeps both sides honest.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from snow.contracts.events import (
    AckRequested,
    AudioLevel,
    ChainEntryStatus,
    ConversationEnded,
    ConversationStarted,
    Envelope,
    HealthProvider,
    HealthRole,
    HealthSubsystem,
    Heartbeat,
    LlmBlockedPrivacy,
    LlmCall,
    LlmExhausted,
    LlmSwitch,
    MuteChanged,
    PresenceState,
    ReplyDelta,
    ReplyFinal,
    ReplyInterrupted,
    SttStatus,
    Tone,
    TranscriptFinal,
    TranscriptPartial,
    TtsSpoken,
    TurnCancelled,
    TurnTiming,
    VoiceStatus,
    VoiceSwitch,
    WakeDetected,
    WorkerExited,
    WorkerStarted,
)
from snow.contracts.wire import (
    AppQuit,
    CommandMsg,
    DevKill,
    DevSay,
    EventMsg,
    MuteSet,
    Snapshot,
    SnapshotMsg,
    SnapshotRequest,
    TranscriptRow,
    WireMessage,
)

TS0 = 1_760_000_000_000_000_000  # fixed so the samples never drift
STEP_NS = 100_000_000
SCHEMA_PATH = Path("contracts") / "events.schema.json"
SAMPLES_PATH = Path("contracts") / "samples" / "events.json"
STREAM_PATH = Path("contracts") / "samples" / "conversation-12.jsonl"

_TONE = Tone(
    emotion="calm",
    emotion_confidence=0.8,
    pace="normal",
    loudness="normal",
    words_per_min=150.0,
    loudness_dbfs=-24.0,
    pitch_hz_median=120.0,
)
_CHAIN = [
    ChainEntryStatus(
        provider="experiential",
        provider_label="Experiential Labs",
        model="gpt-5.6-luna",
        status="active",
    ),
    ChainEntryStatus(
        provider="google",
        provider_label="Google AI Studio",
        model="gemini-flash",
        status="ready",
    ),
]


def _mk(cls: type[Envelope], n: int, source: str = "voice", **fields: Any) -> Envelope:
    """An event at fixed time `n`; durable events get seq `n`."""
    base = {
        "seq": n if cls.durable else None,
        "ts_ns": TS0 + n * STEP_NS,
        "source": source,
        "turn_id": "t1",
    }
    return cls.model_validate({**base, **fields})


def _msg(event: Envelope) -> dict[str, Any]:
    return EventMsg.model_validate({"event": event}).model_dump(mode="json")


def _sample_events() -> list[Envelope]:
    llm = {"role": "brain"}
    return [
        _mk(WakeDetected, 1, score=0.93, model="hey_snow"),
        _mk(ConversationStarted, 2, trigger="wake", correlation_id="conv-1"),
        _mk(ConversationEnded, 3, end_reason="silence"),
        _mk(PresenceState, 4, state="listening", mode="awake"),
        _mk(MuteChanged, 5, muted=True, by="hud"),
        _mk(AudioLevel, 0, channel="mic", level=0.4),
        _mk(TranscriptPartial, 0, text="what is the"),
        _mk(TranscriptFinal, 6, text="what is the time", stt_source="groq", tone=_TONE),
        _mk(ReplyDelta, 0, "brain", text="It is"),
        _mk(
            ReplyFinal,
            7,
            "brain",
            text="It is noon.",
            emotion="neutral",
            big_moment=False,
            reply_source="llm",
            provider="experiential",
            model="gpt-5.6-luna",
        ),
        _mk(ReplyInterrupted, 8, spoken_text="It is"),
        _mk(TurnCancelled, 9, cancel_reason="barge_in"),
        _mk(AckRequested, 10, "brain"),
        _mk(
            LlmCall,
            11,
            "brain",
            **llm,
            provider="experiential",
            model="gpt-5.6-luna",
            data_class="general",
            ttft_ms=420,
            total_ms=900,
            prompt_tokens=120,
            completion_tokens=30,
            outcome="ok",
        ),
        _mk(
            LlmSwitch,
            12,
            "brain",
            **llm,
            from_provider="experiential",
            from_model="gpt-5.6-luna",
            to_provider="google",
            to_model="gemini-flash",
            switch_reason="rate_limit",
        ),
        _mk(LlmBlockedPrivacy, 13, "brain", **llm, data_class="private"),
        _mk(LlmExhausted, 14, "brain", **llm),
        _mk(
            HealthSubsystem,
            15,
            name="mic",
            label="Microphone",
            owner="voice",
            status="running",
        ),
        _mk(
            HealthProvider,
            16,
            "brain",
            provider="experiential",
            label="Experiential Labs",
            status="active",
            requests_today=12,
            tokens_today=3400,
        ),
        _mk(
            HealthRole,
            17,
            "brain",
            **llm,
            status="active",
            active_provider="experiential",
            active_model="gpt-5.6-luna",
            active_index=0,
            entries=_CHAIN,
        ),
        _mk(SttStatus, 18, stt_source="groq", status_reason="primary"),
        _mk(
            VoiceStatus,
            19,
            engine="pocket_tts",
            voice_name="Snow",
            voice_role="everyday",
            credits_remaining=9000,
            cartesia_available=True,
            cartesia_reason="ok",
        ),
        _mk(
            VoiceSwitch,
            20,
            from_engine="cartesia",
            to_engine="pocket_tts",
            switch_reason="out_of_credits",
        ),
        _mk(TtsSpoken, 21, engine="cartesia", chars=11, first_audio_ms=380),
        _mk(
            TurnTiming,
            22,
            vad_stop_ns=TS0,
            stt_final_ns=TS0 + 300_000_000,
            llm_first_token_ns=TS0 + 700_000_000,
            tts_first_audio_ns=TS0 + 900_000_000,
            audio_out_first_ns=TS0 + 950_000_000,
        ),
        _mk(WorkerStarted, 23, worker="voice", pid=4242, restart_count=0),
        _mk(WorkerExited, 24, worker="voice", pid=4242, exit_code=1, cause="crash"),
        _mk(Heartbeat, 0, worker="voice"),
    ]


def _sample_commands() -> list[BaseModel]:
    return [
        MuteSet(muted=True, by="hud"),
        AppQuit(),
        SnapshotRequest(),
        DevSay(text="hello snow"),
        DevKill(worker="voice"),
    ]


def build_samples() -> dict[str, Any]:
    """One valid wire message per event and command type, plus one snapshot."""
    samples: dict[str, Any] = {}
    for event in _sample_events():
        message = _msg(event)
        samples[message["event"]["type"]] = message
    for command in _sample_commands():
        message = CommandMsg.model_validate({"command": command}).model_dump(
            mode="json"
        )
        samples[message["command"]["type"]] = message
    row = TranscriptRow(
        row_id="6", kind="user", text="what is the time", turn_id="t1", ts_ns=TS0
    )
    snapshot = Snapshot(
        presence="listening", rows=[row], conversation_id="conv-1", last_seq=24
    )
    samples["snapshot"] = SnapshotMsg(snapshot=snapshot).model_dump(mode="json")
    return samples


_TURNS: list[tuple[str, str, str]] = [
    ("good morning snow", "Good morning. Ready when you are.", "warm"),
    ("what is on my calendar today", "Two meetings: standup at ten.", "neutral"),
    ("move design to three", "Done. Design is now at three.", "neutral"),
    ("remind me to call mum", "I will remind you at six.", "warm"),
    (
        "read me the last commit message",
        "The last commit says fix the retry",
        "neutral",
    ),
    ("never mind", "Okay.", "neutral"),
    ("open the project folder", "Opening it now.", "neutral"),
    ("summarise yesterday's notes", "You planned the hub contract.", "neutral"),
    ("how long until my next meeting", "About forty minutes.", "neutral"),
    ("turn the volume down a bit", "Lowered to thirty percent.", "neutral"),
    ("that was a long day", "It was. You shipped the whole catalog.", "warm"),
    ("thanks snow that is all", "Anytime. Talk later.", "warm"),
]


def build_stream() -> list[dict[str, Any]]:
    """Fixed 12-turn dialogue: an interrupted reply, an LLM switch, an STT fallback."""
    out: list[dict[str, Any]] = []
    n = 0

    def add(
        cls: type[Envelope], source: str, turn: str | None = None, **kw: Any
    ) -> None:
        nonlocal n
        n += 1
        event = _mk(cls, n, source, **kw, turn_id=turn, correlation_id="conv-1")
        out.append(_msg(event))

    def number_durable() -> None:
        """Renumber seq so durable events count 1..N regardless of ephemeral gaps."""
        seq = 0
        for m in out:
            ev = m["event"]
            if ev["seq"] is not None:
                seq += 1
                ev["seq"] = seq

    add(WakeDetected, "voice", score=0.95, model="hey_snow")
    add(ConversationStarted, "voice", trigger="wake")
    add(PresenceState, "voice", state="listening", mode="awake")
    for i, (user, reply, emotion) in enumerate(_TURNS, start=1):
        turn = f"turn-{i}"
        if i == 9:
            add(SttStatus, "voice", stt_source="local", status_reason="unreachable")
        if i == 7:
            add(
                LlmSwitch,
                "brain",
                role="brain",
                from_provider="experiential",
                from_model="gpt-5.6-luna",
                to_provider="google",
                to_model="gemini-flash",
                switch_reason="rate_limit",
            )
        stt = "local" if i >= 9 else "groq"
        add(TranscriptPartial, "voice", turn, text=user.split()[0])
        add(TranscriptFinal, "voice", turn, text=user, stt_source=stt, tone=_TONE)
        add(PresenceState, "voice", state="thinking", mode="awake")
        add(ReplyDelta, "brain", turn, text=reply.split()[0])
        add(
            ReplyFinal,
            "brain",
            turn,
            text=reply,
            emotion=emotion,
            big_moment=i == 12,
            reply_source="llm",
            provider="experiential",
            model="gpt-5.6-luna",
        )
        add(PresenceState, "voice", state="speaking", mode="awake")
        add(AudioLevel, "voice", turn, channel="tts", level=0.5)
        if i == 5:
            add(ReplyInterrupted, "voice", turn, spoken_text="The last commit says fix")
            add(TurnCancelled, "voice", turn, cancel_reason="barge_in")
        else:
            add(TtsSpoken, "voice", turn, engine="pocket_tts", chars=len(reply))
        add(PresenceState, "voice", state="listening", mode="awake")
    add(ConversationEnded, "voice", end_reason="phrase")
    add(PresenceState, "voice", state="sleeping", mode="awake")
    number_durable()
    return out


def render() -> dict[Path, str]:
    """Every generated file, keyed by path relative to the repository root."""
    schema = TypeAdapter(WireMessage).json_schema()  # pyright: ignore[reportInvalidTypeArguments]
    stream = "".join(
        json.dumps(m, sort_keys=True, separators=(",", ":")) + "\n"
        for m in build_stream()
    )
    return {
        SCHEMA_PATH: json.dumps(schema, indent=2, sort_keys=True) + "\n",
        SAMPLES_PATH: json.dumps(build_samples(), indent=2, sort_keys=True) + "\n",
        STREAM_PATH: stream,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m snow.contracts.export")
    parser.add_argument("--check", action="store_true", help="fail if files are stale")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="repo root",
    )
    args = parser.parse_args(argv)

    stale: list[Path] = []
    for rel, text in render().items():
        path: Path = args.root / rel
        if args.check:
            # Compare line-ending-insensitively: git may check files out with CRLF.
            current = (
                path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else None
            )
            if current != text.encode("utf-8"):
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
    for rel in stale:
        print(f"stale: {rel.as_posix()}")  # noqa: T201 - CLI output
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
