"""`python -m snow.brain`: run the brain worker under a HubClient."""

import asyncio

from snow.brain.worker import BrainWorker
from snow.common.hubclient import HubClient
from snow.logging import configure


async def _main() -> None:
    client = HubClient(role="brain")
    client.on_event = BrainWorker(client.publish).on_event
    await client.run()


if __name__ == "__main__":
    configure("brain")
    asyncio.run(_main())
