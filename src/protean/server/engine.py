from __future__ import annotations

import asyncio
import logging
import signal

from collections import defaultdict

from protean.utils.importlib import import_from_full_path

from .subscription import Subscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


class Engine:
    def __init__(self, domain: "Domain", test_mode: str = False) -> None:
        self.domain = domain
        self.test_mode = test_mode

        self.loop = asyncio.get_event_loop()

        # FIXME Gather all handlers
        self._event_subscriptions = {}
        self._event_handlers = defaultdict(set)
        for handler_name, record in self.domain.registry.event_handlers.items():
            self._event_subscriptions[handler_name] = Subscription(
                self.domain.event_store.store,
                self.loop,
                handler_name,
                record.cls.meta_.aggregate_cls.meta_.stream_name,
                record.cls,
                test_mode=self.test_mode,
            )

            # Handler methods are instance methods, so we deconstruct the event handler,
            #   initialize a handler object and create a dictionary mapping event FQNs to instance methods.
            handler_obj = record.cls()
            for event_name, handler_methods in record.cls._handlers.items():
                for method in handler_methods:
                    instance_method = getattr(handler_obj, method.__name__)
                    self._event_handlers[event_name].add(instance_method)

        self._command_subscriptions = {}
        self._command_handlers = defaultdict(set)
        for handler_name, record in self.domain.registry.command_handlers.items():
            self._command_subscriptions[handler_name] = Subscription(
                self.domain.event_store.store,
                self.loop,
                handler_name,
                f"{record.cls.meta_.aggregate_cls.meta_.stream_name}:command",
                record.cls,
                test_mode=self.test_mode,
            )

            # Handler methods are instance methods, so we deconstruct the event handler,
            #   initialize a handler object and create a dictionary mapping event FQNs to instance methods.
            handler_obj = record.cls()
            for command_name, handler_methods in record.cls._handlers.items():
                for method in handler_methods:
                    instance_method = getattr(handler_obj, method.__name__)
                    self._command_handlers[command_name].add(instance_method)

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Engine:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def handle_results(self, results, message):
        pass

    async def handle_message(self, message) -> None:
        if message.kind == "EVENT":
            for handler_method in self._event_handlers[message.type]:
                handler_method(message.data)
        elif message.kind == "COMMAND":
            handler_method = next(iter(self._command_handlers[message.type]))
            handler_method(message.data)

    async def shutdown(self, signal=None):
        """Cleanup tasks tied to the service's shutdown."""
        if signal:
            logging.info(f"Received exit signal {signal.name}...")

        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        [task.cancel() for task in tasks]

        logging.info(f"Cancelling {len(tasks)} outstanding tasks")
        await asyncio.gather(*tasks, return_exceptions=True)
        self.loop.stop()

    def run(self):
        # Handle Signals
        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
        for s in signals:
            self.loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(self.shutdown(signal=s))
            )

        # Handle Exceptions
        def handle_exception(loop, context):
            # context["message"] will always be there; but context["exception"] may not
            msg = context.get("exception", context["message"])
            logging.error(f"Caught exception: {msg}")
            logging.info("Shutting down...")
            asyncio.create_task(self.shutdown(loop))

        self.loop.set_exception_handler(handle_exception)

        if not (
            len(self._event_subscriptions) > 0 or len(self._command_subscriptions) > 0
        ):
            logging.info("No subscriptions to start. Exiting...")

        # Start consumption, one per subscription
        try:
            for _, subscription in self._event_subscriptions.items():
                self.loop.create_task(subscription.start())

            for _, subscription in self._command_subscriptions.items():
                self.loop.create_task(subscription.start())

            self.loop.run_forever()
        finally:
            self.loop.close()
            logging.debug("Successfully shutdown Protean Engine.")
