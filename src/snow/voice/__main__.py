"""`python -m snow.voice`: the voice worker (heartbeats come from the HubClient)."""

import asyncio

from snow.common.hubclient import HubClient
from snow.config.secrets import get_secret
from snow.config.settings import load_config, repo_root
from snow.logging import configure
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import build_pipeline
from snow.voice.sources import MicSource
from snow.voice.stt_groq import GroqStt
from snow.voice.stt_local import LocalStt
from snow.voice.tts.base import EngineName, TtsEngine
from snow.voice.tts.cartesia import CartesiaEngine
from snow.voice.tts.chatterbox import ChatterboxEngine, GpuPolicy, resolve_reference
from snow.voice.tts.config import TtsConfig
from snow.voice.tts.kokoro import KokoroEngine
from snow.voice.tts.pocket import PocketEngine


async def _main() -> None:
    cfg = load_config("voice.toml", VoiceConfig)
    client = HubClient(role="voice")
    hub_task = asyncio.create_task(
        client.run()
    )  # heartbeats start as soon as it connects
    a = cfg.audio
    mic = MicSource(a.input_device, a.sample_rate, a.frame_samples)
    local = LocalStt(cfg.stt.local, a.sample_rate)  # loads in its own thread
    tts_cfg = load_config("tts.toml", TtsConfig)
    engines: dict[EngineName, TtsEngine] = {
        "pocket_tts": PocketEngine(tts_cfg.engines.pocket_tts),
        "cartesia": CartesiaEngine(tts_cfg.engines.cartesia, get_secret),
        "kokoro": KokoroEngine(tts_cfg.engines.kokoro),
        # The GPU voice: its own process, started only while the GpuPolicy allows it.
        "chatterbox": ChatterboxEngine(
            tts_cfg.engines.chatterbox,
            GpuPolicy(tts_cfg.engines.chatterbox),
            repo_root(),
            resolve_reference(tts_cfg.engines.chatterbox, tts_cfg.engines.pocket_tts),
        ),
    }
    pipeline = build_pipeline(
        cfg,
        client,
        mic,
        GroqStt(cfg.stt.groq, get_secret),
        local=local,
        tts=engines,  # the router loads only the engines tts.toml enables
        tts_cfg=tts_cfg,
        echo_cancel=tts_cfg.playout.echo_cancellation,
    )
    mic.on_health = pipeline.mic_health
    client.on_event = pipeline.on_hub_event
    client.on_command = pipeline.on_command
    client.on_snapshot = pipeline.on_snapshot
    # Fail safe (D-10): the mic opens only once the hub's snapshot says it is unmuted.
    await pipeline.start(listen=False)
    try:
        await hub_task
    finally:
        await pipeline.stop()
        local.close()


if __name__ == "__main__":
    configure("voice")
    asyncio.run(_main())
