"""Chatterbox, the GPU voice (SPCH-02, SPCH-03, D-33, D-39): the power and GPU policy,
the subprocess client, and the router fail-over.

No model and no GPU: the "server" is a stub script speaking the same pipe protocol, the
battery and `nvidia-smi` are fakes, and the clock is ours. Every process a test
starts is closed at teardown.
"""

import asyncio
import io
import struct
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from snow.config.settings import load_config
from snow.contracts.events import VoiceStatus, VoiceSwitch
from snow.voice.tts import chatterbox as chatterbox_module
from snow.voice.tts import router as router_module
from snow.voice.tts.base import EngineError, EngineLoadError, EngineName
from snow.voice.tts.chatterbox import (
    ChatterboxEngine,
    GpuPolicy,
    _nvidia_smi,
    _read_frame,
    resolve_reference,
)
from snow.voice.tts.config import ChatterboxConfig, TtsConfig, VoiceClip
from snow.voice.tts.router import VoiceRouter
from tests.voice.test_tts_router import Bus, FakeEngine, config, say

CFG = load_config("tts.toml", TtsConfig)

STUB = """
import json, struct, sys
out = sys.stdout.buffer

def control(obj):
    body = json.dumps(obj).encode()
    out.write(struct.pack("<I", 0x80000000 | len(body)) + body)
    out.flush()

for line in sys.stdin:
    req = json.loads(line)
    op = req["op"]
    if op == "load":
        control({"ok": True, "sr": 24000, "load_s": 0.1, "warm_s": 0.1})
    elif op == "vram":
        control({"peak_mb": 2048.0, "reserved_mb": 2200.0})
    elif op == "speak":
        if req["text"] == "crash":
            sys.exit(3)
        # the exaggeration it was given is the sample value, so a test can read it back
        pcm = struct.pack("<2400f", *([req["exaggeration"]] * 2400))
        for _ in range(3):
            out.write(struct.pack("<I", len(pcm)) + pcm)
        out.write(struct.pack("<I", 0))
        out.flush()
    elif op == "quit":
        break
"""


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class World:
    """Fake power and GPU readings the policy looks at."""

    def __init__(self) -> None:
        self.plugged: bool | None = True
        self.has_battery = True
        self.gpu: tuple[float, float] | None = (8000.0, 5.0)  # free MB, util %

    def battery(self) -> Any:
        if not self.has_battery:
            return None
        return SimpleNamespace(power_plugged=self.plugged)

    def smi(self) -> tuple[float, float] | None:
        return self.gpu


def policy_cfg(**changes: Any) -> ChatterboxConfig:
    return CFG.engines.chatterbox.model_copy(update=changes)


def policy_for(world: World, clock: Clock | None = None, **changes: Any) -> GpuPolicy:
    return GpuPolicy(
        policy_cfg(**changes),
        battery=world.battery,
        smi=world.smi,
        clock=clock or Clock(),
    )


# --- the policy ---------------------------------------------------------------------


def test_on_battery_the_policy_is_false_for_power() -> None:
    world = World()
    world.plugged = False
    policy = policy_for(world)
    assert policy.allowed() is False
    assert policy.reason == "power"


def test_unknown_power_state_counts_as_battery() -> None:
    world = World()
    world.plugged = None
    assert policy_for(world).allowed() is False


def test_a_desktop_with_no_battery_is_on_mains() -> None:
    world = World()
    world.has_battery = False
    policy = policy_for(world)
    assert policy.allowed() is True
    assert policy.reason is None


def test_plugged_in_with_free_vram_and_a_quiet_gpu_is_true() -> None:
    assert policy_for(World()).allowed() is True


def test_too_little_free_vram_is_gpu_busy() -> None:
    world = World()
    min_free = CFG.engines.chatterbox.min_free_vram_mb
    world.gpu = (min_free - 1.0, 2.0)
    policy = policy_for(world)
    assert policy.allowed() is False
    assert policy.reason == "gpu_busy"


def test_a_busy_gpu_is_false_and_our_own_synthesis_is_not_counted() -> None:
    world = World()
    world.gpu = (8000.0, CFG.engines.chatterbox.max_gpu_util + 1.0)
    policy = policy_for(world)
    assert policy.refresh() is False and policy.reason == "gpu_busy"
    policy.self_busy = True  # that utilisation is Chatterbox's own
    assert policy.refresh() is True


def test_the_vram_our_own_process_holds_counts_as_free() -> None:
    world = World()
    min_free = CFG.engines.chatterbox.min_free_vram_mb
    world.gpu = (min_free - 1000.0, 2.0)  # loaded: little is free, mostly ours
    policy = policy_for(world)
    assert policy.refresh() is False
    policy.own_vram_mb = 1500.0
    assert policy.refresh() is True


def test_a_missing_nvidia_smi_is_false() -> None:
    world = World()
    world.gpu = None
    policy = policy_for(world)
    assert policy.allowed() is False
    assert policy.reason == "gpu_busy"


def test_the_answer_is_cached_and_looked_at_again_when_upkeep_stops() -> None:
    world, clock = World(), Clock()
    policy = policy_for(world, clock)
    assert policy.allowed() is True
    world.plugged = False
    assert policy.allowed() is True  # still within the interval: the cached answer
    clock.t += 3 * CFG.engines.chatterbox.check_interval_s + 1
    assert policy.allowed() is False


def test_nvidia_smi_output_is_parsed_and_a_trimmed_path_is_covered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chatterbox_module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(chatterbox_module, "_smi_fallback", lambda: "nvidia-smi.exe")
    monkeypatch.setattr(
        chatterbox_module.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(stdout="4565, 1\n"),
    )
    assert _nvidia_smi() == (4565.0, 1.0)
    monkeypatch.setattr(chatterbox_module, "_smi_fallback", lambda: None)
    assert _nvidia_smi() is None  # no tool, no GPU voice


# --- the pipe protocol --------------------------------------------------------------


def test_frames_parse_audio_end_and_control() -> None:
    pcm = np.arange(4, dtype="<f4")
    control = b'{"ok": true}'
    wire = (
        struct.pack("<I", len(pcm.tobytes()))
        + pcm.tobytes()
        + struct.pack("<I", 0x80000000 | len(control))
        + control
        + struct.pack("<I", 0)
    )
    pipe = io.BytesIO(wire)
    kind, audio = _read_frame(pipe)
    assert kind == "audio" and audio.tolist() == [0.0, 1.0, 2.0, 3.0]
    assert _read_frame(pipe) == ("control", {"ok": True})
    assert _read_frame(pipe) == ("end", None)
    with pytest.raises(EOFError):
        _read_frame(pipe)


# --- the client against a stub server -----------------------------------------------


@pytest.fixture
def stub(tmp_path: Path) -> Path:
    path = tmp_path / "server.py"
    path.write_text(STUB)
    return path


@pytest.fixture
def engines() -> Iterator[list[ChatterboxEngine]]:
    made: list[ChatterboxEngine] = []
    yield made
    for engine in made:
        engine.close()  # never leaves a process (or VRAM) behind


def make_engine(
    made: list[ChatterboxEngine],
    stub: Path,
    world: World,
    clock: Clock,
    reference: VoiceClip | None = None,
    **changes: Any,
) -> ChatterboxEngine:
    cfg = policy_cfg(
        python=sys.executable,
        server=str(stub),
        check_interval_s=0,
        load_timeout_s=30,
        **changes,
    )
    policy = GpuPolicy(cfg, battery=world.battery, smi=world.smi, clock=clock)
    engine = ChatterboxEngine(cfg, policy, stub.parent, reference, clock=clock)
    made.append(engine)
    return engine


async def until(condition: Callable[[], bool], seconds: float = 20.0) -> None:
    async with asyncio.timeout(seconds):
        while not condition():  # noqa: ASYNC110 - a plain poll of a thread-set flag
            await asyncio.sleep(0.02)


async def warm_up(engine: ChatterboxEngine) -> None:
    engine.load()
    await engine.maintain()  # policy true: starts the process in the background
    await until(engine.warm)


def rewrite(path: Path, text: str) -> None:
    path.write_text(text)


async def collect(stream: AsyncIterator[Any]) -> list[Any]:
    return [chunk async for chunk in stream]


async def test_the_server_starts_lazily_and_speaks_with_the_emotions_dial(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    world, clock = World(), Clock()
    engine = make_engine(engines, stub, world, clock)
    engine.load()
    assert not engine.warm()  # nothing is loaded just because the engine exists
    assert engine.usable() is False

    await warm_up(engine)
    assert engine.usable() is True
    assert engine.sample_rate == 24000
    assert engine.peak_vram_mb == 2048.0

    chunks = await collect(engine.stream("Hello there.", "excited"))
    assert len(chunks) == 3 and all(len(c) == 2400 for c in chunks)
    assert chunks[0].dtype == np.float32
    excited = CFG.engines.chatterbox.exaggeration["excited"]
    assert chunks[0][0] == pytest.approx(excited)

    calm = await collect(engine.stream("Quietly.", "calm"))
    assert calm[0][0] == pytest.approx(CFG.engines.chatterbox.exaggeration["calm"])
    unknown = await collect(engine.stream("Odd.", "no-such-emotion"))
    assert unknown[0][0] == pytest.approx(CFG.engines.chatterbox.default_exaggeration)


async def test_a_server_crash_raises_engine_error_so_the_router_fails_over(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    world, clock = World(), Clock()
    engine = make_engine(engines, stub, world, clock)
    await warm_up(engine)

    with pytest.raises(EngineError) as err:
        await collect(engine.stream("crash", "neutral"))
    assert err.value.kind == "unreachable"
    await until(lambda: not engine.warm())
    assert engine.usable() is False


async def test_a_stream_before_the_model_is_loaded_is_an_engine_error(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    engine = make_engine(engines, stub, World(), Clock())
    engine.load()
    with pytest.raises(EngineError):
        await collect(engine.stream("Too early.", "neutral"))


def test_a_missing_environment_fails_to_load_once(tmp_path: Path) -> None:
    cfg = policy_cfg()  # points at engines/chatterbox/.venv, absent under tmp_path
    engine = ChatterboxEngine(cfg, GpuPolicy(cfg), tmp_path)
    with pytest.raises(EngineLoadError):
        engine.load()


def test_the_process_gets_no_keys_or_tokens(
    engines: list[ChatterboxEngine], stub: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "secret-groq")
    monkeypatch.setenv("SNOW_HUB_TOKEN", "secret-hub")
    monkeypatch.setenv("HF_TOKEN", "secret-hf")
    env = make_engine(engines, stub, World(), Clock())._env()
    assert not {"GROQ_API_KEY", "SNOW_HUB_TOKEN", "HF_TOKEN"} & set(env)
    assert env.get("HF_HUB_DISABLE_IMPLICIT_TOKEN") == "1"  # noqa: S105


# --- consent (D-05) -----------------------------------------------------------------


def test_a_reference_without_a_consent_tag_is_refused_at_config_load() -> None:
    with pytest.raises(ValidationError):
        ChatterboxConfig.model_validate(
            {
                **CFG.engines.chatterbox.model_dump(),
                "reference": {"path": "C:/voices/someone.wav"},
            }
        )


def test_an_untagged_clip_that_got_past_the_config_is_refused_by_the_engine(
    engines: list[ChatterboxEngine], stub: Path, tmp_path: Path
) -> None:
    clip = tmp_path / "someone.wav"
    clip.write_bytes(b"RIFF")
    untagged = VoiceClip.model_construct(path=str(clip), consent="")
    engine = make_engine(engines, stub, World(), Clock(), untagged)
    with pytest.raises(EngineLoadError):
        engine.load()
    tagged = VoiceClip(path=str(clip), consent="self")
    make_engine(engines, stub, World(), Clock(), tagged).load()  # passes


def test_the_pocket_reference_is_shared_only_when_it_is_an_audio_file(
    tmp_path: Path,
) -> None:
    pocket = CFG.engines.pocket_tts
    cb = CFG.engines.chatterbox
    assert resolve_reference(cb, pocket) is None  # "marius" is a preset, not a file
    wav = tmp_path / "me.wav"
    wav.write_bytes(b"RIFF")
    mine = VoiceClip(path=str(wav), consent="self")
    shared = pocket.model_copy(update={"reference": mine})
    assert resolve_reference(cb, shared) == mine
    own = VoiceClip(path=str(wav), consent="consenting_person")
    assert resolve_reference(cb.model_copy(update={"reference": own}), shared) == own


# --- the router ---------------------------------------------------------------------


def routed(
    engines: list[ChatterboxEngine], stub: Path, world: World, clock: Clock
) -> tuple[VoiceRouter, Bus, dict[EngineName, Any]]:
    chatterbox = make_engine(engines, stub, world, clock)
    registered: dict[EngineName, Any] = {
        "chatterbox": chatterbox,
        "pocket_tts": FakeEngine("pocket_tts", voice="marius"),
        "kokoro": FakeEngine("kokoro", voice="bm_george"),
        "cartesia": FakeEngine("cartesia"),
    }
    cfg = config(chatterbox=True, cartesia=True)
    voiced = cfg.engines.cartesia.model_copy(update={"voice_id": "a-voice"})
    cfg = cfg.model_copy(
        update={"engines": cfg.engines.model_copy(update={"cartesia": voiced})}
    )
    bus = Bus()
    router = VoiceRouter(registered, cfg, bus, clock=clock)
    return router, bus, registered


async def test_everyday_replies_use_chatterbox_while_allowed_big_moments_stay_cartesia(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    world, clock = World(), Clock()
    router, bus, registered = routed(engines, stub, world, clock)
    router.start()
    await router.wait_ready()
    await warm_up(registered["chatterbox"])

    audio = await say(router, "A plain reply.", emotion="content")
    assert audio and router.spoke_with == "chatterbox"
    assert registered["pocket_tts"].texts == []
    router.announce()
    assert bus.of(VoiceStatus)[-1].engine == "chatterbox"
    assert bus.of(VoiceStatus)[-1].voice_role == "gpu"

    await say(router, "We did it!", emotion="excited", big_moment=True)
    assert registered["cartesia"].texts == ["We did it!"]
    assert bus.of(VoiceSwitch) == []


async def test_a_crash_mid_reply_finishes_in_pocket_and_records_one_switch(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    world, clock = World(), Clock()
    router, bus, registered = routed(engines, stub, world, clock)
    router.start()
    await router.wait_ready()
    await warm_up(registered["chatterbox"])

    await say(router, "Fine so far.", "crash", "And the rest.")

    assert registered["pocket_tts"].texts == ["crash", "And the rest."]
    (switch,) = bus.of(VoiceSwitch)
    assert (switch.from_engine, switch.to_engine) == ("chatterbox", "pocket_tts")
    assert switch.switch_reason == "unreachable"


@pytest.mark.parametrize(
    ("change", "reason"),
    [("unplug", "power"), ("busy", "gpu_busy")],
)
async def test_a_false_policy_stops_the_process_and_publishes_one_switch(
    engines: list[ChatterboxEngine],
    stub: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    reason: str,
) -> None:
    monkeypatch.setattr(router_module, "_MAINTAIN_S", 0.01)
    world, clock = World(), Clock()
    router, bus, registered = routed(engines, stub, world, clock)
    chatterbox: ChatterboxEngine = registered["chatterbox"]
    router.start()
    await router.wait_ready()
    await warm_up(chatterbox)
    assert chatterbox.usable()
    proc = chatterbox._proc
    assert proc is not None

    if change == "unplug":
        world.plugged = False
    else:
        world.gpu = (100.0, 95.0)
    await until(lambda: bool(bus.of(VoiceSwitch)))
    await until(lambda: proc.poll() is not None)  # the VRAM is given back
    await asyncio.sleep(0.2)  # further looks must not repeat the news

    (switch,) = bus.of(VoiceSwitch)
    assert (switch.from_engine, switch.to_engine) == ("chatterbox", "pocket_tts")
    assert switch.switch_reason == reason
    assert not chatterbox.warm()
    await say(router, "Next reply.")
    assert registered["pocket_tts"].texts == ["Next reply."]
    assert router.spoke_with == "pocket_tts"
    router.stop()


async def test_idle_unload_frees_the_process_and_the_next_reply_brings_it_back(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    world, clock = World(), Clock()
    engine = make_engine(engines, stub, world, clock, unload_after_s=300)
    await warm_up(engine)
    proc = engine._proc
    assert proc is not None

    clock.t += 301
    assert await engine.maintain() is None  # idle, not a policy change: no news
    assert proc.poll() is not None and not engine.warm()

    clock.t += 1
    await engine.maintain()
    assert not engine.warm()  # stays unloaded until a reply asks for it

    engine.touch()
    await engine.maintain()
    await until(engine.warm)


async def test_a_failed_start_is_not_retried_every_look(
    engines: list[ChatterboxEngine], stub: Path
) -> None:
    world, clock = World(), Clock()
    engine = make_engine(engines, stub, world, clock)
    engine.load()
    rewrite(stub, "import sys\nsys.exit(1)\n")  # a server that dies on start
    await engine.maintain()
    await until(lambda: not engine._starting)
    assert not engine.warm()

    rewrite(stub, STUB)
    clock.t += 10
    await engine.maintain()
    assert not engine._starting and not engine.warm()
    clock.t += 301
    await engine.maintain()
    await until(engine.warm)
