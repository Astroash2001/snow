"""Groq request shape and error mapping, on the fail-closed FakeGroq transport."""

import httpx2
import pytest

from snow.config.secrets import Secret
from snow.config.settings import load_config
from snow.voice.config import VoiceConfig
from snow.voice.stt_groq import GroqStt, SttUnavailable
from tests.voice.conftest import FakeGroq

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
