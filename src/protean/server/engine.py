from __future__ import annotations

import asyncio
import logging
import signal

from typing import Type, Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.globals import g
from protean.utils.mixins import Message

from .subscription import Subscription

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, domain, test_mode: bool = False) -> None:
        self.domain = domain
        self.test_mode = test_mode
        self.exit_code = 0

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

    async def handle_message(
        self,
        handler_cls: Type[Union[BaseCommandHandler, BaseEventHandler]],
        message: Message,
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
            except Exception as exc:  # Includes handling `ConfigurationError`
                logger.error(
                    f"Error handling message {message.stream_name}-{message.id} "
                    f"in {handler_cls.__name__}"
                )
                logger.error(f"{str(exc)}")
                handler_cls.handle_error(exc, message)

                await self.shutdown(exit_code=1)
                return

            # Reset message context
            g.pop("message_in_context")

    async def shutdown(self, signal=None, exit_code=0):
        """Cleanup tasks tied to the service's shutdown."""
        try:
            if signal:
                logger.info(f"Received exit signal {signal.name}...")

            # Store the exit code
            self.exit_code = exit_code

            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            # Update read positions for each subscription
            update_tasks = []
            for _, subscription in self._subscriptions.items():
                update_tasks.append(
                    self.loop.create_task(
                        subscription.update_current_position_to_store()
                    )
                )

            [task.cancel() for task in tasks]

            logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            await asyncio.gather(*tasks, return_exceptions=True)

            # Wait for all update tasks to complete
            logger.info(
                f"Updating read positions for {len(update_tasks)} subscriptions"
            )
            await asyncio.gather(*update_tasks, return_exceptions=True)
        finally:
            if self.loop.is_running():
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
            if loop.is_running():
                asyncio.create_task(self.shutdown(exit_code=1))

        self.loop.set_exception_handler(handle_exception)

        if len(self._subscriptions) == 0:
            logger.info("No subscriptions to start. Exiting...")

        # Start consumption, one per subscription
        try:
            tasks = [
                self.loop.create_task(subscription.start())
                for _, subscription in self._subscriptions.items()
            ]

            if self.test_mode:
                # If in test mode, run until all tasks complete
                self.loop.run_until_complete(asyncio.gather(*tasks))
                # Then immediately call and await the shutdown directly
                self.loop.run_until_complete(self.shutdown())
            else:
                self.loop.run_forever()
        finally:
            self.loop.close()
            logger.debug("Successfully shutdown Protean Engine.")
