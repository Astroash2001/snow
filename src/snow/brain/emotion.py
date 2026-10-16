"""Streaming parser for the hidden reply header `[[emotion]]` / `[[emotion|big]]`.

See D-06 and D-33.

The model starts every reply with the header; it is validated here and never reaches the
voice or the HUD. A missing or invalid header falls back to a neutral emotion.
"""

import re
from collections.abc import Collection

HEADER = re.compile(r"^\s*\[\[([a-z/ ]{3,16})(\|big)?\]\]\s*")
_MAX_BUFFER = 32  # a header longer than this is not a header


class HeaderParser:
    def __init__(self, allowed: Collection[str], fallback: str) -> None:
        self._allowed = frozenset(allowed)
        self._fallback = fallback
        self._buf = ""
        self._done = False
        self._strip_lead = False
        self.emotion = fallback
        self.big = False
        self.found = False  # a well-formed header was seen, valid emotion or not

    def feed(self, chunk: str) -> str:
        """Visible text for this chunk; the header is withheld until it is complete."""
        if self._done:
            return self._visible(chunk)
        self._buf += chunk
        head = self._buf.lstrip()
        if not head or head == "[":
            return ""
        if not head.startswith("[["):
            return self._release(self._buf)
        if "]]" not in self._buf and len(self._buf) <= _MAX_BUFFER:
            return ""
        match = HEADER.match(self._buf)
        if match is None:
            return self._release(self._buf)
        name = match.group(1).strip()
        self.found = True
        self.emotion = name if name in self._allowed else self._fallback
        self.big = match.group(2) is not None
        self._strip_lead = True
        return self._release(self._buf[match.end() :])

    def flush(self) -> str:
        """End of stream: whatever is still held. A half-written header is dropped."""
        if self._done:
            return ""
        held, self._buf, self._done = self._buf, "", True
        return "" if held.lstrip().startswith("[") else held

    def _release(self, text: str) -> str:
        self._done = True
        self._buf = ""
        return self._visible(text)

    def _visible(self, text: str) -> str:
        if self._strip_lead and text:
            text = text.lstrip()
            self._strip_lead = not text
        return text


def split_header(
    text: str, allowed: Collection[str], fallback: str
) -> tuple[str, bool, bool, str]:
    """One whole line: (emotion, big, header_found, visible_text)."""
    parser = HeaderParser(allowed, fallback)
    visible = parser.feed(text) + parser.flush()
    return parser.emotion, parser.big, parser.found, visible
