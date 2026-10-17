"""The voice router: which engine speaks, and what happens when one breaks (SPCH-03).

The engine list is an ordered chain (D-33) like the LLM provider chains. Per reply the
first enabled, registered, eligible and healthy engine speaks. An engine that errors,
even in the middle of a reply, is marked down (a cooldown for synthesis errors, for the
session when it failed to load) and the failed chunk plus the rest of the reply continue
on the next engine, so Snow is never silent because a voice broke. Audio is handed on in
memory only.

Shortcut: audio a failing engine had already pushed for the failed chunk is not taken
back, so a chunk that dies half way may repeat its first words on the next engine; a
chunk is a clause, so this is a few hundred milliseconds.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Literal

import numpy as np

from snow.contracts.events import HealthSubsystem, VoiceStatus, VoiceSwitch
from snow.voice.tts.base import EngineError, EngineName, ErrorKind, Samples, TtsEngine
from snow.voice.tts.cartesia import CartesiaEngine
from snow.voice.tts.config import TtsConfig

log = logging.getLogger("snow.voice")

VoiceRole = Literal["everyday", "big_moment", "gpu", "fallback"]
_ROLE: dict[EngineName, VoiceRole] = {
    "pocket_tts": "everyday",
    "cartesia": "big_moment",
    "chatterbox": "gpu",
    "kokoro": "fallback",
}
_LOADING = "loading"
_MAINTAIN_S = (
    5.0  # how often Cartesia's probe, credits and warm connection are looked at
)


class AllVoicesDown(EngineError):
    """No engine could speak a reply that has text."""

    def __init__(self) -> None:
        super().__init__("unreachable")


class VoiceRouter:
    def __init__(
        self,
        engines: Mapping[EngineName, TtsEngine],
        cfg: TtsConfig,
        publish: Callable[..., None],
        *,
        gpu_ok: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engines = engines
        self._cfg = cfg
        self._publish = publish  # publish(EventClass, **fields), on the event loop
        self._gpu_ok = gpu_ok  # chatterbox's own policy: mains power and an idle GPU
        self._clock = clock
        # name -> "loading" | "ok" | an ErrorKind (down)
        self._state: dict[EngineName, str] = {}
        self._until: dict[EngineName, float] = {}  # cooldown end for synthesis errors
        self._loads: dict[EngineName, asyncio.Task[None]] = {}
        self._switched: set[EngineName] = set()  # failures already announced
        self._active: TtsEngine | None = None
        self.spoke_with: EngineName | None = None  # the engine of the latest audio
        self._announced: tuple[object, ...] | None = None
        self.sample_rate = 24000  # of the playout; set from the first engine that loads
        self.ready = False
        self.spoken: dict[
            EngineName, int
        ] = {}  # characters each engine spoke this reply
        self._maintainer: asyncio.Future[None] | None = None

    # --- startup ------------------------------------------------------------------

    def _enabled(self, name: EngineName) -> bool:
        return name in self._engines and bool(getattr(self._cfg.engines, name).enabled)

    def _order(self) -> list[EngineName]:
        return [n for n in self._cfg.router.order if self._enabled(n)]

    def start(self) -> None:
        """Load every enabled engine in the background (needs a running loop)."""
        for name in self._order():
            self._state[name] = _LOADING
            self._loads[name] = asyncio.ensure_future(self._load(name))
        if self._cartesia() is not None:
            self._maintainer = asyncio.ensure_future(self._maintain())

    def stop(self) -> None:
        if self._maintainer is not None:
            self._maintainer.cancel()

    def _cartesia(self) -> CartesiaEngine | None:
        engine = self._engines.get("cartesia")
        if isinstance(engine, CartesiaEngine) and self._enabled("cartesia"):
            return engine
        return None

    async def _maintain(self) -> None:
        """Cartesia's free probe, credits and warm connection (SPCH-03 failback)."""
        cartesia = self._cartesia()
        assert cartesia is not None  # noqa: S101 - start() checked
        while True:
            await asyncio.sleep(_MAINTAIN_S)  # first look after start-up has settled
            try:
                await cartesia.maintain()
            except Exception as e:  # noqa: BLE001 - upkeep must never stop the voice
                log.error("cartesia_upkeep_failed kind=%s", type(e).__name__)
            self.announce()

    def on_snapshot(self, cartesia_chars_today: int) -> None:
        """The hub's Cartesia characters today: where the budget starts."""
        if (cartesia := self._cartesia()) is not None:
            cartesia.set_base(cartesia_chars_today)

    async def _load(self, name: EngineName) -> None:
        try:
            await asyncio.to_thread(self._engines[name].load)
            self._state[name] = "ok"
        except EngineError as e:
            self._state[name] = e.kind
        except Exception as e:  # noqa: BLE001 - a broken engine must not take the others down
            log.error("tts_load_failed engine=%s kind=%s", name, type(e).__name__)
            self._state[name] = "load_failed"

    async def wait_ready(self) -> bool:
        """Wait until the engine that would speak an everyday reply is known; False when
        none can. Slower engines behind it keep loading in the background."""
        engine = await self._choose(big_moment=False, text="")
        if engine is not None:
            self.sample_rate = engine.sample_rate
        self.ready = True
        self.announce()
        return engine is not None

    # --- choosing -----------------------------------------------------------------

    def _eligible(self, name: EngineName, big_moment: bool) -> bool:
        if name == "cartesia":  # D-33: only the big emotional moments, with a voice set
            return big_moment and bool(self._cfg.engines.cartesia.voice_id)
        if name == "chatterbox":
            return self._gpu_ok()
        return True

    def _usable(self, name: EngineName) -> bool:
        if self._state.get(name) == "ok":
            return True
        # A synthesis error is retried after its cooldown (a load failure is not).
        return name in self._until and self._clock() >= self._until[name]

    async def _choose(
        self,
        *,
        big_moment: bool,
        text: str,
        tried: Mapping[EngineName, str] | None = None,
    ) -> TtsEngine | None:
        """First usable engine in the configured order; waits for one still loading.
        `tried` are engines that already failed this reply, with why."""
        tried = tried or {}
        failed: tuple[EngineName, str] | None = None
        cartesia = self._cartesia()
        for name in self._order():
            if name in tried:
                failed = failed or (name, tried[name])
                continue
            if not self._eligible(name, big_moment):
                continue
            if self._state.get(name) == _LOADING:
                await self._loads[name]
            if not self._usable(name):
                failed = failed or (name, self._state.get(name, "load_failed"))
                continue
            if name == "cartesia" and cartesia is not None:
                if why := cartesia.unavailable_reason(len(text)):  # health, key, budget
                    failed = failed or (name, why)
                    continue
            if name in self._until:  # back after its cooldown
                del self._until[name]
                self._state[name] = "ok"
                self._switched.discard(name)
            if name == "cartesia":
                self._switched.discard(name)  # available again: the next outage is news
            if failed and failed[0] not in self._switched:
                self._switched.add(failed[0])
                self._publish(
                    VoiceSwitch,
                    from_engine=failed[0],
                    to_engine=name,
                    switch_reason=failed[1],
                )
            return self._engines[name]
        return None

    def _fail(self, engine: TtsEngine, kind: ErrorKind) -> None:
        log.error("tts_failed engine=%s kind=%s", engine.name, kind)
        if engine.name == "cartesia":
            return  # its own health decides when it is back (the free probe)
        self._state[engine.name] = kind
        if kind != "load_failed":
            self._until[engine.name] = self._clock() + self._cfg.router.cooldown_s
        self._switched.discard(engine.name)

    # --- speaking -----------------------------------------------------------------

    async def speak(
        self,
        chunks: AsyncIterator[str],
        emotion: str,
        big_moment: bool,
        push: Callable[[Samples], None],
    ) -> None:
        """Speak each text chunk in order, handing audio to `push`. Raises
        `AllVoicesDown` (after publishing the health row) when no engine can say one."""
        tried: dict[
            EngineName, str
        ] = {}  # an engine that broke stays out of this reply
        self.spoken = {}
        try:
            async for text in chunks:
                await self._say(text, emotion, big_moment, push, tried)
        finally:
            if (cartesia := self._cartesia()) is not None:
                await (
                    cartesia.end_reply()
                )  # closes its context; a no-op if it was dropped

    async def _say(
        self,
        text: str,
        emotion: str,
        big_moment: bool,
        push: Callable[[Samples], None],
        tried: dict[EngineName, str],
    ) -> None:
        while True:
            engine = await self._choose(big_moment=big_moment, text=text, tried=tried)
            if engine is None:
                self.announce()
                raise AllVoicesDown
            self._active = engine
            self.spoke_with = engine.name
            pushed = False
            try:
                async for audio in engine.stream(text, emotion):
                    pushed = True
                    push(self._resample(audio, engine.sample_rate))
                self.announce()  # an engine back after its cooldown shows as current
                return
            except EngineError as e:
                self._fail(engine, e.kind)
                tried[engine.name] = e.kind
            except Exception:  # noqa: BLE001 - library errors count as a broken engine
                self._fail(engine, "unreachable")
                tried[engine.name] = "unreachable"
            finally:
                self._active = None
                if pushed:  # credits and the daily count follow what was started
                    self.spoken[engine.name] = self.spoken.get(engine.name, 0) + len(
                        text
                    )

    def take_spoken(self) -> dict[EngineName, int]:
        """Characters each engine spoke in the reply that just ended, once."""
        spoken, self.spoken = self.spoken, {}
        return spoken

    def cancel(self) -> None:
        """Thread-safe: stop the engine that is speaking, if any."""
        if (engine := self._active) is not None:
            engine.cancel()

    def _resample(self, audio: Samples, rate: int) -> Samples:
        """Linear resample when an engine runs at another rate than the open playout."""
        if rate == self.sample_rate or len(audio) == 0:
            return audio
        n = round(len(audio) * self.sample_rate / rate)
        out = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
        return out.astype(np.float32)

    # --- what the HUD sees --------------------------------------------------------

    def _current(self) -> TtsEngine | None:
        """The engine that would speak an everyday reply right now (no waiting)."""
        for name in self._order():
            if self._eligible(name, big_moment=False) and self._usable(name):
                return self._engines[name]
        return None

    def health(self) -> tuple[Literal["running", "starting", "down"], str | None]:
        if not self.ready:
            return "starting", None
        current = self._current()
        if current is None:
            return "down", "No voice available"
        if _ROLE[current.name] == "fallback":
            return "running", "Fallback voice"
        return "running", None

    def announce(self, *, force: bool = False) -> None:
        """Publish the health row and the voice card when they changed (or when forced:
        a row sent while the hub was away is lost)."""
        status, detail = self.health()
        shown = self._current()
        cartesia = self._cartesia()
        if cartesia is not None and self.spoke_with == "cartesia":
            shown = (
                cartesia  # the big moment just spoken stays on the card until the next
            )
        available, reason = cartesia.status() if cartesia else (False, None)
        credits = cartesia.credits_remaining if cartesia else None
        key = (
            status,
            detail or "",
            shown.name if shown else "",
            available,
            reason,
            credits,
        )
        if not force and key == self._announced:
            return
        self._announced = key
        self._publish(
            HealthSubsystem,
            name="speech_output",
            label="Speech output",
            owner="voice",
            status=status,
            detail=detail,
        )
        if shown is not None:
            self._publish(
                VoiceStatus,
                engine=shown.name,
                voice_name=shown.voice_name,
                voice_role=_ROLE[shown.name],
                credits_remaining=credits,
                cartesia_available=available,
                cartesia_reason=reason,
            )
