from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import sys

from protean.server.subscription import Subscription
from protean.utils.importlib import import_from_full_path

logging.basicConfig(
    level=logging.INFO,  # FIXME Pick up log level from config
    format="%(threadName)10s %(name)18s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("protean.server")


class Engine:
    def __init__(self, domain: "Domain", test_mode: str = False) -> None:
        self.domain = domain
        self.test_mode = test_mode

        self.loop = asyncio.new_event_loop()
        # FIXME Pick max workers from config
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=3,
            # Activate domain context before processing
            initializer=self.domain.domain_context().push,
        )

        self._event_subscriptions = {}
        for handler_name, record in self.domain.registry.event_handlers.items():
            self._event_subscriptions[handler_name] = Subscription(
                self.domain.event_store.store,
                self.loop,
                handler_name,
                record.cls.meta_.aggregate_cls.meta_.stream_name,
                record.cls,
            )

        self._command_subscriptions = {}
        for handler_name, record in self.domain.registry.command_handlers.items():
            self._command_subscriptions[handler_name] = Subscription(
                self.domain.event_store.store,
                self.loop,
                handler_name,
                f"{record.cls.meta_.aggregate_cls.meta_.stream_name}:command",
                record.cls,
            )

        # Track engine status
        self.SHUTTING_DOWN = False

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Engine:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def start_event_handler_subscriptions(self):
        for _, subscription in self._event_subscriptions.items():
            subscription.start()

    def start_command_handler_subscriptions(self):
        for _, subscription in self._command_subscriptions.items():
            subscription.start()

    def run(self):
        with self.domain.domain_context():
            try:
                logger.debug("Starting server...")

                self.start_event_handler_subscriptions()
                self.start_command_handler_subscriptions()

                if self.test_mode:
                    self.loop.call_soon(self.stop)

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
                logger.debug("Shutting down...")

                # Signal executor to finish pending futures and free resources
                self.executor.shutdown(wait=True)

                self.loop.stop()
                self.loop.close()

    def stop(self):
        self.SHUTTING_DOWN = True

        # Signal executor to finish pending futures and free resources
        self.executor.shutdown(wait=True)

        self.loop.stop()
        # self.loop.close()  # FIXME Why is `close` throwing an exception?
