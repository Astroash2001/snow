"""`python -m snow.voice`: the voice worker (heartbeats come from the HubClient)."""

import asyncio

from snow.common.hubclient import HubClient
from snow.config.secrets import get_secret
from snow.config.settings import load_config
from snow.logging import configure
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import build_pipeline
from snow.voice.sources import MicSource
from snow.voice.stt_groq import GroqStt


async def _main() -> None:
    cfg = load_config("voice.toml", VoiceConfig)
    client = HubClient(role="voice")
    hub_task = asyncio.create_task(
        client.run()
    )  # heartbeats start as soon as it connects
    a = cfg.audio
    pipeline = build_pipeline(
        cfg,
        client,
        MicSource(a.input_device, a.sample_rate, a.frame_samples),
        GroqStt(cfg.stt.groq, get_secret),
    )
    client.on_event = pipeline.on_hub_event
    await pipeline.start()
    try:
        await hub_task
    finally:
        await pipeline.stop()


if __name__ == "__main__":
    configure("voice")
    asyncio.run(_main())
