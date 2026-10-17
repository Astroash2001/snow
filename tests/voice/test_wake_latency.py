"""HUD-03 hub half: wake.detected reaches another client within 50 ms (p95).

The HUD paint half of the 100 ms budget is proven by plan 01-19.
"""

import asyncio
import json
import statistics
import time

import numpy as np
from websockets.asyncio.client import connect

from snow.common.hubclient import HubClient
from snow.contracts.wire import Snapshot
from snow.voice.wake import WakeHit
from tests.conftest import HubHandle
from tests.voice.conftest import StubSource, make_pipeline, until

RUNS = 50
BUDGET_MS = 50.0


async def test_wake_detected_reaches_a_second_client_within_budget(
    hub: HubHandle, wake_models: None
) -> None:
    client = HubClient(hub.url, hub.token, role="voice")
    pipeline = make_pipeline(client, StubSource())
    await pipeline.start(listen=False)
    runner = asyncio.create_task(client.run())
    await until(client.connected.is_set)
    await pipeline.on_snapshot(Snapshot(muted=True))  # keep the stub closed; no audio
    hit = WakeHit(0.9, "hey_jarvis", [np.zeros(1280, dtype=np.int16)], 0)
    latencies_ms: list[float] = []
    async with connect(hub.url) as hud:
        await hud.send(json.dumps({"kind": "hello", "role": "hud", "token": hub.token}))
        for _ in range(RUNS):
            # The audio thread is where the real wake fires.
            await asyncio.to_thread(pipeline.on_wake, hit)
            async with asyncio.timeout(5):
                while True:
                    msg = json.loads(await hud.recv())
                    if (
                        msg["kind"] == "event"
                        and msg["event"]["type"] == "wake.detected"
                    ):
                        break
            latencies_ms.append((time.time_ns() - msg["event"]["ts_ns"]) / 1e6)
    runner.cancel()
    await pipeline.stop()
    p95 = statistics.quantiles(latencies_ms, n=20)[-1]
    assert p95 <= BUDGET_MS, f"p95 {p95:.1f} ms, worst {max(latencies_ms):.1f} ms"
