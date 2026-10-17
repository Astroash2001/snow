"""What gets spoken: markdown, code, links and emoji never do (SPCH-03, T-01-43), and a
reply is cut into chunks so the first clause can start playing early (SPCH-04)."""

import re

_FENCE = "```"
_FENCED = re.compile(r"```.*?(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`?")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_LINE_MARKER = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+•][ \t]+|\d+[.)][ \t]+)", re.M
)
_STRONG = re.compile(r"(\*{1,3}|~~)(?=\S)(.+?)(?<=\S)\1", re.S)
_UNDERLINE = re.compile(r"(?<!\w)(_{1,3})(?=\S)(.+?)(?<=\S)\1(?!\w)", re.S)
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U00002b00-\U00002bff"
    "\U0001f1e6-\U0001f1ff️‍⃣]"
)
_RESIDUE = re.compile(r"[\[\]{}<>|\\^~`*#]|\(\s*\)")
_SPACES = re.compile(r"\s+")


def sanitize(text: str) -> str:
    """The speakable part of `text`: no code, links, markup or emoji, one line."""
    text = _FENCED.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _LINE_MARKER.sub("", text)
    text = _STRONG.sub(r"\2", text)
    text = _UNDERLINE.sub(r"\2", text)
    text = _EMOJI.sub("", text)
    text = _RESIDUE.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "e.g", "i.e"}
_BOUNDARY = re.compile(r"[.!?]+[\"')\]]*(?=\s)|[,;:](?=\s)|[—–]|(?<=\s)-{1,2}(?=\s)")
_LIST_NUMBER = re.compile(r"(?:.*\n)?\s*\d+", re.S)
_FIRST_CLAUSE_WORDS = 3


class SentenceChunker:
    """Cuts streamed reply text into speakable chunks. `feed` takes raw deltas.

    The first chunk ends at the first clause boundary (comma, semicolon, colon, dash)
    once it holds 3 words, else at the first sentence end; later ones end at sentence
    ends only. A boundary needs the whitespace after it, so decimals (3.5) and names
    never split; the last sentence waits for `flush`. Fenced code is dropped here, even
    when the fence spans several deltas.
    """

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._held = ""  # a possible fence marker at the end of the last delta
        self._in_fence = False
        self._buf = ""
        self._first = True

    def feed(self, delta: str) -> list[str]:
        self._buf += self._without_fences(delta)
        return self._release(final=False)

    def flush(self) -> list[str]:
        """The reply is complete: everything left is spoken; resets for the next one."""
        out = self._release(final=True)
        self._reset()
        return out

    def _without_fences(self, delta: str) -> str:
        raw = self._held + delta
        self._held = ""
        kept: list[str] = []
        while raw:
            i = raw.find(_FENCE)
            if i < 0:
                # A fence marker may be split across deltas: hold back trailing ticks.
                hold = len(raw) - len(raw.rstrip("`"))
                if 0 < hold < len(_FENCE):
                    self._held = raw[-hold:]
                    raw = raw[:-hold]
                if not self._in_fence:
                    kept.append(raw)
                break
            if not self._in_fence:
                kept.append(raw[:i])
            self._in_fence = not self._in_fence
            raw = raw[i + len(_FENCE) :]
        return "".join(kept)

    def _release(self, *, final: bool) -> list[str]:
        out: list[str] = []
        while (end := self._boundary()) is not None:
            piece, self._buf = self._buf[:end], self._buf[end:]
            self._add(out, piece)
        if final:
            self._add(out, self._buf)
            self._buf = ""
        return out

    def _add(self, out: list[str], piece: str) -> None:
        text = sanitize(piece)
        if re.search(r"\w", text):  # punctuation alone is not worth a synthesis call
            out.append(text)
            self._first = False

    def _boundary(self) -> int | None:
        for m in _BOUNDARY.finditer(self._buf):
            before = self._buf[: m.start()]
            if m.group()[0] in ".!?":
                if self._is_sentence_end(before, m.group()):
                    return m.end()
            elif self._first and len(sanitize(before).split()) >= _FIRST_CLAUSE_WORDS:
                return m.end()
        return None

    @staticmethod
    def _is_sentence_end(before: str, mark: str) -> bool:
        if mark != ".":
            return True
        word = re.search(r"[A-Za-z.]+$", before)
        if word and word.group().lower().strip(".") in _ABBREVIATIONS:
            return False
        return not _LIST_NUMBER.fullmatch(before)  # "1. " opens a list item
