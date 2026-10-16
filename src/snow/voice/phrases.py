"""Text helpers shared by the voice flow: normalization and wake-phrase stripping."""

import re
import unicodedata

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
