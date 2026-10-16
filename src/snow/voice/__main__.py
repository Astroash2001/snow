"""`python -m snow.voice`: the voice worker (heartbeats come from the HubClient)."""

import asyncio

from snow.common.hubclient import HubClient
from snow.config.secrets import get_secret
from snow.config.settings import load_config
from snow.logging import configure
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import VoicePipeline
from snow.voice.sources import MicSource
from snow.voice.stt_groq import GroqStt
from snow.voice.turn import TurnEngine
from snow.voice.vad import EndOfTurn, VadDetector
from snow.voice.wake import WakeGate


async def _main() -> None:
    cfg = load_config("voice.toml", VoiceConfig)
    client = HubClient(role="voice")
    hub_task = asyncio.create_task(
        client.run()
    )  # heartbeats start as soon as it connects
    rate = cfg.audio.sample_rate
    w = cfg.wake
    pipeline = VoicePipeline(
        cfg,
        client,
        MicSource(cfg.audio.input_device, rate, cfg.audio.frame_samples),
        WakeGate(
            w.model,
            w.threshold,
            w.patience_frames,
            w.preroll_frames,
            w.refractory_s,
            rate,
        ),
        TurnEngine(cfg.turn, VadDetector(rate), EndOfTurn(rate), sample_rate=rate),
        GroqStt(cfg.stt.groq, get_secret),
    )
    await pipeline.start()
    try:
        await hub_task
    finally:
        await pipeline.stop()


if __name__ == "__main__":
    configure("voice")
    asyncio.run(_main())
