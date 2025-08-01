from __future__ import annotations

import asyncio
import logging
import platform
import signal
import traceback
from typing import Type, Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.utils.globals import g
from protean.utils.mixins import Message

from .subscription.broker_subscription import BrokerSubscription
from .subscription.event_store_subscription import EventStoreSubscription
from .outbox_processor import OutboxProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class Engine:
    """
    The Engine class represents the Protean Engine that handles message processing and subscription management.
    """

    def __init__(self, domain, test_mode: bool = False, debug: bool = False) -> None:
        """
        Initialize the Engine.

        Modes:
        - Test Mode: If set to True, the engine will run in test mode and will exit after all tasks are completed.
        - Debug Mode: If set to True, the engine will run in debug mode and will log additional information.

        Args:
            domain (Domain): The domain object associated with the engine.
            test_mode (bool, optional): Flag to indicate if the engine is running in test mode. Defaults to False.
            debug (bool, optional): Flag to indicate if debug mode is enabled. Defaults to False.
        """
        self.domain = domain
        self.test_mode = (
            test_mode  # Flag to indicate if the engine is running in test mode
        )
        self.debug = debug  # Flag to indicate if debug mode is enabled
        self.exit_code = 0
        self.shutting_down = False  # Flag to indicate the engine is shutting down

        # Store original signal handlers for cleanup
        self._original_signal_handlers = {}

        if self.debug:
            logger.setLevel(logging.DEBUG)

        # Create a new event loop instead of getting the current one
        # This avoids fragility when the caller already has a running loop
        self.loop = asyncio.new_event_loop()

        # Gather all handlers
        self._subscriptions = {}
        for handler_name, handler_record in self.domain.registry.event_handlers.items():
            # Create a subscription for each event handler
            self._subscriptions[handler_name] = EventStoreSubscription(
                self,
                handler_record.cls.meta_.stream_category
                or handler_record.cls.meta_.part_of.meta_.stream_category,
                handler_record.cls,
                origin_stream=handler_record.cls.meta_.source_stream,
            )

        for (
            handler_name,
            handler_record,
        ) in self.domain.registry.command_handlers.items():
            # Create a subscription for each command handler
            self._subscriptions[handler_name] = EventStoreSubscription(
                self,
                f"{handler_record.cls.meta_.part_of.meta_.stream_category}:command",
                handler_record.cls,
            )

        for handler_name, handler_record in self.domain.registry.projectors.items():
            # Create a subscription for each projector
            for stream_category in handler_record.cls.meta_.stream_categories:
                self._subscriptions[f"{handler_name}-{stream_category}"] = (
                    EventStoreSubscription(
                        self,
                        stream_category,
                        handler_record.cls,
                    )
                )

        # Gather broker subscriptions
        self._broker_subscriptions = {}

        for (
            subscriber_name,
            subscriber_record,
        ) in self.domain.registry.subscribers.items():
            subscriber_cls = subscriber_record.cls
            broker_name = subscriber_cls.meta_.broker
            broker = self.domain.brokers[broker_name]
            stream = subscriber_cls.meta_.stream
            self._broker_subscriptions[subscriber_name] = BrokerSubscription(
                self,
                broker,
                stream,
                subscriber_cls,
            )

        # Gather outbox processors - one per database-broker provider combination
        self._outbox_processors = {}

        # Create an outbox processor for each database provider to each broker provider
        # Only if outbox is enabled in the domain
        if self.domain.config.get("enable_outbox", False):
            # Get the broker provider name from the config with validation
            outbox_config = self.domain.config.get("outbox", {})
            broker_provider_name = outbox_config.get("broker", "default")

            if broker_provider_name not in self.domain.brokers:
                raise ValueError(
                    f"Broker provider '{broker_provider_name}' not configured in domain"
                )

            messages_per_tick = outbox_config.get("messages_per_tick", 10)
            tick_interval = outbox_config.get("tick_interval", 1)

            # Create an outbox processor for each database provider
            for database_provider_name in self.domain.providers.keys():
                processor_name = f"outbox-processor-{database_provider_name}-to-{broker_provider_name}"
                self._outbox_processors[processor_name] = OutboxProcessor(
                    self,
                    database_provider_name,
                    broker_provider_name,
                    messages_per_tick=messages_per_tick,
                    tick_interval=tick_interval,
                )

    async def handle_broker_message(
        self, subscriber_cls: Type[BaseSubscriber], message: dict
    ) -> bool:
        """
        Handle a message received from the broker.

        Args:
            subscriber_cls (Type[BaseSubscriber]): The subscriber class to handle the message
            message (dict): The message to be handled

        Returns:
            bool: True if the message was processed successfully, False otherwise
        """

        if self.shutting_down:
            return False  # Skip handling if shutdown is in progress

        with self.domain.domain_context():
            try:
                subscriber = subscriber_cls()
                subscriber(message)

                logger.info(
                    f"{subscriber_cls.__name__} processed message successfully."
                )
                return True
            except Exception as exc:
                logger.error(
                    f"Error handling message in {subscriber_cls.__name__}: {str(exc)}"
                )
                # Print the stack trace
                logger.error(traceback.format_exc())
                try:
                    # Attempt to call error handler if it exists
                    if hasattr(subscriber_cls, "handle_error") and callable(
                        subscriber_cls.handle_error
                    ):
                        subscriber_cls.handle_error(exc, message)
                except Exception as error_exc:
                    logger.error(f"Error in error handler: {str(error_exc)}")
                    logger.error(traceback.format_exc())
                # Continue processing instead of shutting down
                return False

    async def handle_message(
        self,
        handler_cls: Type[Union[BaseCommandHandler, BaseEventHandler]],
        message: Message,
    ) -> bool:
        """
        Handle a message by invoking the appropriate handler class.

        Args:
            handler_cls (Type[Union[BaseCommandHandler, BaseEventHandler]]): The handler class
            message (Message): The message to be handled.

        Returns:
            bool: True if the message was processed successfully, False otherwise
        """
        if self.shutting_down:
            return False  # Skip handling if shutdown is in progress

        with self.domain.domain_context():
            # Set context from current message, so that further processes
            #   carry the metadata forward.
            g.message_in_context = message

            try:
                handler_cls._handle(message)

                logger.info(
                    f"{handler_cls.__name__} processed {message.type}-{message.id} successfully."
                )
                return True
            except Exception as exc:  # Includes handling `ConfigurationError`
                logger.error(
                    f"Error handling message {message.stream_name}-{message.id} "
                    f"in {handler_cls.__name__}: {str(exc)}"
                )
                # Print the stack trace
                logger.error(traceback.format_exc())
                try:
                    # Call the error handler if it exists
                    handler_cls.handle_error(exc, message)
                except Exception as error_exc:
                    logger.error(f"Error in error handler: {str(error_exc)}")
                    logger.error(traceback.format_exc())
                # Continue processing instead of shutting down
                # Reset message context
                g.pop("message_in_context", None)
                return False

            # Reset message context
            g.pop("message_in_context", None)

    def _setup_signal_handlers(self):
        """
        Set up signal handlers using the appropriate method based on the platform.

        On Unix-like systems, use asyncio.add_signal_handler for better integration with the event loop.
        On Windows, fall back to signal.signal as add_signal_handler is not available.
        """

        def signal_handler(sig, frame=None):
            """Signal handler for non-asyncio signal handling (Windows)"""
            if not self.shutting_down and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.shutdown(signal=sig), self.loop)

        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)

        # Check if we're on Windows or if add_signal_handler is not available
        if platform.system() == "Windows" or not hasattr(
            self.loop, "add_signal_handler"
        ):
            logger.debug(
                "Using signal.signal() for signal handling (Windows or unsupported platform)"
            )
            for s in signals:
                try:
                    # Store original handler for cleanup
                    self._original_signal_handlers[s] = signal.signal(s, signal_handler)
                except (OSError, ValueError) as e:
                    # Some signals may not be available on all platforms
                    logger.debug(f"Signal {s} not available on this platform: {e}")
        else:
            logger.debug(
                "Using asyncio.add_signal_handler() for signal handling (Unix-like)"
            )
            for s in signals:
                try:
                    self.loop.add_signal_handler(
                        s, lambda s=s: asyncio.create_task(self.shutdown(signal=s))
                    )
                except (OSError, ValueError) as e:
                    # Some signals may not be available on all platforms
                    logger.debug(f"Signal {s} not available on this platform: {e}")

    def _cleanup_signal_handlers(self):
        """
        Clean up signal handlers when shutting down.
        """
        if platform.system() == "Windows" or not hasattr(
            self.loop, "add_signal_handler"
        ):
            # Restore original signal handlers
            for sig, original_handler in self._original_signal_handlers.items():
                try:
                    signal.signal(sig, original_handler)
                except (OSError, ValueError):
                    pass  # Ignore errors during cleanup
        else:
            # Remove signal handlers from the event loop
            signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
            for s in signals:
                try:
                    self.loop.remove_signal_handler(s)
                except (OSError, ValueError):
                    pass  # Ignore errors during cleanup

    async def shutdown(self, signal=None, exit_code=0):
        """
        Cleanup tasks tied to the service's shutdown.

        Args:
            signal (Optional[signal]): The exit signal received. Defaults to None.
            exit_code (int): The exit code to be stored. Defaults to 0.
        """
        self.shutting_down = True  # Set shutdown flag

        try:
            msg = (
                f"Received exit signal {signal.name if hasattr(signal, 'name') else signal}. Shutting down..."
                if signal
                else "Shutting down..."
            )
            logger.info(msg)

            # Store the exit code
            self.exit_code = exit_code

            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

            # Shutdown subscriptions
            subscription_shutdown_tasks = [
                subscription.shutdown()
                for _, subscription in self._subscriptions.items()
            ]

            # Add broker subscriptions to shutdown tasks
            subscription_shutdown_tasks.extend(
                [
                    subscription.shutdown()
                    for _, subscription in self._broker_subscriptions.items()
                ]
            )

            # Add outbox processors to shutdown tasks
            subscription_shutdown_tasks.extend(
                [
                    processor.shutdown()
                    for _, processor in self._outbox_processors.items()
                ]
            )

            # Cancel outstanding tasks
            [task.cancel() for task in tasks]
            logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            await asyncio.gather(*tasks, return_exceptions=True)

            # Wait for subscriptions to shut down
            await asyncio.gather(*subscription_shutdown_tasks, return_exceptions=True)
            logger.info("All subscriptions have been shut down.")

            # Clean up signal handlers
            self._cleanup_signal_handlers()
        finally:
            self.loop.stop()

    def run(self):
        """
        Start the Protean Engine and run the subscriptions.
        """
        # Set the loop we created as the current event loop
        # This ensures we use our own loop instead of any existing one
        asyncio.set_event_loop(self.loop)

        logger.debug("Starting Protean Engine...")

        # Set up signal handlers using platform-appropriate method
        self._setup_signal_handlers()

        # Handle Exceptions
        def handle_exception(loop, context):
            msg = context.get("exception", context["message"])

            print(
                f"Exception caught: {msg}"
            )  # Debugging line to ensure this code path runs

            # Print the stack trace
            if "exception" in context and context["exception"]:
                traceback.print_stack(context["exception"])
                logger.error(f"Caught exception: {msg}")
                logger.info("Shutting down...")
                if loop.is_running() and not self.shutting_down:
                    self.shutting_down = (
                        True  # Set flag immediately to prevent multiple shutdown calls
                    )
                    asyncio.create_task(self.shutdown(exit_code=1))
                # Don't re-raise the exception - let the loop drain gracefully
            else:
                logger.error(f"Caught exception: {msg}")

        self.loop.set_exception_handler(handle_exception)

        if (
            len(self._subscriptions) == 0
            and len(self._broker_subscriptions) == 0
            and len(self._outbox_processors) == 0
        ):
            logger.info("No subscriptions to start. Exiting...")
            return

        subscription_tasks = [
            self.loop.create_task(subscription.start())
            for _, subscription in self._subscriptions.items()
        ]

        broker_subscription_tasks = [
            self.loop.create_task(subscription.start())
            for _, subscription in self._broker_subscriptions.items()
        ]

        outbox_processor_tasks = [
            self.loop.create_task(processor.start())
            for _, processor in self._outbox_processors.items()
        ]

        try:
            if self.test_mode:
                # If in test mode, run until all tasks complete
                self.loop.run_until_complete(
                    asyncio.gather(
                        *subscription_tasks,
                        *broker_subscription_tasks,
                        *outbox_processor_tasks,
                    )
                )
                # Then immediately call and await the shutdown directly
                self.loop.run_until_complete(self.shutdown())
            else:
                logger.info("Protean Engine is running...")
                self.loop.run_forever()
        finally:
            # Clean up signal handlers before closing the loop
            self._cleanup_signal_handlers()
            self.loop.close()
            logger.info("Protean Engine has stopped.")
