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
    mic = MicSource(a.input_device, a.sample_rate, a.frame_samples)
    pipeline = build_pipeline(cfg, client, mic, GroqStt(cfg.stt.groq, get_secret))
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


if __name__ == "__main__":
    configure("voice")
    asyncio.run(_main())
