"""Small deterministic checks: phrase helpers, Groq error mapping, turn-engine caps."""

import httpx2
import numpy as np
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.voice.config import VoiceConfig
from snow.voice.phrases import normalize, strip_wake
from snow.voice.stt_groq import GroqStt, SttUnavailable
from snow.voice.turn import TurnEngine
from snow.voice.wake import WakeHit

CFG = load_config("voice.toml", VoiceConfig)
PATTERNS = CFG.wake.strip_patterns


def test_normalize() -> None:
    assert normalize("  Hey,  JARVIS! That’s all. ") == "hey jarvis that's all"


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        (
            "Hey Jarvis, what is the capital of France?",
            "what is the capital of France?",
        ),
        ("Hey, Jervis. Open the pod bay doors", "Open the pod bay doors"),
        ("a jarvis what time is it", "what time is it"),
        ("What does Jarvis mean?", "What does Jarvis mean?"),
        ("Hey Jarvis.", ""),
        ("Hey Snow, what time is it?", "what time is it?"),
        ("hey, snow. Open the editor", "Open the editor"),
        ("Hay sno what time is it", "what time is it"),
        ("a snow, mute", "mute"),
        ("hey snoh", ""),
        ("Let it snow", "Let it snow"),
        ("Is it going to snow? Hey snow", "Is it going to snow? Hey snow"),
    ],
)
def test_strip_wake(heard: str, expected: str) -> None:
    assert strip_wake(heard, PATTERNS) == expected


def _stt(handler: httpx2.MockTransport, key: bool = True) -> GroqStt:
    return GroqStt(
        CFG.stt.groq, lambda _n: Secret("gsk_x") if key else None, transport=handler
    )


@pytest.mark.parametrize(
    ("response", "kind", "retry_after"),
    [
        (
            httpx2.Response(429, headers={"retry-after": "7"}, json={}),
            "rate_limited",
            7.0,
        ),
        (httpx2.Response(503, json={}), "unreachable", None),
        (httpx2.Response(401, json={}), "no_key", None),
    ],
)
async def test_groq_errors_become_stt_unavailable(
    response: httpx2.Response, kind: str, retry_after: float | None
) -> None:
    stt = _stt(httpx2.MockTransport(lambda _r: response))
    with pytest.raises(SttUnavailable) as e:
        await stt.transcribe(b"\x00\x00" * 1600)
    assert (e.value.kind, e.value.retry_after_s) == (kind, retry_after)


async def test_groq_without_key_never_touches_the_network() -> None:
    def boom(_r: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request expected")

    with pytest.raises(SttUnavailable) as e:
        await _stt(httpx2.MockTransport(boom), key=False).transcribe(b"\x00\x00")
    assert e.value.kind == "no_key"


class ScriptedVad:
    """Speech for the first `speech_chunks` post-wake chunks, then silence."""

    def __init__(self, speech_chunks: int) -> None:
        self.left = speech_chunks

    def speech_prob(self, chunk: object) -> float:
        self.left -= 1
        return 1.0 if self.left >= 0 else 0.0

    def reset(self) -> None: ...


class NeverComplete:
    def append(self, pcm: object) -> None: ...

    def is_complete(self) -> bool:
        return False

    def clear(self) -> None: ...


class Recorder:
    def __init__(self) -> None:
        self.ended: list[int] = []

    def __getattr__(self, name: str):
        if name == "on_turn_end":
            return lambda _id, _pcm, dur, _stop: self.ended.append(dur)
        return lambda *_a: None


def test_silence_cap_ends_a_turn_smart_turn_keeps_open() -> None:
    rec = Recorder()
    engine = TurnEngine(CFG.turn, ScriptedVad(20), NeverComplete(), rec)  # type: ignore[arg-type]
    frame = np.zeros(1280, dtype=np.int16)
    engine.on_wake(WakeHit(1.0, "t", [frame], 1280))
    for _ in range(100):  # 8 s of audio at 80 ms
        engine.feed(frame)
    # 20 speech chunks (0.64 s) + the 3 s cap, plus the pre-roll frame.
    assert len(rec.ended) == 1
    assert 3600 <= rec.ended[0] <= 4000
