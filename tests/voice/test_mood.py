"""SPCH-02, D-05, D-34: the reply emotion picks a mood clip of the everyday voice, every
reference clip carries a consent tag, and `snow dev audition-voices` writes the pick.

Nothing real is contacted or played: Cartesia's REST API is an `httpx2.MockTransport`
(respx does not intercept httpx2), synthesis and playback are fakes, the key is a fake,
and the tool edits a temp copy of tts.toml. No Cartesia credits are spent.
"""

import tomllib
from pathlib import Path
from typing import Any

import httpx2
import numpy as np
import pytest
from pydantic import ValidationError

from snow.cli import main as cli_main
from snow.config.secrets import Secret
from snow.config.settings import repo_root
from snow.voice.audition import Tools, main, set_line, shortlist
from snow.voice.tts.config import PocketConfig, TtsConfig
from snow.voice.tts.pocket import PocketEngine

TTS_TOML = repo_root() / "config" / "tts.toml"
KEY = "sk_car_test-key-not-real"


def clip(path: str, consent: str = "licensed_preset") -> dict[str, str]:
    return {"path": path, "consent": consent}


def pocket_cfg(**changes: Any) -> PocketConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "reference": clip("base"),
        "torch_threads": 1,
        "moods": {"sympathetic": clip("clips/sym.wav", "self")},
        "emotion_to_mood": {"sympathetic": "sympathetic", "excited": "upbeat"},
    }
    return PocketConfig.model_validate({**base, **changes})


# --- emotion -> mood -----------------------------------------------------------------


def test_emotions_map_to_moods_and_an_unknown_one_is_calm() -> None:
    cfg = TtsConfig.model_validate(tomllib.loads(TTS_TOML.read_text("utf-8")))
    pocket = cfg.engines.pocket_tts
    expected = {
        "neutral": "calm",
        "content": "upbeat",
        "calm": "calm",
        "curious": "playful",
        "sympathetic": "sympathetic",
        "excited": "upbeat",
        "no-such-emotion": "calm",
    }
    assert {e: pocket.mood_for(e) for e in expected} == expected


class FakeTensor:
    def __init__(self, data: np.ndarray[Any, Any]) -> None:
        self._data = data

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> np.ndarray[Any, Any]:
        return self._data


class FakeModel:
    """The slice of pocket_tts.TTSModel the engine uses. Clips named 'broken' fail."""

    sample_rate = 24000

    def __init__(self) -> None:
        self.spoken: list[tuple[str, str]] = []

    def get_state_for_audio_prompt(self, path: str) -> str:
        if path == "broken":
            raise ValueError("needs the voice cloning weights")
        return f"state:{path}"

    def generate_audio_stream(self, voice: str, text: str, stop: Any = None):  # noqa: ANN201
        self.spoken.append((voice, text))
        yield FakeTensor(np.full(240, 0.1, dtype=np.float32))


def loaded(cfg: PocketConfig) -> tuple[PocketEngine, FakeModel]:
    engine, model = PocketEngine(cfg), FakeModel()
    engine._model = model  # noqa: SLF001 - skip the real model download
    engine._state(cfg.reference.path)  # noqa: SLF001
    engine._load_moods()  # noqa: SLF001
    return engine, model


async def speak(engine: PocketEngine, emotion: str) -> None:
    assert [c async for c in engine.stream("Hello there.", emotion)]


async def test_the_emotion_selects_the_voice_state_of_its_mood_clip() -> None:
    engine, model = loaded(pocket_cfg())
    await speak(engine, "sympathetic")
    assert model.spoken == [("state:clips/sym.wav", "Hello there.")]


async def test_a_mood_without_a_clip_uses_the_base_voice() -> None:
    engine, model = loaded(pocket_cfg())
    await speak(engine, "excited")  # upbeat has no clip
    await speak(engine, "unheard-of")  # calm has no clip
    assert [v for v, _ in model.spoken] == ["state:base", "state:base"]


async def test_a_clip_that_cannot_load_falls_back_to_the_base_voice() -> None:
    engine, model = loaded(pocket_cfg(moods={"sympathetic": clip("broken", "self")}))
    await speak(engine, "sympathetic")
    assert model.spoken == [("state:base", "Hello there.")]


async def test_one_state_is_built_per_distinct_clip() -> None:
    cfg = pocket_cfg(moods={"calm": clip("base"), "upbeat": clip("base")})
    engine, _ = loaded(cfg)
    assert list(engine._states) == ["base"]  # noqa: SLF001


# --- consent -------------------------------------------------------------------------


def test_the_shipped_config_tags_every_clip_with_consent() -> None:
    pocket = TtsConfig.model_validate(tomllib.loads(TTS_TOML.read_text("utf-8")))
    clips = [
        pocket.engines.pocket_tts.reference,
        *pocket.engines.pocket_tts.moods.values(),
    ]
    assert len(clips) == 6 and all(c.consent == "licensed_preset" for c in clips)


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"moods": {"playful": {"path": "friend.wav"}}}, "playful"),
        ({"moods": {"playful": clip("a.wav", "stolen")}}, "playful"),
        ({"reference": {"path": "voice.wav"}}, "reference"),
        ({"reference": clip("voice.wav", "")}, "reference"),
    ],
)
def test_a_clip_without_a_valid_consent_tag_is_refused(
    changes: dict[str, Any], named: str
) -> None:
    with pytest.raises(ValidationError) as refused:
        pocket_cfg(**changes)
    assert named in str(refused.value) and "consent" in str(refused.value)


# --- the audition --------------------------------------------------------------------

LINE = "Good evening. This is how I sound, so tell me whether it suits you."


def stock_voice(
    i: int, name: str, gender: str = "masculine", lang: str = "en"
) -> dict[str, Any]:
    return {
        "id": f"id-{i}",
        "name": name,
        "gender": gender,
        "language": lang,
        "description": "A British voice" if name == "Archie" else "A voice",
    }


VOICES = [
    stock_voice(0, "Skylar", "feminine"),
    stock_voice(1, "Fabio", lang="it"),
    stock_voice(2, "Ronald"),
    stock_voice(3, "Archie"),
    stock_voice(4, "Daniel"),
    *[stock_voice(5 + i, f"Extra{i}") for i in range(10)],
]


class Session:
    """A scripted user, a recording speaker and a fake Cartesia."""

    def __init__(
        self, answers: list[str], voices: list[dict[str, Any]] = VOICES
    ) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.said: list[str] = []
        self.played: list[tuple[int, int]] = []
        self.synthesised: list[tuple[str, str]] = []
        self.requests: list[httpx2.Request] = []
        self.voices = voices

    def rest(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == "/voices":
            return httpx2.Response(200, json={"data": self.voices, "has_more": False})
        return httpx2.Response(599)  # anything else is a violation

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)

    async def cartesia(self, voice_id: str, emotion: str) -> Any:
        self.synthesised.append((voice_id, emotion))
        return np.zeros(10, dtype=np.float32)

    async def pocket(self, path: str) -> Any:
        self.synthesised.append((path, "pocket"))
        return np.zeros(10, dtype=np.float32), 24000

    def tools(self) -> Tools:
        return Tools(
            ask=self.ask,
            say=self.said.append,
            play=lambda samples, rate: self.played.append((len(samples), rate)),
            secret=lambda _name: Secret(KEY),
            transport=httpx2.MockTransport(self.rest),
            cartesia_voice=self.cartesia,
            pocket_voice=self.pocket,
        )


@pytest.fixture
def tts_toml(tmp_path: Path) -> Path:
    path = tmp_path / "tts.toml"
    path.write_bytes(TTS_TOML.read_bytes())
    return path


def changed_lines(before: bytes, after: bytes) -> list[str]:
    old, new = before.decode().splitlines(), after.decode().splitlines()
    assert len(old) == len(new)
    return [b for a, b in zip(old, new, strict=True) if a != b]


def test_set_line_rewrites_only_the_named_line_of_its_section() -> None:
    text = "[a]\nx = 1\n[b]\nx = 2  # keep?\ny = 3\r\n"
    assert set_line(text, "b", "x", "9") == "[a]\nx = 1\n[b]\nx = 9\ny = 3\r\n"
    with pytest.raises(ValueError, match="no 'z ="):
        set_line(text, "b", "z", "1")


def test_the_shortlist_puts_named_british_english_men_first_and_skips_the_rest() -> (
    None
):
    names = [v["name"] for v in shortlist(VOICES, ["Daniel", "Archie"], 8)]
    assert names[:2] == ["Archie", "Daniel"]  # both listed; the British one first
    assert "Skylar" not in names and "Fabio" not in names
    assert len(names) == 8 and names[2] == "Ronald"


def test_choosing_two_writes_that_voice_into_tts_toml_and_nothing_else(
    tts_toml: Path,
) -> None:
    before = tts_toml.read_bytes()
    s = Session(["y", "2"])
    assert main(["--cartesia", "--config", str(tts_toml)], tools=s.tools()) == 0
    # candidates, in order: Archie, Daniel (shortlist), Ronald, ...; the user picked 2
    assert changed_lines(before, tts_toml.read_bytes()) == [
        'voice_id = "id-4"',
        'voice_name = "Daniel"',
    ]
    assert [e for _, e in s.synthesised[:2]] == ["content", "neutral"]
    assert KEY not in "".join(s.said + s.prompts)
    assert all(r.headers["X-API-Key"] == KEY for r in s.requests)  # in headers only
    assert all(KEY not in str(r.url) for r in s.requests)


def test_cartesia_asks_before_spending_and_caps_at_eight(tts_toml: Path) -> None:
    before = tts_toml.read_bytes()
    s = Session(["n"])
    assert main(["--cartesia", "--config", str(tts_toml)], tools=s.tools()) == 0
    assert s.synthesised == [] and s.played == []  # declined: nothing was spoken
    assert f"{len(LINE) * 2 * 8} Cartesia credits" in s.prompts[0]
    assert tts_toml.read_bytes() == before

    s = Session(["y", ""])
    main(["--cartesia", "--config", str(tts_toml)], tools=s.tools())
    assert len({v for v, _ in s.synthesised}) == 8 and len(s.synthesised) == 16
    assert tts_toml.read_bytes() == before  # Enter at the pick keeps the config


def test_pocket_pick_writes_the_preset_and_moods_with_consent(tts_toml: Path) -> None:
    before = tts_toml.read_bytes()
    s = Session(["2", *[""] * 5])  # javert, every mood the same voice
    assert main(["--pocket", "--config", str(tts_toml)], tools=s.tools()) == 0
    after = tomllib.loads(tts_toml.read_text("utf-8"))["engines"]["pocket_tts"]
    assert after["reference"] == clip("javert")
    assert set(after["moods"]) == {
        "calm",
        "upbeat",
        "serious",
        "playful",
        "sympathetic",
    }
    assert all(m == clip("javert") for m in after["moods"].values())
    assert len(changed_lines(before, tts_toml.read_bytes())) == 6
    assert [v for v, _ in s.synthesised][:3] == [
        "marius",
        "javert",
        "george",
    ]  # every preset


def test_a_clip_with_a_consent_tag_is_accepted_and_tagged(
    tts_toml: Path, tmp_path: Path
) -> None:
    mine = tmp_path / "mine.wav"
    mine.write_bytes(b"not audio; the synthesis is a fake")
    s = Session([str(mine), "self", *[""] * 5])
    assert main(["--pocket", "--config", str(tts_toml)], tools=s.tools()) == 0
    after = tomllib.loads(tts_toml.read_text("utf-8"))["engines"]["pocket_tts"]
    assert after["reference"] == clip(str(mine), "self")
    assert after["moods"]["calm"] == clip(str(mine), "self")


@pytest.mark.parametrize("consent", ["", "the film actor", "licensed"])
def test_a_clip_without_a_valid_consent_is_refused_and_nothing_is_written(
    tts_toml: Path, tmp_path: Path, consent: str
) -> None:
    before = tts_toml.read_bytes()
    stranger = tmp_path / "somebody.wav"
    stranger.write_bytes(b"x")
    s = Session([str(stranger), consent])
    assert main(["--pocket", "--config", str(tts_toml)], tools=s.tools()) == 2
    assert tts_toml.read_bytes() == before
    assert any("consent tag" in line for line in s.said)


def test_a_mood_clip_that_cannot_be_spoken_is_not_saved(
    tts_toml: Path, tmp_path: Path
) -> None:
    sad = tmp_path / "sad.wav"
    sad.write_bytes(b"x")

    class NoCloning(Session):
        async def pocket(self, path: str) -> Any:
            if path == str(sad):
                raise ValueError("needs the voice cloning weights")
            return await super().pocket(path)

    s = NoCloning(["2", "", "", "", "", str(sad), "consenting_person"])
    assert main(["--pocket", "--config", str(tts_toml)], tools=s.tools()) == 0
    moods = tomllib.loads(tts_toml.read_text("utf-8"))["engines"]["pocket_tts"]["moods"]
    assert moods["sympathetic"] == clip("javert")


def test_audition_voices_has_a_help_screen(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as done:
        cli_main(["dev", "audition-voices", "--help"])
    assert done.value.code == 0 and "--cartesia" in capsys.readouterr().out
