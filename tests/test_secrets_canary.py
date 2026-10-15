"""SAFE-09 / QUAL-03 canary: a stored key and the user's words never leak.

A scripted turn runs through the real hub and brain worker. The first provider answers
401 with a body that echoes the key; the second succeeds. Afterwards the canary must be
absent from log files, event rows, every WebSocket frame and every config file, and the
spoken text must be absent from log files (it lives only in the event log, D-18).
"""

import asyncio
import logging
import re
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from loguru import logger as loguru_logger

from snow.brain.worker import BrainWorker
from snow.common import hubclient
from snow.common.hubclient import HubClient
from snow.contracts.events import Event, ReplyFinal
from snow.contracts.wire import DevSay
from snow.logging import configure
from tests.conftest import (
    HubHandle,
    InMemoryKeyring,
    MockProvider,
    SnowDirs,
    openai_sse,
)

CANARY = "gsk_CANARY0123456789abcdef"
CANARY_2 = "xpl_CANARYTWO0123456789abc"
USER_TEXT = "zebra canary phrase"


@pytest.fixture
def logs(snow_dirs: SnowDirs) -> Iterator[Path]:
    configure("canary")
    yield snow_dirs.data / "logs"
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_snow_handler", False):
            root.removeHandler(h)
            h.close()
    loguru_logger.remove()


def _two_trusted_fast_entries(config: Path) -> None:
    toml = config / "models.toml"
    text = toml.read_text(encoding="utf-8")
    fast = (
        "[roles.fast]\nttft_timeout_s = 2.5\nchain = [\n"
        '  { provider = "groq", model = "openai/gpt-oss-120b" },\n'
        '  { provider = "experiential", model = "deepseek-v4-flash" },\n]\n\n'
    )
    toml.write_text(
        re.sub(r"\[roles\.fast\].*?(?=\[roles\.vision\])", fast, text, flags=re.S),
        encoding="utf-8",
    )


async def test_canary_and_spoken_text_never_leak(
    hub: HubHandle,
    snow_dirs: SnowDirs,
    memory_keyring: InMemoryKeyring,
    mock_provider: MockProvider,
    logs: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _two_trusted_fast_entries(snow_dirs.config)
    memory_keyring.set_password("snow", "groq", CANARY)
    memory_keyring.set_password("snow", "experiential", CANARY_2)
    echo = {"error": {"message": f"Incorrect API key provided: {CANARY}", "code": "x"}}
    mock_provider.responses += [
        httpx2.Response(401, json=echo),
        openai_sse(["Right away, sir."]),
    ]

    frames: list[str] = []
    real_send = HubClient._send  # pyright: ignore[reportPrivateUsage]
    real_validate = hubclient._WIRE.validate_json  # pyright: ignore[reportPrivateUsage]

    async def recording_send(self: HubClient, text: str) -> None:
        frames.append(text)
        await real_send(self, text)

    def recording_validate(raw: str | bytes, **kw: object) -> object:
        frames.append(raw if isinstance(raw, str) else raw.decode())
        return real_validate(raw, **kw)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(HubClient, "_send", recording_send)
    monkeypatch.setattr(hubclient._WIRE, "validate_json", recording_validate)  # pyright: ignore[reportPrivateUsage]

    inbox: asyncio.Queue[Event] = asyncio.Queue()

    async def collect(ev: Event) -> None:
        inbox.put_nowait(ev)

    brain = HubClient(hub.url, hub.token, role="brain")
    brain.on_event = BrainWorker(brain.publish).on_event
    dev = HubClient(hub.url, hub.token, role="dev", on_event=collect)
    runners = [asyncio.create_task(brain.run()), asyncio.create_task(dev.run())]
    try:
        async with asyncio.timeout(10):
            await brain.connected.wait()
            await dev.connected.wait()
            await dev.send_command(DevSay(text=USER_TEXT))
            while not isinstance(await inbox.get(), ReplyFinal):
                pass
    finally:
        for t in runners:
            t.cancel()
        await asyncio.gather(*runners, return_exceptions=True)

    assert len(mock_provider.requests) == 2  # the 401 really happened, then failover

    # A careless future log line that echoes the provider body must still be scrubbed.
    body = str(echo)
    careless = logging.getLogger("snow.brain.chain")
    careless.warning("provider body: %s", body)
    try:
        raise RuntimeError(body)
    except RuntimeError:
        careless.exception("provider failed")

    log_text = "".join(
        p.read_text(encoding="utf-8") for p in sorted(logs.glob("canary.log*"))
    )
    assert "llm_failed" in log_text  # the logger really was wired into the turn
    row_text = "\n".join(
        " | ".join(str(c) for c in tuple(r)) for r in hub.log.rows()
    )
    config_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in snow_dirs.config.rglob("*")
        if p.is_file()
    )
    frame_text = "\n".join(frames)

    assert USER_TEXT in row_text and USER_TEXT in frame_text  # the scan can see it
    assert "Right away, sir." in row_text
    for name, haystack in {
        "logs": log_text,
        "events": row_text,
        "frames": frame_text,
        "config": config_text,
    }.items():
        for key in (CANARY, CANARY_2, "CANARY0123456789", "CANARYTWO"):
            assert key not in haystack, f"{key!r} leaked into {name}"
    assert USER_TEXT not in log_text
    assert "Right away, sir." not in log_text
