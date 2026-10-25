"""Groq request shape and error mapping, on the fail-closed FakeGroq transport."""

import logging

import httpx2
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.voice.config import VoiceConfig
from snow.voice.stt_groq import GroqStt, SttUnavailable
from tests.voice.conftest import FakeGroq, verbose_segment

CFG = load_config("voice.toml", VoiceConfig).stt.groq
PCM = b"\x00\x00" * 1600


def stt(transport: httpx2.MockTransport, key: bool = True) -> GroqStt:
    return GroqStt(CFG, lambda _n: Secret("gsk_test") if key else None, transport)


async def test_request_is_multipart_with_model_and_language(groq: FakeGroq) -> None:
    groq.text = "hello"
    text = await stt(httpx2.MockTransport(groq.handler)).transcribe(PCM)
    assert text == "hello"
    request = groq.requests[0]
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="model"\r\n\r\nwhisper-large-v3-turbo' in body
    assert b'name="language"\r\n\r\nen' in body
    assert b"RIFF" in body  # the in-memory WAV, not a path
    assert request.headers["authorization"] == "Bearer gsk_test"


async def test_request_asks_for_verbose_json_temperature_zero_and_the_prompt(
    groq: FakeGroq,
) -> None:
    groq.text = "hello"
    await stt(httpx2.MockTransport(groq.handler)).transcribe(PCM)
    body = groq.requests[0].content
    assert b'name="response_format"\r\n\r\nverbose_json' in body
    assert b'name="temperature"\r\n\r\n0' in body
    assert b'name="prompt"\r\n\r\n' + CFG.prompt.encode() in body


def answer(*segments: tuple[float, float], text: str = "thank you") -> GroqStt:
    """A Groq whose answer has one segment per (no_speech_prob, avg_logprob) pair."""
    body = {
        "text": text,
        "language": "en",
        "duration": 1.0,
        "segments": [verbose_segment(text, n, a) for n, a in segments],
    }
    return stt(httpx2.MockTransport(lambda _r: httpx2.Response(200, json=body)))


NSP, ALP = CFG.silent_no_speech_prob, CFG.silent_avg_logprob


async def test_a_silent_looking_answer_is_dropped_inclusive_at_both_edges() -> None:
    assert await answer((NSP, ALP)).transcribe(PCM) == ""


async def test_just_inside_either_edge_keeps_the_text() -> None:
    assert await answer((NSP - 0.01, ALP)).transcribe(PCM) == "thank you"
    assert await answer((NSP, ALP + 0.01)).transcribe(PCM) == "thank you"


async def test_one_confident_segment_keeps_the_whole_text() -> None:
    both = answer((0.95, -2.0), (0.01, -0.2))
    assert await both.transcribe(PCM) == "thank you"


async def test_every_segment_silent_looking_is_dropped() -> None:
    assert await answer((0.95, -2.0), (NSP, ALP)).transcribe(PCM) == ""


async def test_a_transcript_made_only_of_prompt_words_is_dropped() -> None:
    prompt = "Hey Snow. Claude Code, Antigravity, OpenCode."
    cfg = CFG.model_copy(update={"prompt": prompt})

    def heard(text: str) -> GroqStt:
        body = {
            "text": text,
            "language": "en",
            "duration": 1.0,
            "segments": [verbose_segment(text, 0.0, -0.3)],
        }
        mock = httpx2.MockTransport(lambda _r: httpx2.Response(200, json=body))
        return GroqStt(cfg, lambda _n: Secret("gsk_test"), mock)

    assert await heard(" Claude Code, Antigravity, OpenCode.").transcribe(PCM) == ""
    assert await heard("Hey snow.").transcribe(PCM) == ""
    kept = " Open Claude Code in the snow project."
    assert await heard(kept).transcribe(PCM) == kept  # one word outside the prompt


async def test_no_segments_fails_open() -> None:
    assert await answer().transcribe(PCM) == "thank you"


async def test_the_confidence_line_carries_numbers_and_never_the_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="snow.voice")
    await answer((0.5, -0.3), text="secret words").transcribe(PCM)
    line = next(r.getMessage() for r in caplog.records if "groq_stt" in r.message)
    assert "segments=1 no_speech_prob=0.50 avg_logprob=-0.30 silent=False" in line
    assert "secret" not in caplog.text


async def test_rate_limit_carries_retry_after() -> None:
    limited = httpx2.Response(429, headers={"retry-after": "30"}, json={})
    with pytest.raises(SttUnavailable) as e:
        await stt(httpx2.MockTransport(lambda _r: limited)).transcribe(PCM)
    assert (e.value.kind, e.value.retry_after_s) == ("rate_limited", 30.0)


async def test_missing_key_is_no_key_and_sends_nothing(groq: FakeGroq) -> None:
    with pytest.raises(SttUnavailable) as e:
        await stt(httpx2.MockTransport(groq.handler), key=False).transcribe(PCM)
    assert e.value.kind == "no_key"
    assert groq.requests == []
