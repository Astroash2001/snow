"""The voice router (SPCH-03, D-33): config-driven choice, load failures, all-down.

Fake engines only: no model is loaded, nothing is played, no network.
"""

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

import numpy as np
import pytest

from snow.config.settings import load_config
from snow.contracts.events import HealthSubsystem, VoiceStatus, VoiceSwitch
from snow.voice.tts.base import EngineLoadError, EngineName, Samples
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.router import AllVoicesDown, VoiceRouter

CFG = load_config("tts.toml", TtsConfig)
RATE = 24000


class FakeEngine:
    """`script` has one entry per `stream` call: None speaks, an exception is raised."""

    def __init__(
        self,
        name: EngineName,
        *,
        voice: str = "v",
        rate: int = RATE,
        load_error: Exception | None = None,
        script: list[Exception | None] | None = None,
    ) -> None:
        self.name = name
        self.voice_name = voice
        self.sample_rate = rate
        self.texts: list[str] = []
        self.cancelled = 0
        self._load_error = load_error
        self._script = script or []

    def load(self) -> None:
        if self._load_error is not None:
            raise self._load_error

    def cancel(self) -> None:
        self.cancelled += 1

    async def stream(self, text: str, emotion: str) -> AsyncIterator[Samples]:
        self.texts.append(text)
        outcome = self._script.pop(0) if self._script else None
        await asyncio.sleep(0)
        if outcome is not None:
            raise outcome
        yield np.full(self.sample_rate // 10, 0.2, dtype=np.float32)


def config(**enabled: bool) -> TtsConfig:
    """CFG with the named engines switched on or off."""
    engines = CFG.engines
    for name, on in enabled.items():
        engines = engines.model_copy(
            update={name: getattr(engines, name).model_copy(update={"enabled": on})}
        )
    return CFG.model_copy(update={"engines": engines})


class Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def __call__(self, cls: Callable[..., Any], **fields: object) -> None:
        self.events.append(cls(ts_ns=0, source="voice", **fields))

    def of(self, cls: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, cls)]


def make(
    engines: dict[EngineName, FakeEngine],
    cfg: TtsConfig = CFG,
    **kw: Any,
) -> tuple[VoiceRouter, Bus]:
    bus = Bus()
    return VoiceRouter(engines, cfg, bus, **kw), bus  # type: ignore[arg-type]


async def say(
    router: VoiceRouter,
    *texts: str,
    emotion: str = "neutral",
    big_moment: bool = False,
) -> list[Samples]:
    audio: list[Samples] = []

    async def chunks() -> AsyncIterator[str]:
        for t in texts:
            yield t

    await router.speak(chunks(), emotion, big_moment, audio.append)
    return audio


def pocket_and_kokoro(**kw: Any) -> dict[EngineName, FakeEngine]:
    return {
        "pocket_tts": FakeEngine("pocket_tts", voice="marius", **kw),
        "kokoro": FakeEngine("kokoro", voice="bm_george"),
    }


async def test_normal_and_big_moment_replies_both_go_to_pocket() -> None:
    engines = pocket_and_kokoro()
    router, bus = make(engines)
    router.start()
    assert await router.wait_ready()

    await say(router, "Hello there.", big_moment=False)
    await say(router, "We did it!", emotion="excited", big_moment=True)

    assert engines["pocket_tts"].texts == ["Hello there.", "We did it!"]
    assert engines["kokoro"].texts == []
    assert bus.of(VoiceSwitch) == []
    status = bus.of(VoiceStatus)
    assert [(s.engine, s.voice_role) for s in status] == [("pocket_tts", "everyday")]
    health = bus.of(HealthSubsystem)
    assert (health[-1].name, health[-1].status) == ("speech_output", "running")


async def test_a_pocket_that_fails_to_load_hands_every_reply_to_kokoro() -> None:
    engines = pocket_and_kokoro(load_error=EngineLoadError())
    router, bus = make(engines)
    router.start()
    assert await router.wait_ready()
    await say(router, "First reply.")
    await say(router, "Second reply.")

    assert engines["pocket_tts"].texts == []
    assert engines["kokoro"].texts == ["First reply.", "Second reply."]
    (switch,) = bus.of(VoiceSwitch)  # once, not per reply
    assert (switch.from_engine, switch.to_engine, switch.switch_reason) == (
        "pocket_tts",
        "kokoro",
        "load_failed",
    )
    (status,) = bus.of(VoiceStatus)
    assert (status.engine, status.voice_name, status.voice_role) == (
        "kokoro",
        "bm_george",
        "fallback",
    )
    assert bus.of(HealthSubsystem)[-1].detail == "Fallback voice"


async def test_an_engine_disabled_in_config_is_never_selected() -> None:
    engines = pocket_and_kokoro()
    router, _bus = make(engines, config(pocket_tts=False))
    router.start()
    await say(router, "Hi.")

    assert engines["pocket_tts"].texts == [] and engines["kokoro"].texts == ["Hi."]


async def test_an_engine_in_the_order_but_not_registered_is_skipped() -> None:
    engines: dict[EngineName, FakeEngine] = {"kokoro": FakeEngine("kokoro")}
    router, bus = make(engines, config(cartesia=True, chatterbox=True))
    router.start()
    await say(router, "Hi.", big_moment=True)

    assert engines["kokoro"].texts == ["Hi."]
    assert bus.of(VoiceSwitch) == []  # nothing failed: those engines were never there


async def test_cartesia_only_for_big_moments_and_chatterbox_only_by_its_policy() -> (
    None
):
    engines = pocket_and_kokoro()
    engines["cartesia"] = FakeEngine("cartesia")
    engines["chatterbox"] = FakeEngine("chatterbox")
    gpu = {"ok": False}
    cfg = config(cartesia=True, chatterbox=True)
    voiced = cfg.engines.cartesia.model_copy(update={"voice_id": "a-voice"})
    cfg = cfg.model_copy(
        update={"engines": cfg.engines.model_copy(update={"cartesia": voiced})}
    )
    router, _bus = make(engines, cfg, gpu_ok=lambda: gpu["ok"])
    router.start()
    await say(router, "Plain.")
    await say(router, "Big!", big_moment=True)
    assert engines["pocket_tts"].texts == ["Plain."]
    assert engines["cartesia"].texts == ["Big!"]

    gpu["ok"] = True  # mains power and an idle GPU
    await say(router, "Plugged in.")
    assert engines["chatterbox"].texts == ["Plugged in."]


async def test_when_every_engine_fails_the_health_row_goes_down() -> None:
    engines = pocket_and_kokoro(load_error=EngineLoadError())
    engines["kokoro"] = FakeEngine("kokoro", load_error=EngineLoadError())
    router, bus = make(engines)
    router.start()

    assert not await router.wait_ready()
    with pytest.raises(AllVoicesDown):
        await say(router, "Anyone there?")

    rows = bus.of(HealthSubsystem)
    assert (rows[-1].name, rows[-1].status) == ("speech_output", "down")
    assert bus.of(VoiceStatus) == []


async def test_a_slow_kokoro_does_not_hold_up_a_pocket_that_loaded() -> None:
    engines = pocket_and_kokoro()
    release = threading.Event()
    engines["kokoro"].load = lambda: release.wait(5)  # type: ignore[method-assign,assignment]
    router, _bus = make(engines)
    router.start()
    async with asyncio.timeout(5):
        assert await router.wait_ready()  # Pocket is ready while Kokoro still loads
    assert router.sample_rate == RATE
    release.set()
    await asyncio.gather(*router._loads.values())  # noqa: SLF001
