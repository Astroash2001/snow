"""Cloud final transcript through Groq Whisper (VOIC-04, D-37).

The turn goes up as one in-memory WAV, never a file (D-18), and only for a turn a wake
phrase opened. Failures become `SttUnavailable` so a router can fall back to local STT.
"""

import io
import wave
from collections.abc import Callable
from typing import Literal

import httpx2
import openai
from openai import AsyncOpenAI

from snow.config.secrets import Secret
from snow.voice.config import GroqConfig

SttKind = Literal["no_key", "rate_limited", "unreachable", "offline"]


class SttUnavailable(Exception):
    def __init__(self, kind: SttKind, retry_after_s: float | None = None) -> None:
        super().__init__(kind)
        self.kind: SttKind = kind
        self.retry_after_s = retry_after_s


def wav_bytes(pcm: bytes, sample_rate: int) -> io.BytesIO:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    buffer.seek(0)
    return buffer


def _retry_after(response: httpx2.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


class GroqStt:
    def __init__(
        self,
        cfg: GroqConfig,
        get_secret: Callable[[str], Secret | None],
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._cfg = cfg
        self._get_secret = get_secret
        self._transport = transport  # tests inject a fail-closed mock transport

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        secret = self._get_secret(self._cfg.key_name)
        if secret is None:
            raise SttUnavailable("no_key")
        client = AsyncOpenAI(
            base_url=self._cfg.base_url,
            api_key=secret.reveal(),
            max_retries=0,
            timeout=self._cfg.timeout_s,
            http_client=httpx2.AsyncClient(transport=self._transport)
            if self._transport
            else None,
        )
        try:
            result = await client.audio.transcriptions.create(
                model=self._cfg.model,
                file=("turn.wav", wav_bytes(pcm, sample_rate), "audio/wav"),
                language=self._cfg.language,
                response_format="json",
            )
        except openai.RateLimitError as e:
            raise SttUnavailable("rate_limited", _retry_after(e.response)) from e
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            raise SttUnavailable("no_key") from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise SttUnavailable("unreachable") from e
            raise
        except openai.APIConnectionError as e:  # includes timeouts
            raise SttUnavailable("unreachable") from e
        finally:
            await client.close()
        return result.text
