"""Speaker verification: the DPAPI voiceprint store, the TitaNet verifier, its config
and its place in the barge-in check. The real model runs only when it was fetched
(`SpeakerVerifier.load`); everything else uses a fake extractor or a fake verifier."""

import asyncio
import logging
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from snow.config.settings import repo_root
from snow.contracts.events import ReplyInterrupted
from snow.voice.config import SpeakerConfig
from snow.voice.sources import read_wav
from snow.voice.speaker import (
    SpeakerVerifier,
    delete_voiceprint,
    load_voiceprint,
    save_voiceprint,
)
from snow.voice.tts.kokoro import ensure_pinned
from tests.voice.conftest import CFG, FakeGroq, until
from tests.voice.test_bargein import (
    HoldEngine,
    ask,
    make_rig,
    playout_of,
    start_reply,
    verdict_in,
)
from tests.voice.test_tts_pipeline import of

SPEAKER = CFG.speaker
MODEL = repo_root() / "models" / "speaker" / SPEAKER.model_url.rsplit("/", 1)[-1]
CLIP = Path(__file__).resolve().parents[1] / "fixtures" / "audio" / "tone_calm.wav"


def unit(*values: float) -> np.ndarray:
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


# --- the voiceprint store -----------------------------------------------------------


def test_the_voiceprint_round_trips_through_dpapi_and_holds_no_plaintext(
    tmp_path: Path,
) -> None:
    path = tmp_path / "voice" / "voiceprint.bin"
    centroid = unit(*np.random.default_rng(1).normal(size=192))
    save_voiceprint(centroid, 0.41, path)

    raw = path.read_bytes()
    assert b"centroid" not in raw and b"threshold" not in raw
    loaded = load_voiceprint(path, dim=192)
    assert loaded is not None
    assert loaded.threshold == pytest.approx(0.41)
    assert np.allclose(loaded.centroid, centroid, atol=1e-6)
    assert not list(path.parent.glob("*.tmp"))  # the temp file was replaced


def test_a_corrupt_missing_or_wrong_size_voiceprint_loads_as_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="snow.voice")
    path = tmp_path / "voiceprint.bin"
    assert load_voiceprint(path) is None  # missing

    path.write_bytes(b"not a dpapi blob")
    assert load_voiceprint(path) is None

    save_voiceprint(unit(1, 2, 3, 4), 0.4, path)
    assert load_voiceprint(path, dim=192) is None  # wrong dimension
    assert load_voiceprint(path, dim=4) is not None
    assert "voiceprint_unreadable kind=" in caplog.text


def test_deleting_a_voiceprint_reports_whether_there_was_one(tmp_path: Path) -> None:
    path = tmp_path / "voiceprint.bin"
    assert delete_voiceprint(path) is False
    save_voiceprint(unit(1, 2), 0.4, path)
    assert delete_voiceprint(path) is True
    assert not path.exists() and delete_voiceprint(path) is False


# --- the verifier -------------------------------------------------------------------


def verifier(tmp_path: Path, enrolled: np.ndarray | None) -> SpeakerVerifier:
    store = tmp_path / "voiceprint.bin"
    if enrolled is not None:
        save_voiceprint(enrolled, 0.5, store)
    v = SpeakerVerifier(SPEAKER, models_dir=tmp_path, store=store)
    v._print = load_voiceprint(store)  # noqa: SLF001 - as load() does after the model
    return v


def test_score_is_none_without_a_voiceprint_and_the_cosine_with_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="snow.voice")
    pcm = np.zeros(16000, dtype=np.int16)
    none = verifier(tmp_path, None)
    monkeypatch.setattr(none, "embed", lambda _pcm: unit(1, 0, 0))
    assert none.score(pcm) is None
    assert none.enrolled is False and none.threshold == SPEAKER.threshold

    (tmp_path / "x").mkdir()
    v = verifier(tmp_path / "x", unit(1, 0, 0))
    monkeypatch.setattr(v, "embed", lambda _pcm: unit(1, 1, 0))
    assert v.score(pcm) == pytest.approx(np.sqrt(0.5), abs=1e-6)
    assert v.enrolled is True
    assert v.threshold == pytest.approx(0.5)  # the calibrated one, not the config's
    assert v.voiceprint_on_disk() is True
    assert "0.7071" not in caplog.text and "centroid" not in caplog.text


@pytest.mark.skipif(
    not MODEL.is_file(), reason="models/speaker is fetched on first load"
)
def test_the_real_model_gives_a_deterministic_192_unit_vector(tmp_path: Path) -> None:
    v = SpeakerVerifier(SPEAKER, store=tmp_path / "none.bin")
    v.load()
    assert (
        v.dim == 192 and v.enrolled is False and v.score(read_wav(CLIP, 16000)) is None
    )
    pcm = read_wav(CLIP, 16000)
    a, b = v.embed(pcm), v.embed(pcm)
    assert a.shape == (192,)
    assert float(np.linalg.norm(a)) == pytest.approx(1.0, abs=1e-5)
    assert np.allclose(a, b, atol=1e-5)


def test_the_model_download_is_pinned_and_https_only(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="https"):
        ensure_pinned("http://example.invalid/m.onnx", "0" * 64, tmp_path / "m.onnx")


# --- config -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"calibration_lines": []},
        {"calibration_lines": ["  "]},
        {"model_url": "http://example.invalid/m.onnx"},
        {"threshold": 0.9},
        {"threshold": 0.1},
        {"min_margin": 0.0},
    ],
)
def test_a_bad_speaker_config_fails_at_load(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SpeakerConfig.model_validate({**SPEAKER.model_dump(), **bad})


def test_the_live_speaker_config_is_valid_and_has_calibration_lines() -> None:
    assert SPEAKER.calibration_lines
    assert not any("snow" in line.lower() for line in SPEAKER.calibration_lines)


# --- the barge-in check with a verifier ---------------------------------------------


class FakeSpeaker:
    """A SpeakerCheck: the model needs `load()`; the voiceprint is on disk or not."""

    def __init__(
        self,
        score: float | None = 0.9,
        *,
        on_disk: bool = True,
        load_error: bool = False,
        score_error: bool = False,
        threshold: float = 0.35,
    ) -> None:
        self._score, self._on_disk = score, on_disk
        self._load_error, self._score_error = load_error, score_error
        self._threshold = threshold
        self.loaded = False
        self.load_called = False
        self.scored: list[int] = []

    @property
    def enrolled(self) -> bool:
        return self.loaded and self._on_disk and self._score is not None

    @property
    def threshold(self) -> float:
        return self._threshold

    def voiceprint_on_disk(self) -> bool:
        return self._on_disk

    def load(self) -> None:
        self.load_called = True
        if self._load_error:
            raise RuntimeError("no model")
        self.loaded = True

    def score(self, pcm: np.ndarray) -> float | None:
        self.scored.append(len(pcm))
        if self._score_error:
            raise RuntimeError("bad window")
        return self._score if self.enrolled else None


async def one_word(
    groq: FakeGroq,
    speaker: FakeSpeaker | None,
    word: str,
    caplog: pytest.LogCaptureFixture,
):
    """Snow speaks; the user says `word` over it and goes quiet. Returns the rig after
    the check's verdict reached the engine."""
    caplog.set_level(logging.INFO, logger="snow.voice")
    rig = await make_rig(groq, HoldEngine(hold_from=2), speaker=speaker)
    if speaker is not None:
        await until(lambda: speaker.load_called)
        await asyncio.sleep(0.05)  # the load task logs its outcome
    turn_id = await ask(rig)
    await start_reply(rig, turn_id, blocks=30)
    rig.local.heard = word
    rig.hear(320, speech=True)  # the pause
    rig.hear(15 * 32, speech=False)  # quiet: the episode is checked once
    rig.pump(10)
    await verdict_in(rig)
    rig.hear(32, speech=False)  # the engine applies the verdict
    return rig


async def test_a_voice_that_is_not_the_users_never_cuts_snow_off(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    speaker = FakeSpeaker(score=0.1)
    rig = await one_word(groq, speaker, "please stop and listen to me", caplog)
    assert speaker.scored, "the window was scored"
    assert not playout_of(rig)._paused  # noqa: SLF001 - the reply resumed
    assert rig.aborts == [] and of(rig.hub, ReplyInterrupted) == []
    assert "reason=speaker" in caplog.text and "score=0.1" in caplog.text


async def test_the_verified_user_stops_snow_with_one_word(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    rig = await one_word(groq, FakeSpeaker(score=0.8), "Stop.", caplog)
    assert rig.aborts, "playback was cut"
    assert "reason=ok" in caplog.text and "score=0.8" in caplog.text


async def test_the_same_one_word_without_a_voiceprint_resumes(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    for speaker in (None, FakeSpeaker(on_disk=False)):  # no verifier / not enrolled
        rig = await one_word(groq, speaker, "Stop.", caplog)
        assert not playout_of(rig)._paused  # noqa: SLF001
        assert rig.aborts == []
        assert "reason=words" in caplog.text
    assert "score=None" in caplog.text


async def test_without_a_voiceprint_two_words_still_cut_in_degraded_mode(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    rig = await one_word(groq, FakeSpeaker(on_disk=False), "wait a moment", caplog)
    assert rig.aborts
    assert "reason=ok" in caplog.text


async def test_an_enrolled_user_whose_model_failed_to_load_is_never_cut_by_talk(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    # fail closed: the voiceprint is on disk but the verifier is not up
    speaker = FakeSpeaker(load_error=True)
    rig = await one_word(groq, speaker, "stop right now please", caplog)
    assert speaker.scored == [], "nothing can be scored"
    assert not playout_of(rig)._paused  # noqa: SLF001
    assert rig.aborts == []
    assert "speaker_verify unavailable kind=RuntimeError" in caplog.text
    assert "reason=speaker" in caplog.text


async def test_a_scoring_error_fails_closed(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    rig = await one_word(
        groq, FakeSpeaker(score_error=True), "stop right now please", caplog
    )
    assert rig.aborts == []
    assert "speaker_score_failed kind=RuntimeError" in caplog.text
    assert "reason=speaker" in caplog.text


async def test_the_voiceprint_never_reaches_the_logs(
    groq: FakeGroq, caplog: pytest.LogCaptureFixture
) -> None:
    await one_word(groq, FakeSpeaker(score=0.8), "Stop.", caplog)
    assert "centroid" not in caplog.text and "voiceprint" not in caplog.text.replace(
        "voiceprint_unreadable", ""
    )
