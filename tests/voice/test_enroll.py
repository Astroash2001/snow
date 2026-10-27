"""`snow dev enroll-voice`: the running-Snow guard, segmenting, calibration and the
tool's exit paths. The recordings and the TitaNet model are faked (constant-level
audio whose level says whose voice it is); nothing opens a microphone, a speaker or
the network."""

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from snow.config.settings import run_dir
from snow.voice import enroll
from snow.voice.speaker import load_voiceprint, save_voiceprint, voiceprint_path
from tests.voice.conftest import CFG

RATE = 16000
SPEAKER = CFG.speaker
USER, SNOW, TV = 1000, 2000, 3000  # the level of each voice in the fake recordings


def tone(level: int, seconds: float) -> np.ndarray:
    return np.full(int(seconds * RATE), level, dtype=np.int16)


def silence(seconds: float) -> np.ndarray:
    return tone(0, seconds)


class FakeVerifier:
    """Embeds by level: the user is (1, 0); Snow sits `snow_cosine` away from it."""

    def __init__(self, snow_cosine: float) -> None:
        self.snow = np.array([snow_cosine, np.sqrt(1 - snow_cosine**2)], np.float32)
        self.embedded = 0

    def embed(self, pcm: np.ndarray) -> np.ndarray:
        self.embedded += 1
        level = int(np.abs(pcm).max())
        return np.array([1, 0], np.float32) if level == USER else self.snow


@pytest.fixture(autouse=True)
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SNOW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(enroll, "_countdown", lambda: None)
    return tmp_path


def tool(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snow_cosine: float = 0.1,
    mine: np.ndarray | None = None,
    running: bool = False,
    lines: list[str] | None = None,
) -> dict[str, list[object]]:
    """Fakes everything that touches the world; returns what the tool asked for."""
    calls: dict[str, list[object]] = {"say": [], "record": [], "verifier": []}
    cfg = CFG
    if lines is not None:
        cfg = CFG.model_copy(
            update={"speaker": SPEAKER.model_copy(update={"calibration_lines": lines})}
        )
    monkeypatch.setattr(enroll, "load_config", lambda *_a: cfg)
    monkeypatch.setattr(enroll, "snow_is_running", lambda: running)

    def play(text: str) -> np.ndarray:
        calls["say"].append(text)
        return tone(SNOW, 12)

    def rec(seconds: float) -> np.ndarray:
        calls["record"].append(seconds)
        if seconds < 10:  # the TV recording
            return tone(TV, seconds)
        return mine if mine is not None else np.concatenate([tone(USER, 30)])

    def verifier(_cfg: object) -> FakeVerifier:
        calls["verifier"].append(1)
        return FakeVerifier(snow_cosine)

    monkeypatch.setattr(enroll, "play_and_capture", play)
    monkeypatch.setattr(enroll, "record", rec)
    monkeypatch.setattr(enroll, "_load_verifier", verifier)
    return calls


# --- the guard ----------------------------------------------------------------------


def hub_json(pid: int) -> None:
    run_dir().mkdir(parents=True, exist_ok=True)
    (run_dir() / "hub.json").write_text(
        json.dumps({"port": 1, "token": "t", "pid": pid}), encoding="utf-8"
    )


def test_snow_is_running_follows_the_hub_pid_and_touches_nothing() -> None:
    assert enroll.snow_is_running() is False  # no hub.json
    hub_json(os.getpid())
    assert enroll.snow_is_running() is True
    done = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
    done.wait()
    hub_json(done.pid)  # a stale file: its process is gone
    assert enroll.snow_is_running() is False
    (run_dir() / "hub.json").write_text("not json", encoding="utf-8")
    assert enroll.snow_is_running() is False


def test_it_refuses_while_snow_runs_before_loading_or_recording(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = tool(monkeypatch, running=True)
    assert enroll.main([]) == 2
    assert "Snow is running: quit it" in capsys.readouterr().err
    assert calls == {"say": [], "record": [], "verifier": []}
    assert not voiceprint_path().exists()


def test_reset_deletes_the_voiceprint_even_while_snow_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool(monkeypatch, running=True)
    save_voiceprint(np.array([1, 0], np.float32), 0.4)
    assert enroll.main(["--reset"]) == 0
    assert not voiceprint_path().exists()
    assert enroll.main(["--reset"]) == 0  # nothing left: still fine


# --- segmenting and calibration -----------------------------------------------------


def test_segments_keep_only_two_second_windows_with_a_second_of_speech() -> None:
    pcm = np.concatenate([tone(USER, 6), silence(4), tone(USER, 3)])
    assert (
        len(enroll.segments(pcm, RATE)) == 4
    )  # 3 + 1 whole windows; the rest is quiet
    assert enroll.segments(silence(10), RATE) == []


def test_crops_are_short_windows_at_a_half_overlap() -> None:
    crops = enroll.crops(tone(USER, 2), RATE)
    assert len(crops) == 4 and all(len(c) == int(0.8 * RATE) for c in crops)
    assert enroll.crops(silence(2), RATE) == []


def test_a_small_margin_is_refused_and_a_good_one_gets_the_clamped_midpoint() -> None:
    refused = enroll.calibrate([0.8, 0.82, 0.9], [0.1, 0.7], SPEAKER)
    assert refused.threshold is None and refused.margin == pytest.approx(
        0.8 - 0.7, abs=0.02
    )

    ok = enroll.calibrate([0.7, 0.8, 0.9], [0.1, 0.2], SPEAKER)
    assert ok.threshold == pytest.approx(0.45, abs=0.02)  # midpoint of ~0.7 and 0.2
    low = enroll.calibrate([0.5, 0.5], [-0.3, -0.2], SPEAKER)
    assert low.threshold == SPEAKER.min_threshold  # clamped up
    high = enroll.calibrate([0.99, 0.99], [0.8, 0.81], SPEAKER)
    assert high.threshold == SPEAKER.max_threshold  # clamped down


# --- the tool -----------------------------------------------------------------------


def test_a_good_margin_saves_a_voiceprint_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = tool(monkeypatch, snow_cosine=0.1)
    assert enroll.main([]) == 0
    saved = load_voiceprint()
    assert saved is not None
    assert saved.threshold == pytest.approx(0.55, abs=0.01)  # midpoint of 1.0 and 0.1
    assert np.allclose(saved.centroid, [1, 0], atol=1e-5)
    assert calls["record"] == [30]
    out = capsys.readouterr().out
    assert "margin 0.90" in out and "Restart Snow" in out
    assert "centroid" not in out  # scores only, no vector


def test_a_small_margin_saves_nothing_prints_the_numbers_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tool(monkeypatch, snow_cosine=0.9)  # Snow's voice sits right next to the user's
    assert enroll.main([]) == 1
    assert not voiceprint_path().exists()
    streams = capsys.readouterr()
    assert "margin 0.10" in streams.out and "needs 0.15" in streams.out
    assert "Sit closer" in streams.err


def test_too_little_speech_refuses_before_any_calibration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tool(monkeypatch, mine=np.concatenate([tone(USER, 12), silence(18)]))  # 6 segments
    assert enroll.main([]) == 1
    assert not voiceprint_path().exists()
    assert "only 6 usable stretches" in capsys.readouterr().err


def test_the_spoken_and_printed_lines_come_from_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = tool(monkeypatch, lines=["alpha beta gamma", "delta epsilon"])
    assert enroll.main(["--seconds", "20"]) == 0
    assert calls["say"] == ["alpha beta gamma delta epsilon"]
    out = capsys.readouterr().out
    assert "alpha beta gamma" in out and "delta epsilon" in out
    assert calls["record"] == [20]


def test_tv_audio_is_extra_impostor_material_and_clips_are_only_reported(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    calls = tool(monkeypatch, snow_cosine=0.1)
    clips = tmp_path / "clips"
    clips.mkdir()
    with wave.open(str(clips / "a.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(tone(USER, 1).tobytes())
    before = sorted(p.name for p in tmp_path.iterdir())
    assert enroll.main(["--tv-seconds", "5", "--check-clips", str(clips)]) == 0
    assert calls["record"] == [5, 30]  # TV first, then the user
    assert "Your clips (1): min 1.00, mean 1.00, max 1.00" in capsys.readouterr().out
    assert sorted(p.name for p in clips.iterdir()) == ["a.wav"]  # nothing written
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*before, "voice"])
