"""Stand-in worker for supervisor tests: `python fake_worker.py <role>`.

Behaviour comes from the environment: FAKE_EXIT_AFTER_S + FAKE_EXIT_CODE exit with that
code; FAKE_HANG_AFTER_S blocks the event loop so heartbeats stop (a wedged worker).
"""

import asyncio
import os
import sys
import time
from typing import cast

from snow.common.hubclient import HubClient
from snow.contracts.wire import Role


async def main(role: Role) -> None:
    client = HubClient(role=role)
    runner = asyncio.create_task(client.run())
    exit_after = os.environ.get("FAKE_EXIT_AFTER_S")
    hang_after = os.environ.get("FAKE_HANG_AFTER_S")
    if exit_after is not None:
        await asyncio.sleep(float(exit_after))
        os._exit(int(os.environ.get("FAKE_EXIT_CODE", "0")))
    if hang_after is not None:
        await asyncio.sleep(float(hang_after))
        time.sleep(3600)  # noqa: ASYNC251 - blocking the loop IS the test
    await runner


if __name__ == "__main__":
    asyncio.run(main(cast(Role, sys.argv[1])))
