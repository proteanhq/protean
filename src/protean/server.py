from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sys

from typing import Dict

from protean.core.subscriber import BaseSubscriber
from protean.domain import Domain
from protean.globals import current_domain
from protean.infra.eventing import EventLog
from protean.infra.eventing import Message
from protean.utils import fully_qualified_name
from protean.utils.importlib import import_from_full_path

logging.basicConfig(
    level=logging.DEBUG,  # FIXME Pick up log level from config
    format="%(threadName)10s %(name)18s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("Server")


def handled():
    logger.info("1--->", "Done..")


class Server:
    def __init__(
        self, domain: Domain, broker: str = "default", test_mode: str = False
    ) -> None:
        self.domain = domain
        self.broker = self.domain.brokers[broker]
        self.test_mode = test_mode

        self.loop = asyncio.get_event_loop()

        self.SHUTTING_DOWN = False

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Server:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def subscribers_for(self, message: Dict) -> BaseSubscriber:
        object = self.domain.from_message(message)
        return self.broker._subscribers[fully_qualified_name(object.__class__)]

    async def push_messages(self) -> None:
        """Pick up published events and push to all register brokers"""
        logger.debug(f"Polling DB for new events to publish...")

        # Check if there are new messages to publish
        while object := current_domain.repository_for(EventLog).get_next_to_publish():
            message = Message.from_event_log(object)

            # FIXME Move this to separate threads?
            for _, broker in current_domain.brokers.items():
                broker.publish(message)

            # Mark event as picked up
            object.mark_published()
            current_domain.repository_for(EventLog).add(object)

        # Trampoline: self-schedule again if not shutting down
        if not self.SHUTTING_DOWN:
            self.loop.call_later(0.5, self.push_messages)

    async def poll_for_messages(self):
        """This works with `add_done_callback`"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            while True:
                logger.debug(f"Polling broker for new messages...")

                # FIXME Gather maximum `max_workers` messages and wait for the next cycle
                while message := self.broker.get_next():
                    # Reconstruct message back to Event
                    object = current_domain.from_message(message)

                    # Collect registered Subscribers from Domain
                    for subscriber in self.subscribers_for(object):
                        subscriber_object = subscriber(current_domain, object.__class__)
                        future = executor.submit(
                            subscriber_object.notify, object.to_dict()
                        )
                        future.add_done_callback(handled)

                await asyncio.sleep(0.5)

                if self.SHUTTING_DOWN:
                    break  # FIXME Wait until all tasks are completed?

    def run(self):
        try:
            self.loop.call_soon(self.push_messages)

            if self.test_mode:
                self.loop.call_soon(self.loop.stop)

            self.loop.run_forever()
        except KeyboardInterrupt:
            # Complete running tasks and cancel safely
            logger.debug("Caught Keyboard interrupt. Cancelling tasks...")
            self.SHUTTING_DOWN = True

            def shutdown_exception_handler(loop, context):
                if "exception" not in context or not isinstance(
                    context["exception"], asyncio.CancelledError
                ):
                    loop.default_exception_handler(context)

            self.loop.set_exception_handler(shutdown_exception_handler)

            ##################
            # CANCEL Elegantly
            ##################
            # Handle shutdown gracefully by waiting for all tasks to be cancelled
            # tasks = asyncio.gather(*asyncio.all_tasks(loop=loop), loop=loop, return_exceptions=True)
            # tasks.add_done_callback(lambda t: loop.stop())
            # tasks.cancel()

            # # Keep the event loop running until it is either destroyed or all
            # # tasks have really terminated
            # while not tasks.done() and not loop.is_closed():
            #     loop.run_forever()

            #####################
            # WAIT FOR COMPLETION
            #####################
            pending = asyncio.all_tasks(loop=self.loop)
            self.loop.run_until_complete(asyncio.gather(*pending))
        finally:
            logger.debug("Closing connection...")
            self.loop.close()

    def stop(self):
        self.SHUTTING_DOWN = True
        self.loop.stop()
