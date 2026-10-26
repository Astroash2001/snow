"""The barge-in decision: words, Snow's own echo, speaker. Pure, on the UAT phrases."""

import pytest
from pydantic import ValidationError

from snow.voice.bargein import decide, echo_ratio, words
from snow.voice.config import BargeCheckConfig
from tests.voice.conftest import CFG

CHECK = CFG.barge_check
SAID = "Certainly. It is ten past four, sir. Understood, sir."
THRESHOLD = 0.35


def test_words_are_lowercase_alphanumerics_with_apostrophes() -> None:
    assert words("Stop, it's 4 PM!") == ["stop", "it's", "4", "pm"]
    assert words("") == []


def test_echo_ratio_is_the_in_order_share_of_heard_words_found_in_said() -> None:
    assert echo_ratio("", SAID) == 0.0
    assert echo_ratio("understood sir", SAID) == 1.0
    assert echo_ratio("understood sir ten", SAID) == pytest.approx(2 / 3)
    assert echo_ratio("tell me about germany", SAID) == 0.0


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("Peace.", "words"),  # a cough: one word, no voiceprint
        ("Stop.", "words"),  # still one word without a voiceprint
        ("", "words"),
        ("stop, tell me about Germany instead", "ok"),
        ("Certainly.", "words"),  # the word floor runs before the echo filter
        ("Understood, sir.", "echo"),  # Snow heard itself
    ],
)
def test_without_a_voiceprint_two_real_words_that_are_not_snow_cut(
    heard: str, expected: str
) -> None:
    assert decide(None, 0.0, heard, SAID, CHECK) == expected


@pytest.mark.parametrize(
    ("heard", "score", "expected"),
    [
        ("Stop.", 0.6, "ok"),  # a verified user stops Snow with one word
        ("Wait.", 0.6, "ok"),
        ("", 0.6, "words"),
        ("Certainly.", 0.6, "echo"),  # a verified single word that repeats Snow
        ("Stop.", 0.2, "speaker"),
        ("stop tell me about Germany instead", 0.2, "speaker"),
        ("Stop.", THRESHOLD, "ok"),  # at the threshold passes
    ],
)
def test_a_verified_voice_needs_one_word_and_not_snows_own(
    heard: str, score: float, expected: str
) -> None:
    assert decide(score, THRESHOLD, heard, SAID, CHECK) == expected


def test_nothing_said_means_nothing_to_echo() -> None:
    assert decide(0.6, THRESHOLD, "Stop.", "", CHECK) == "ok"


@pytest.mark.parametrize(
    "update",
    [
        {"min_words_verified": 0},
        {"min_words_verified": 3, "min_words_unverified": 2},
    ],
)
def test_bad_word_floors_fail_at_load(update: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        BargeCheckConfig(**{**CHECK.model_dump(), **update})
