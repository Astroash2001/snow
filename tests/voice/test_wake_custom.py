"""A custom wake model by path, pinned by SHA-256 (VOIC-01, T-01-45), and the
negatives recorder's folder rule (T-01-46). The hey_jarvis ONNX file copied to a temp
path stands in for the user's trained "hey snow" model."""

import asyncio
import hashlib
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from snow.config.settings import repo_root
from snow.voice import record_negatives
from snow.voice.sources import read_wav
from snow.voice.wake import WakeGate, model_files
from tests.voice.conftest import AUDIO, CFG, FakeHub, StubSource, make_pipeline


@pytest.fixture
def custom_model(tmp_path: Path, wake_models: None) -> tuple[str, str]:
    """(absolute path, sha256) of a stand-in custom model."""
    path = tmp_path / "hey_custom.onnx"
    shutil.copyfile(model_files("hey_jarvis")[0], path)
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def gate(model: str, sha: str) -> WakeGate:
    w = CFG.wake
    return WakeGate(
        model,
        w.threshold,
        w.patience_frames,
        w.preroll_frames,
        w.refractory_s,
        model_sha256=sha,
    )


def fires(g: WakeGate, name: str) -> int:
    pcm = read_wav(AUDIO / f"{name}.wav", CFG.audio.sample_rate)
    step = CFG.audio.frame_samples
    return sum(
        g.process(pcm[i : i + step]) is not None
        for i in range(0, len(pcm) - step, step)
    )


def test_path_model_with_matching_checksum_loads_and_fires(
    custom_model: tuple[str, str],
) -> None:
    path, sha = custom_model
    g = gate(path, sha.upper())  # certutil prints upper case
    assert g.error is None
    assert g.name == "hey_custom"
    assert fires(g, "wake_only") == 1
    assert fires(g, "tv_negative") == 0


def test_checksum_mismatch_is_refused(custom_model: tuple[str, str]) -> None:
    g = gate(custom_model[0], "0" * 64)
    assert g.error == "Wake model checksum mismatch"
    assert fires(g, "wake_only") == 0  # deaf, not crashed


def test_path_without_a_checksum_is_refused(custom_model: tuple[str, str]) -> None:
    assert gate(custom_model[0], "").error == "Wake model checksum mismatch"


def test_missing_model_is_refused(tmp_path: Path, wake_models: None) -> None:
    g = gate(str(tmp_path / "nope.onnx"), "0" * 64)
    assert g.error == "Wake model missing"
    g.reset()  # still safe to use


async def test_refused_model_reports_wake_word_down(tmp_path: Path) -> None:
    hub = FakeHub()
    pipeline = make_pipeline(hub, StubSource())
    pipeline._wake = gate(str(tmp_path / "nope.onnx"), "")  # pyright: ignore[reportPrivateUsage]
    await pipeline.start(listen=False)
    await pipeline.wait_done()
    rows = [(h.status, h.detail) for h in hub.health if h.name == "wake_word"]
    assert rows[-1] == ("down", "Wake model missing")
    pipeline.mic_health(True)  # a working mic does not hide the refused model
    await asyncio.sleep(0.05)
    await pipeline.wait_done()
    rows = [(h.status, h.detail) for h in hub.health if h.name == "wake_word"]
    assert rows[-1] == ("down", "Wake model missing")
    await pipeline.stop()


@pytest.mark.parametrize("inside", ["repo", "data"])
def test_record_negatives_refuses_repo_and_data_folders(
    inside: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "snowdata"
    monkeypatch.setenv("SNOW_DATA_DIR", str(data))
    out = (repo_root() if inside == "repo" else data) / "negatives"
    assert record_negatives.main(["--minutes", "1", "--out", str(out)]) == 2
    assert not out.exists()


def test_record_negatives_allows_an_outside_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SNOW_DATA_DIR", str(tmp_path / "snowdata"))
    outside = Path(repo_root().anchor) / "SnowNegatives"  # never created here
    assert record_negatives.refuse_reason(outside) is None


def test_write_chunks_rotates_files(tmp_path: Path) -> None:
    frames = [np.full(1280, i, dtype=np.int16) for i in range(10)]  # 12 800 samples
    written = record_negatives.write_chunks(frames, tmp_path, rate=1000, file_s=5)
    lengths = []
    for path in written:
        with wave.open(str(path), "rb") as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (
                1,
                2,
                1000,
            )
            lengths.append(w.getnframes())
    assert lengths == [5000, 5000, 2800]
