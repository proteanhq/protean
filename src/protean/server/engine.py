from __future__ import annotations

import asyncio
import logging
import signal

from typing import Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.globals import g
from protean.utils.importlib import import_from_full_path
from protean.utils.mixins import Message

from .subscription import Subscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, domain, test_mode: str = False) -> None:
        self.domain = domain
        self.test_mode = test_mode

        self.loop = asyncio.get_event_loop()

        # FIXME Gather all handlers
        self._subscriptions = {}
        for handler_name, record in self.domain.registry.event_handlers.items():
            self._subscriptions[handler_name] = Subscription(
                self,
                handler_name,
                record.cls.meta_.stream_name
                or record.cls.meta_.aggregate_cls.meta_.stream_name,
                record.cls,
                origin_stream_name=record.cls.meta_.source_stream,
            )

        for handler_name, record in self.domain.registry.command_handlers.items():
            self._subscriptions[handler_name] = Subscription(
                self,
                handler_name,
                f"{record.cls.meta_.aggregate_cls.meta_.stream_name}:command",
                record.cls,
            )

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Engine:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def handle_results(self, results, message):
        pass

    async def handle_message(
        self, handler_cls: Union[BaseCommandHandler, BaseEventHandler], message: Message
    ) -> None:
        with self.domain.domain_context():
            # Set context from current message, so that further processes
            #   carry the metadata forward.
            g.message_in_context = message

            try:
                handler_cls._handle(message)

                logger.info(
                    f"{handler_cls.__name__} processed {message.type}-{message.id} successfully."
                )
            except ConfigurationError as exc:
                logger.error(
                    f"Error while handling message {message.stream_name} in {handler_cls.__name__} - {str(exc)}"
                )
                raise
            except Exception as exc:
                logger.error(
                    f"Error while handling message {message.stream_name} in {handler_cls.__name__} - {str(exc)}"
                )
                # FIXME Implement mechanisms to track errors

            # Reset message context
            g.pop("message_in_context")

    async def shutdown(self, signal=None):
        """Cleanup tasks tied to the service's shutdown."""
        if signal:
            logger.info(f"Received exit signal {signal.name}...")

        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        [task.cancel() for task in tasks]

        logger.info(f"Cancelling {len(tasks)} outstanding tasks")
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

            import traceback

            traceback.print_stack(context.get("exception"))

            logger.error(f"Caught exception: {msg}")
            logger.info("Shutting down...")
            asyncio.create_task(self.shutdown(loop))

        self.loop.set_exception_handler(handle_exception)

        if len(self._subscriptions) == 0:
            logger.info("No subscriptions to start. Exiting...")

        # Start consumption, one per subscription
        try:
            for _, subscription in self._subscriptions.items():
                self.loop.create_task(subscription.start())

            self.loop.run_forever()
        finally:
            self.loop.close()
            logger.debug("Successfully shutdown Protean Engine.")
