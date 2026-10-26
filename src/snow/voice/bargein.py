"""The decision on a paused barge-in episode: real words, not Snow's own echo, the user.

Pure and I/O-free. A verified voice (speaker score at or above the threshold) needs
`min_words_verified` words; with no voiceprint the degraded mode needs
`min_words_unverified`, because Moonshine tiny-streaming gives no word confidences, so a
lone word is as likely a cough as a command.
"""

import re
from difflib import SequenceMatcher

from snow.voice.config import BargeCheckConfig

_WORD = re.compile(r"[a-z0-9']+")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def echo_ratio(heard: str, said: str) -> float:
    """The share of the heard words found, in order, inside what Snow said."""
    h, s = words(heard), words(said)
    if not h:
        return 0.0
    blocks = SequenceMatcher(None, h, s, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(h)


def decide(
    score: float | None,
    threshold: float,
    heard: str,
    said: str,
    cfg: BargeCheckConfig,
) -> str:
    """Returns "ok" to cut Snow off, else "speaker", "words" or "echo": why not."""
    if score is not None and score < threshold:
        return "speaker"
    floor = cfg.min_words_unverified if score is None else cfg.min_words_verified
    if len(words(heard)) < floor:
        return "words"
    if echo_ratio(heard, said) >= cfg.echo_match:
        return "echo"
    return "ok"
