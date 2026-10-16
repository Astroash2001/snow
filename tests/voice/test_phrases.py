"""Voice commands match only a whole short utterance (T-01-24)."""

import pytest

from snow.config.settings import load_config
from snow.voice.config import VoiceConfig
from snow.voice.phrases import match_command

PHRASES = load_config("voice.toml", VoiceConfig).phrases


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("that's all", "end"),
        ("That's all.", "end"),
        ("That’s all!", "end"),
        ("thanks, that's all", "end"),
        ("snow go to sleep", "sleep"),
        ("Snow, go to sleep.", "sleep"),
        ("go to sleep", "sleep"),
        ("mute", "mute"),
        ("Snow, mute.", "mute"),
        ("mute yourself", "mute"),
        # A request that merely contains a command is not a command.
        ("mute the speaker in the call", None),
        ("go to sleep now please thanks a lot okay", None),  # over 6 words
        ("please don't go to sleep on me", None),
        ("what does mute mean", None),
        ("", None),
        ("snow", None),
    ],
)
def test_match_command(heard: str, expected: str | None) -> None:
    assert match_command(heard, PHRASES) == expected
