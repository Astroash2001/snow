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
        self._announced: tuple[str, ...] | None = None
        self.sample_rate = 24000  # of the playout; set from the first engine that loads
        self.ready = False

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
        engine = await self._choose(big_moment=False)
        if engine is not None:
            self.sample_rate = engine.sample_rate
        self.ready = True
        self.announce()
        return engine is not None

    # --- choosing -----------------------------------------------------------------

    def _eligible(self, name: EngineName, big_moment: bool) -> bool:
        if name == "cartesia":
            return big_moment  # D-33: only the big emotional moments
        if name == "chatterbox":
            return self._gpu_ok()
        return True

    def _usable(self, name: EngineName) -> bool:
        if self._state.get(name) == "ok":
            return True
        # A synthesis error is retried after its cooldown (a load failure is not).
        return name in self._until and self._clock() >= self._until[name]

    async def _choose(
        self, *, big_moment: bool, tried: frozenset[EngineName] = frozenset()
    ) -> TtsEngine | None:
        """First usable engine in the configured order; waits for one still loading.
        `tried` are engines that already failed this chunk."""
        failed: tuple[EngineName, str] | None = None
        for name in self._order():
            if name in tried or not self._eligible(name, big_moment):
                continue
            if self._state.get(name) == _LOADING:
                await self._loads[name]
            if not self._usable(name):
                failed = failed or (name, self._state.get(name, "load_failed"))
                continue
            if name in self._until:  # back after its cooldown
                del self._until[name]
                self._state[name] = "ok"
                self._switched.discard(name)
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
        async for text in chunks:
            await self._say(text, emotion, big_moment, push)

    async def _say(
        self, text: str, emotion: str, big_moment: bool, push: Callable[[Samples], None]
    ) -> None:
        tried: set[EngineName] = set()  # a zero cooldown must not retry a broken engine
        while True:
            engine = await self._choose(big_moment=big_moment, tried=frozenset(tried))
            if engine is None:
                self.announce()
                raise AllVoicesDown
            self._active = engine
            self.spoke_with = engine.name
            try:
                async for audio in engine.stream(text, emotion):
                    push(self._resample(audio, engine.sample_rate))
                self.announce()  # an engine back after its cooldown shows as current
                return
            except EngineError as e:
                self._fail(engine, e.kind)
                tried.add(engine.name)
            except Exception:  # noqa: BLE001 - library errors count as a broken engine
                self._fail(engine, "unreachable")
                tried.add(engine.name)
            finally:
                self._active = None

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
        current = self._current()
        cartesia = self._usable("cartesia") and self._enabled("cartesia")
        key = (status, detail or "", current.name if current else "", str(cartesia))
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
        if current is not None:
            self._publish(
                VoiceStatus,
                engine=current.name,
                voice_name=current.voice_name,
                voice_role=_ROLE[current.name],
                credits_remaining=None,
                cartesia_available=cartesia,
                cartesia_reason="ok" if cartesia else None,
            )
