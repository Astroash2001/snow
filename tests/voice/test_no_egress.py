"""VOIC-01 and D-18: idle audio never leaves the PC and no audio is written to disk.

No real network is involved: the pipeline runs on an in-memory FakeHub and a fail-closed
Groq MockTransport, and every socket connect is recorded and refused.
"""

import io
import socket
import tempfile
import wave
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import SnowDirs
from tests.voice.conftest import FakeGroq, RunFixture

AUDIO_SUFFIXES = {".wav", ".pcm", ".raw", ".flac", ".mp3"}


class Egress:
    def __init__(self) -> None:
        self.connects: list[object] = []
        self.wave_writes: list[object] = []


@pytest.fixture
async def egress(
    monkeypatch: pytest.MonkeyPatch,
) -> Egress:  # async: the loop exists first
    seen = Egress()

    def refuse(*args: Any, **_: Any) -> None:
        seen.connects.append(args[1:] if args else ())
        raise OSError("network is closed in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    real_open = wave.open

    def spy(f: Any, mode: str | None = None, *a: Any, **k: Any) -> Any:
        if mode and mode.startswith("w"):
            seen.wave_writes.append(f)
        return real_open(f, mode, *a, **k)

    monkeypatch.setattr(wave, "open", spy)
    return seen


def audio_files(*roots: Path, deep: bool) -> set[Path]:
    found: set[Path] = set()
    for root in roots:
        if root.exists():
            walk = root.rglob("*") if deep else root.glob("*")
            found |= {p for p in walk if p.suffix.lower() in AUDIO_SUFFIXES}
    return found


async def test_no_wake_means_no_connection_and_no_groq_request(
    groq: FakeGroq, run_fixture: RunFixture, egress: Egress
) -> None:
    run = await run_fixture("tv_negative", "should never be asked")
    assert run.hub.events == []
    assert groq.requests == []
    assert egress.connects == []
    assert egress.wave_writes == []  # no turn audio was even assembled


async def test_a_wake_turn_makes_exactly_one_groq_request_and_no_file(
    groq: FakeGroq,
    run_fixture: RunFixture,
    egress: Egress,
    snow_dirs: SnowDirs,
    tmp_path: Path,
) -> None:
    deep, shallow = (
        [snow_dirs.data, tmp_path],
        [Path.cwd(), Path(tempfile.gettempdir())],
    )
    before = audio_files(*deep, deep=True), audio_files(*shallow, deep=False)
    run = await run_fixture("wake_cmd_gap150", "Hey Jarvis, what time is it?")
    assert "transcript.final" in run.hub.types()
    assert len(groq.requests) == 1
    assert egress.connects == []  # the upload went through the injected transport
    # The turn went up as a WAV built in memory, and nothing else was ever written.
    assert egress.wave_writes
    assert all(isinstance(f, io.BytesIO) for f in egress.wave_writes)
    after = audio_files(*deep, deep=True), audio_files(*shallow, deep=False)
    assert after == before
