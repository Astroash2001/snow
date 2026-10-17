"""SPCH-03: the voice never drops out. A broken engine, even mid-reply, is replaced.

Fake engines and a fake speaker: nothing is synthesized for real (except the one `slow`
test, which plays nothing), nothing is played, and no audio touches the disk.
"""

import asyncio
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from snow.contracts.events import (
    HealthSubsystem,
    PresenceState,
    VoiceStatus,
    VoiceSwitch,
)
from snow.voice.tts.base import EngineError, EngineLoadError
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.kokoro import KokoroEngine, _ensure
from snow.voice.tts.router import VoiceRouter
from tests.voice.conftest import FakeHub, StubSource, make_pipeline, until
from tests.voice.test_tts_pipeline import (
    TTS_CFG,
    Speaker,
    StubTurnEngine,
    delta,
    final,
    of,
    play_out,
)
from tests.voice.test_tts_router import (
    CFG,
    FakeEngine,
    make,
    pocket_and_kokoro,
    say,
)


async def test_pocket_failing_on_chunk_two_of_three_finishes_the_reply_in_kokoro() -> (
    None
):
    engines = pocket_and_kokoro(script=[None, EngineError("unreachable"), None])
    router, bus = make(engines)
    router.start()
    await router.wait_ready()

    audio = await say(router, "One.", "Two.", "Three.")

    assert engines["pocket_tts"].texts == ["One.", "Two."]  # chunk 1 not spoken again
    assert engines["kokoro"].texts == [
        "Two.",
        "Three.",
    ]  # the failed chunk, then the rest
    assert len(audio) == 3  # every chunk produced audio, in order
    (switch,) = bus.of(VoiceSwitch)
    assert (switch.from_engine, switch.to_engine, switch.switch_reason) == (
        "pocket_tts",
        "kokoro",
        "unreachable",
    )
    assert [s.engine for s in bus.of(VoiceStatus)] == ["pocket_tts", "kokoro"]
    assert bus.of(VoiceStatus)[-1].voice_role == "fallback"
    assert bus.of(HealthSubsystem)[-1].status == "running"


async def test_a_library_error_counts_as_a_broken_engine() -> None:
    engines = pocket_and_kokoro(script=[RuntimeError("torch exploded")])
    router, _bus = make(engines)
    router.start()
    await router.wait_ready()

    await say(router, "Still here.")

    assert engines["kokoro"].texts == ["Still here."]


async def test_the_everyday_voice_comes_back_after_its_cooldown() -> None:
    engines = pocket_and_kokoro(script=[EngineError("unreachable")])
    now = {"t": 0.0}
    router, bus = make(engines, clock=lambda: now["t"])
    router.start()
    await router.wait_ready()

    await say(router, "Breaks.")  # pocket fails, kokoro speaks
    await say(router, "Inside the cooldown.")
    assert engines["pocket_tts"].texts == ["Breaks."]

    now["t"] += CFG.router.cooldown_s + 1
    await say(router, "Recovered.")

    assert engines["pocket_tts"].texts == ["Breaks.", "Recovered."]
    assert [s.engine for s in bus.of(VoiceStatus)] == [
        "pocket_tts",
        "kokoro",
        "pocket_tts",
    ]
    assert len(bus.of(VoiceSwitch)) == 1


async def test_a_zero_cooldown_does_not_retry_a_broken_engine_forever() -> None:
    cfg = CFG.model_copy(
        update={"router": CFG.router.model_copy(update={"cooldown_s": 0.0})}
    )
    engines = pocket_and_kokoro(script=[EngineError("unreachable")] * 5)
    router, _bus = make(engines, cfg)
    router.start()
    await router.wait_ready()

    async with asyncio.timeout(5):
        await say(router, "Once.")

    assert engines["pocket_tts"].texts == ["Once."]
    assert engines["kokoro"].texts == ["Once."]


async def test_a_fallback_at_another_sample_rate_is_resampled_to_the_open_playout() -> (
    None
):
    engines = pocket_and_kokoro(script=[EngineError("unreachable")])
    engines["kokoro"] = FakeEngine("kokoro", rate=16000)
    router, _bus = make(engines)
    router.start()
    await router.wait_ready()

    (clip,) = await say(router, "Short.")

    assert len(clip) == 2400  # 0.1 s at 16 kHz became 0.1 s at the playout's 24 kHz
    assert clip.dtype == np.float32


def test_cancel_stops_the_engine_that_is_speaking() -> None:
    engines = pocket_and_kokoro()
    router, _bus = make(engines)
    router.cancel()  # idle: nothing to stop, no error
    router._active = engines["pocket_tts"]  # noqa: SLF001
    router.cancel()
    assert engines["pocket_tts"].cancelled == 1


# --- through the pipeline ----------------------------------------------------------


async def pipeline_with(
    engines: dict[Any, FakeEngine], cfg: TtsConfig = TTS_CFG
) -> tuple[Any, FakeHub, Speaker, StubTurnEngine]:
    hub, speaker = FakeHub(), Speaker()
    pipeline = make_pipeline(hub, StubSource())
    pipeline._tts = VoiceRouter(engines, cfg, pipeline._emit)  # noqa: SLF001
    pipeline._tts_cfg = cfg  # noqa: SLF001
    pipeline._stream_factory = speaker.factory  # noqa: SLF001
    turn = StubTurnEngine(pipeline)
    pipeline._engine = turn  # type: ignore[assignment]  # noqa: SLF001
    await pipeline.start()
    pipeline._pending = "t1"  # noqa: SLF001 - a turn is waiting for this reply
    await until(pipeline._tts_ready.is_set)  # noqa: SLF001
    return pipeline, hub, speaker, turn


async def test_a_reply_that_loses_its_voice_midway_is_still_spoken_to_the_end() -> None:
    engines = pocket_and_kokoro(script=[None, EngineError("unreachable")])
    pipeline, hub, speaker, turn = await pipeline_with(engines)
    for text in ("First sentence here. ", "Second sentence here. ", "Third one."):
        await pipeline.on_hub_event(delta(text))
    await pipeline.on_hub_event(
        final("First sentence here. Second sentence here. Third one.")
    )
    await play_out(pipeline, hub, speaker)

    assert engines["kokoro"].texts == ["Second sentence here.", "Third one."]
    assert [e.state for e in of(hub, PresenceState)] == ["speaking", "listening"]
    assert of(hub, VoiceSwitch)[0].to_engine == "kokoro"
    assert turn.finished == 1


async def test_when_every_voice_is_down_the_loop_goes_on_and_health_says_so() -> None:
    engines = pocket_and_kokoro(load_error=EngineLoadError())
    engines["kokoro"] = FakeEngine("kokoro", load_error=EngineLoadError())
    pipeline, hub, speaker, turn = await pipeline_with(engines)

    await pipeline.on_hub_event(delta("Hello there, my friend."))
    await pipeline.on_hub_event(
        final("Hello there, my friend.")
    )  # the HUD gets the text
    await until(lambda: turn.finished == 1)
    await pipeline._q.join()  # noqa: SLF001

    rows = [h for h in hub.health if h.name == "speech_output"]
    assert rows[0].status == "starting" and rows[-1].status == "down"
    assert speaker.stream is None  # nothing was opened, nothing crashed


async def test_every_voice_dying_in_synthesis_ends_the_reply_cleanly() -> None:
    dying = [EngineError("unreachable")]
    engines = pocket_and_kokoro(script=list(dying))
    engines["kokoro"] = FakeEngine("kokoro", script=list(dying))
    pipeline, hub, _speaker, turn = await pipeline_with(engines)

    await pipeline.on_hub_event(final("Nobody can say this."))
    await until(lambda: turn.finished == 1)
    await pipeline._q.join()  # noqa: SLF001

    assert [h for h in hub.health if h.name == "speech_output"][-1].status == "down"
    assert pipeline._reply is None  # noqa: SLF001


# --- kokoro itself -------------------------------------------------------------------


def test_the_pinned_kokoro_config_is_the_british_male_voice_with_two_checksums() -> (
    None
):
    k = TTS_CFG.engines.kokoro
    assert k.enabled and k.voice == "bm_george" and k.threads == 4
    assert k.model_url.startswith("https://github.com/thewh1teagle/kokoro-onnx/")
    assert len(k.model_sha256) == 64 and len(k.voices_sha256) == 64


def test_a_downloaded_file_that_fails_its_checksum_is_never_kept_or_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Reply:
        def __init__(self) -> None:
            self._data = b"not the real model"

        def __enter__(self) -> "Reply":
            return self

        def __exit__(self, *a: object) -> None: ...

        def read(self, n: int) -> bytes:
            data, self._data = self._data[:n], self._data[n:]
            return data

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Reply())
    dest = tmp_path / "model.onnx"
    with pytest.raises(ValueError, match="SHA-256"):
        _ensure("https://example.invalid/model.onnx", "0" * 64, dest)
    assert not dest.exists() and not list(tmp_path.iterdir())

    engine = KokoroEngine(TTS_CFG.engines.kokoro, models_dir=tmp_path)
    with pytest.raises(
        EngineLoadError
    ):  # the real pins do not match the stand-in bytes
        engine.load()
    assert list(tmp_path.iterdir()) == []


def test_a_plain_http_model_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="https"):
        _ensure("http://example.invalid/model.onnx", "0" * 64, tmp_path / "m.onnx")


async def test_kokoro_that_was_not_loaded_cannot_speak() -> None:
    engine = KokoroEngine(TTS_CFG.engines.kokoro)
    with pytest.raises(EngineLoadError):
        [c async for c in engine.stream("Hello.", "neutral")]


@pytest.mark.slow
async def test_real_kokoro_speaks_in_british_male_on_the_cpu(
    record_property: Any,
) -> None:
    engine = KokoroEngine(TTS_CFG.engines.kokoro)
    started = time.perf_counter()
    await asyncio.to_thread(engine.load)  # fetches and verifies the files on first use
    load_s = time.perf_counter() - started
    for label, text in (
        ("first clause", "Well, I think so, yes."),
        ("sentence", "The build finished, and every test passed."),
    ):
        started = time.perf_counter()
        chunks = [c async for c in engine.stream(text, "neutral")]
        synth_s = time.perf_counter() - started
        (audio,) = chunks
        audio_s = len(audio) / engine.sample_rate
        rtf = synth_s / audio_s
        print(  # noqa: T201 - the measurement is the point of this test
            f"kokoro {label}: load={load_s:.1f}s first_audio={synth_s:.3f}s "
            f"audio={audio_s:.2f}s rtf={rtf:.2f}"
        )
        record_property(f"{label}_first_audio_s", synth_s)
        record_property(f"{label}_rtf", rtf)
        assert audio.dtype == np.float32 and audio.ndim == 1
        assert audio_s > 0.5 and float(np.abs(audio).max()) > 0.01
