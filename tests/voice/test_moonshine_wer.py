"""The local model is good enough to be the fallback: word error rate on fixtures."""

import re

import pytest

from snow.config.settings import load_config
from snow.voice.config import VoiceConfig
from snow.voice.sources import read_wav
from snow.voice.stt_local import LocalStt
from tests.voice.conftest import AUDIO, SR

MAX_WER = 0.25
SCRIPTED = {
    "wake_cmd_gap0": "Hey Jarvis, what is the capital of France?",
    "wake_cmd_gap150": "Hey Jarvis, what is the capital of France?",
    "wake_cmd_gap600": "Hey Jarvis, what is the capital of France?",
    "mid_thought_pause": (
        "Hey Jarvis, I was thinking that we could maybe check the weather tomorrow."
    ),
}


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def word_errors(ref: list[str], hyp: list[str]) -> int:
    """Word-level edit distance (substitutions, insertions, deletions)."""
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def test_word_errors_counts_each_kind_once() -> None:
    assert word_errors(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert word_errors(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert word_errors(["a", "b", "c"], ["a", "c"]) == 1
    assert word_errors(["a", "c"], ["a", "b", "c"]) == 1
    assert word_errors(["a"], []) == 1


@pytest.mark.slow
def test_moonshine_finals_stay_within_the_word_error_bound() -> None:
    cfg = load_config("voice.toml", VoiceConfig)
    local = LocalStt(cfg.stt.local)
    errors = total = 0
    try:
        for name, said in SCRIPTED.items():
            local.start_turn()
            pcm = read_wav(AUDIO / f"{name}.wav", SR)
            for i in range(0, len(pcm) - 1280 + 1, 1280):
                local.feed(pcm[i : i + 1280])
            heard = local.finish().result(timeout=60)
            errors += word_errors(words(said), words(heard))
            total += len(words(said))
            print(f"{name}: {heard!r}")
    finally:
        local.close()
    wer = errors / total
    print(f"WER {wer:.3f} over {total} words")
    assert wer <= MAX_WER
