"""Developer-only commands (D-07): `snow dev say` and `snow dev kill`."""

import argparse
import asyncio
import contextlib
import io
import sys

from snow.common.hubclient import HubClient
from snow.config.settings import run_dir
from snow.contracts.events import Event, ReplyDelta, ReplyFinal, TranscriptFinal
from snow.contracts.wire import Command, DevKill, DevSay


def _no_hub() -> int:
    print("snow: the hub is not running (start it with `snow run`)", file=sys.stderr)
    return 1


async def _say(text: str, limit_s: float) -> bool:
    turn: str | None = None
    done = asyncio.Event()
    spoke = False

    async def on_event(event: Event) -> None:
        nonlocal turn, spoke
        if isinstance(event, TranscriptFinal) and event.text == text and turn is None:
            turn = event.turn_id
        elif turn is None or event.turn_id != turn:
            return
        elif isinstance(event, ReplyDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, ReplyFinal):
            spoke = bool(event.text)  # empty text = the silent all-providers-down case
            done.set()

    client = HubClient(role="dev", on_event=on_event)
    runner = asyncio.create_task(client.run())
    try:
        async with asyncio.timeout(limit_s):
            await client.connected.wait()
            await client.send_command(DevSay(text=text))
            await done.wait()
    except TimeoutError:
        return False
    finally:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner
    print()
    return spoke


def say(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="snow dev say")
    parser.add_argument("text")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    if not (run_dir() / "hub.json").exists():
        return _no_hub()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")  # pyright: ignore[reportUnknownMemberType]  # Windows consoles reject some glyphs
    if asyncio.run(_say(args.text, args.timeout)):
        return 0
    print("snow: no reply", file=sys.stderr)
    return 1


async def _send(command: Command) -> None:
    client = HubClient(role="dev")
    runner = asyncio.create_task(client.run())
    try:
        async with asyncio.timeout(10):
            await client.connected.wait()
            await client.send_command(command)
            await asyncio.sleep(0.2)  # let the frame flush before the socket closes
    finally:
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner


def kill(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="snow dev kill")
    parser.add_argument("worker", choices=["voice", "brain", "hud"])
    args = parser.parse_args(argv)
    if not (run_dir() / "hub.json").exists():
        return _no_hub()
    try:
        asyncio.run(_send(DevKill(worker=args.worker)))
    except TimeoutError:
        print("snow: could not reach the hub", file=sys.stderr)
        return 1
    return 0
