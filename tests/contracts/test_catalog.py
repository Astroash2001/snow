"""The committed JSON Schema and golden samples match the Pydantic catalog."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from snow.contracts.events import Event
from snow.contracts.wire import COMMAND_ROLES, WireMessage

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "contracts" / "samples"
_WIRE: TypeAdapter[Any] = TypeAdapter(WireMessage)  # pyright: ignore[reportInvalidTypeArguments]


def _export(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, our own module
        [sys.executable, "-m", "snow.contracts.export", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


def _samples() -> dict[str, Any]:
    return json.loads((SAMPLES / "events.json").read_text(encoding="utf-8"))


def test_committed_files_are_fresh() -> None:
    result = _export("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_detects_a_stale_file(tmp_path: Path) -> None:
    assert _export("--root", str(tmp_path)).returncode == 0
    assert _export("--check", "--root", str(tmp_path)).returncode == 0
    schema = tmp_path / "contracts" / "events.schema.json"
    schema.write_text(schema.read_text(encoding="utf-8") + " ", encoding="utf-8")
    result = _export("--check", "--root", str(tmp_path))
    assert result.returncode == 1
    assert "events.schema.json" in result.stdout


def test_every_sample_validates_as_a_wire_message() -> None:
    samples = _samples()
    for name, sample in samples.items():
        assert _WIRE.validate_python(sample) is not None, name


def test_samples_cover_every_event_and_command_type() -> None:
    event_types = {
        cls.model_fields["type"].default for cls in get_args(get_args(Event)[0])
    }
    expected = event_types | set(COMMAND_ROLES) | {"snapshot"}
    assert set(_samples()) == expected


def test_sample_with_an_unknown_extra_field_is_rejected() -> None:
    sample = _samples()["transcript.final"]
    sample["event"]["surprise"] = 1
    with pytest.raises(ValidationError):
        _WIRE.validate_python(sample)


def test_conversation_stream_is_a_valid_scripted_dialogue() -> None:
    lines = (SAMPLES / "conversation-12.jsonl").read_text(encoding="utf-8").splitlines()
    messages = [json.loads(line) for line in lines]
    for m in messages:
        _WIRE.validate_python(m)
    types = [m["event"]["type"] for m in messages]
    assert len(lines) >= 30
    assert types.count("transcript.final") == 12
    for needed in (
        "reply.interrupted",
        "llm.switch",
        "stt.status",
        "conversation.ended",
    ):
        assert needed in types
    assert types[0] == "wake.detected"
    seqs = [m["event"]["seq"] for m in messages if m["event"]["seq"] is not None]
    assert seqs == list(range(1, len(seqs) + 1))
