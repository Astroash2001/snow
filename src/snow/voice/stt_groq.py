"""Cloud final transcript through Groq Whisper (VOIC-04, D-37).

The turn goes up as one in-memory WAV, never a file (D-18), and only for a turn a wake
phrase opened. Failures become `SttUnavailable` so a router can fall back to local STT.

The request asks for `verbose_json` so each segment carries Whisper's own confidence
(`no_speech_prob`, `avg_logprob`), at temperature 0 and with the vocabulary prompt from
voice.toml. A turn whose every segment looks silent returns "" and so gets no reply;
only numbers are logged, never the transcript (D-18).
"""

import io
import logging
import wave
from collections.abc import Callable
from typing import Literal

import httpx2
import openai
from openai import AsyncOpenAI, omit

from snow.config.secrets import Secret
from snow.voice.config import GroqConfig

log = logging.getLogger("snow.voice")

# Groq recommends 0 for transcription; it removes sampling randomness on short clips.
_TEMPERATURE = 0

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

    @property
    def has_key(self) -> bool:
        return self._get_secret(self._cfg.key_name) is not None

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
                response_format="verbose_json",
                temperature=_TEMPERATURE,
                prompt=self._cfg.prompt or omit,
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
        segs = result.segments or []
        if not segs:  # fail open: no confidence data means trust the text
            return result.text
        nsp = min(s.no_speech_prob for s in segs)
        alp = max(s.avg_logprob for s in segs)
        # Every segment at or above the first threshold and at or below the second.
        silent = (
            nsp >= self._cfg.silent_no_speech_prob
            and alp <= self._cfg.silent_avg_logprob
        )
        log.info(
            "groq_stt segments=%d no_speech_prob=%.2f avg_logprob=%.2f silent=%s",
            len(segs),
            nsp,
            alp,
            silent,
        )
        return "" if silent else result.text
