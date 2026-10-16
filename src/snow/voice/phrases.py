"""Text helpers shared by the voice flow: normalization and wake-phrase stripping."""

import re
import unicodedata
from typing import Literal

from snow.voice.config import PhrasesConfig

_PUNCT = re.compile(r"[^\w\s']")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})


def normalize(text: str) -> str:
    """Lowercase, unify apostrophes, drop punctuation, collapse spaces."""
    text = unicodedata.normalize("NFKC", text).lower().translate(_APOSTROPHES)
    return " ".join(_PUNCT.sub(" ", text).split())


def strip_wake(text: str, patterns: list[str]) -> str:
    """Remove a leading wake phrase (D-09) while keeping the rest exactly as heard."""
    for pattern in patterns:
        stripped = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)
        if stripped != text:
            return stripped.strip()
    return text.strip()


Command = Literal["end", "sleep", "mute"]
_MAX_COMMAND_WORDS = 6  # T-01-24: a longer utterance is a request, never a command


def match_command(text: str, phrases: PhrasesConfig) -> Command | None:
    """A voice command only if the whole short utterance is one (never a substring)."""
    heard = normalize(text)
    bare = heard.removeprefix("snow ")  # "Snow, go to sleep"
    if not heard or len(heard.split()) > _MAX_COMMAND_WORDS:
        return None
    groups: tuple[tuple[Command, list[str]], ...] = (
        ("end", phrases.end),
        ("sleep", phrases.sleep),
        ("mute", phrases.mute),
    )
    for name, group in groups:
        known = {normalize(p) for p in group}
        if heard in known or bare in known:
            return name
    return None
