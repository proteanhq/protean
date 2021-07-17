import asyncio
import concurrent.futures
import logging
import sys

from protean.utils.importlib import import_from_string

logging.basicConfig(
    level=logging.INFO,  # FIXME Pick up log level from config
    format="%(threadName)10s %(name)18s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("Server")


class Server:
    def __init__(self, domain, package=None, broker="default"):
        self.domain = import_from_string(domain, package=package)
        self.broker = self.domain.brokers[broker]

    async def poll(self):
        """This works with `add_done_callback`"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            while True:
                logger.debug(f"Polling...")

                # while message := r.lpop("messages"):
                #     # Reconstruct message back to Command or Event

                #     # Collect registered Command or Event Handlers from Domain

                #     # Submit a task with Command handler, with a callback
                #     future = executor.submit(domain.handle, message)
                #     future.add_done_callback(handled)

                await asyncio.sleep(0.5)

    def run(self):
        asyncio.run(self.poll())
