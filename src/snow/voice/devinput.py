"""`snow dev inject-wav <path> [--realtime]`: drive the voice pipeline from a WAV file.

Developer-only input (D-07). Reads an existing file; never records or writes audio.
Events carry source `dev`, so the hub treats this process as the dev client.
"""

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

from snow.common.hubclient import HubClient
from snow.config.secrets import get_secret
from snow.config.settings import load_config, run_dir
from snow.contracts.events import Event, ReplyFinal, TranscriptFinal
from snow.voice.config import VoiceConfig
from snow.voice.pipeline import Publisher, VoicePipeline, build_pipeline
from snow.voice.sources import FileSource
from snow.voice.stt_groq import GroqStt

LIMIT_S = 60.0


def inject(
    path: Path,
    cfg: VoiceConfig,
    hub: Publisher,
    stt: GroqStt,
    *,
    realtime: bool = False,
) -> VoicePipeline:
    """The real pipeline over `path`, waiting for each reply like a listening user."""
    a = cfg.audio
    source = FileSource(
        path,
        realtime=realtime,
        sample_rate=a.sample_rate,
        frame_samples=a.frame_samples,
    )
    pipeline = build_pipeline(cfg, hub, source, stt, "dev")
    source.hold = lambda: pipeline.waiting_reply
    return pipeline


async def play(pipeline: VoicePipeline, limit_s: float = LIMIT_S) -> bool:
    """Run to the end of the file; False if `limit_s` ran out first."""
    await pipeline.start()
    try:
        async with asyncio.timeout(limit_s):
            await pipeline.wait_done()
    except TimeoutError:
        return False
    finally:
        await pipeline.stop()
    return True


async def _run(path: Path, realtime: bool) -> bool:
    cfg = load_config("voice.toml", VoiceConfig)
    client = HubClient(role="dev")
    stt = GroqStt(cfg.stt.groq, get_secret)
    pipeline = inject(path, cfg, client, stt, realtime=realtime)

    async def on_event(event: Event) -> None:
        await pipeline.on_hub_event(event)
        if isinstance(event, TranscriptFinal):
            print(f"you:  {event.text}")
        elif isinstance(event, ReplyFinal) and event.text:
            print(f"snow: {event.text}")

    client.on_event = on_event
    runner = asyncio.create_task(client.run())
    try:
        async with asyncio.timeout(10):
            await client.connected.wait()
        return await play(pipeline)
    finally:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="snow dev inject-wav",
        description="Play a WAV file through the voice pipeline as the dev client.",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--realtime", action="store_true", help="play at microphone speed"
    )
    args = parser.parse_args(argv)
    if not args.path.is_file():
        print(f"snow: no such file: {args.path}", file=sys.stderr)
        return 1
    if not (run_dir() / "hub.json").exists():
        print(
            "snow: the hub is not running (start it with `snow run`)", file=sys.stderr
        )
        return 1
    try:
        finished = asyncio.run(_run(args.path, args.realtime))
    except TimeoutError:
        print("snow: could not reach the hub", file=sys.stderr)
        return 1
    if not finished:
        print(f"snow: stopped after {LIMIT_S:.0f} s", file=sys.stderr)
    return 0
