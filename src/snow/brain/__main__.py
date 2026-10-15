"""`python -m snow.brain`: run the brain worker under a HubClient."""

import asyncio

from snow.brain.worker import BrainWorker
from snow.common.hubclient import HubClient
from snow.logging import configure


async def _main() -> None:
    client = HubClient(role="brain")
    worker = BrainWorker(client.publish)
    client.on_event = worker.on_event
    client.on_snapshot = worker.on_snapshot
    await client.run()


if __name__ == "__main__":
    configure("brain")
    asyncio.run(_main())
