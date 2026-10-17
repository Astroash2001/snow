"""Groq first, Moonshine when Groq cannot answer in time (VOIC-04, D-17, D-37, D-38).

An ordered source chain with cooldowns: a Groq that failed is left alone until its
cooldown ends, so a rate limit or a dead network costs one turn, not one wait per turn.
The local final is computed while the user speaks, so falling back adds no wait.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Literal

from snow.contracts.events import SttStatus
from snow.voice.config import SttConfig
from snow.voice.stt_groq import GroqStt, SttKind, SttUnavailable

log = logging.getLogger("snow.voice")

Source = Literal["groq", "local"]
_MISSES_BEFORE_COOLDOWN = 3


class SttRouter:
    def __init__(
        self,
        groq: GroqStt,
        cfg: SttConfig,
        publish: Callable[..., None],
        *,
        has_local: bool = True,
        clock: Callable[[], float] = time.time,
        on_change: Callable[[], None] = lambda: None,
    ) -> None:
        self._groq = groq
        self._cfg = cfg
        self._publish = publish  # publish(SttStatus, **fields), on the event loop
        self._has_local = has_local
        self._clock = clock  # seconds; wall time so retry_after_ns means something
        self._on_change = on_change
        self._source: Source = "groq"
        self._reason: str = "primary"
        self._until = 0.0  # Groq is left alone until the clock reaches this
        self._misses = 0
        self._announced: tuple[str, str, int | None] | None = None
        if not groq.has_key:  # announced by the pipeline's start(), not from here
            self._start_cooldown("no_key", None)

    # --- state the pipeline reads ---------------------------------------------------

    def health(self) -> tuple[Literal["running", "down"], str | None]:
        """Row for `speech_to_text`: running when any source can hear the user."""
        if not self._has_local:  # Groq is the only source (plan 01-13 behaviour)
            if self._source == "groq":
                return "running", None
            if self._reason == "no_key":
                return "down", "No Groq key. Run snow setup."
            return "down", "Groq unavailable"
        if self._source == "groq":
            return "running", "Groq cloud"
        if self._reason == "no_key":
            return "running", "Local only (no Groq key)"
        return "running", "Local fallback"

    def refresh(self) -> None:
        """A Groq key stored since the last look ends the no-key cooldown at once."""
        if self._reason == "no_key" and self._groq.has_key:
            self._source, self._reason, self._until = "groq", "primary", 0.0
            self.announce()

    def announce(self, *, force: bool = False) -> None:
        """Publish the current source if it was not published yet (or when forced)."""
        retry_ns = int(self._until * 1e9) if self._source == "local" else None
        key = (self._source, self._reason, retry_ns)
        if force or key != self._announced:
            self._announced = key
            self._publish(
                SttStatus,
                stt_source=self._source,
                status_reason=self._reason,
                retry_after_ns=retry_ns,
            )

    # --- the final transcript ---------------------------------------------------------

    async def final(
        self, pcm: bytes, sample_rate: int, local: "Future[str] | None"
    ) -> tuple[str, Source]:
        self.refresh()
        if self._clock() >= self._until:
            try:
                text = await asyncio.wait_for(
                    self._groq.transcribe(pcm, sample_rate), self._cfg.final_deadline_s
                )
            except SttUnavailable as e:
                self._cooldown(e.kind, e.retry_after_s)
            except TimeoutError:
                self._miss()
            except Exception as e:  # noqa: BLE001 - a bad reply must not cost the turn
                log.warning("groq_stt_failed kind=%s", type(e).__name__)
                self._miss()
            else:
                self._misses = 0
                self._source, self._reason, self._until = "groq", "primary", 0.0
                self.announce()
                self._on_change()
                return text, "groq"
        if local is None or not self._has_local:
            raise SttUnavailable(self._failed_kind())
        try:
            return await asyncio.wrap_future(local), "local"
        except Exception as e:  # the local model never loaded
            raise SttUnavailable(self._failed_kind()) from e

    # --- cooldowns ---------------------------------------------------------------

    def _failed_kind(self) -> SttKind:
        return "no_key" if self._reason == "no_key" else "unreachable"

    def _miss(self) -> None:
        """A late or broken answer: local this turn; three in a row start a cooldown."""
        self._misses += 1
        if self._misses >= _MISSES_BEFORE_COOLDOWN:
            self._misses = 0
            self._cooldown("unreachable", None)

    def _start_cooldown(self, kind: SttKind, retry_after_s: float | None) -> None:
        wait = retry_after_s if kind == "rate_limited" and retry_after_s else None
        self._until = self._clock() + (wait or self._cfg.cooldown_s)
        self._source, self._reason = "local", kind

    def _cooldown(self, kind: SttKind, retry_after_s: float | None) -> None:
        self._start_cooldown(kind, retry_after_s)
        self.announce()
        self._on_change()
