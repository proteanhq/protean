import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import SubscriptionType

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.server.engine import Engine

logger = logging.getLogger(__name__)


class BaseSubscription(ABC):
    """
    Base class for all subscription types in the Protean event-driven architecture.

    A subscription allows a subscriber to receive and process messages from a specific stream.
    It provides methods to start and stop the subscription, as well as process messages in batches.
    """

    # Human-readable identifier for the subscriber, set by each concrete
    # subscription in its ``__init__`` (typically ``fqn(self.handler)``). The
    # base class reads it for structured logging.
    subscriber_name: str

    def __init__(
        self,
        engine: "Engine",
        messages_per_tick: int = 10,
        tick_interval: float = 1,
    ) -> None:
        """
        Initialize the BaseSubscription object.

        Args:
            engine: The Protean engine instance.
            handler: The handler instance.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            tick_interval (float, optional): The interval between ticks (seconds). Defaults to 1.
        """
        self.engine = engine
        self.loop = engine.loop

        self.messages_per_tick = messages_per_tick
        self.tick_interval = tick_interval

        self.keep_going = True  # Initially set to keep going

    async def start(self) -> None:
        """
        Start the subscription.

        This method initializes the subscription and starts the polling loop.

        Returns:
            None
        """
        logger.info(
            "subscription.started",
            extra={"subscriber": self.subscriber_name},
        )

        # Perform backend-specific initialization
        await self.initialize()

        # Start the polling loop
        self.loop.create_task(self.poll())

    async def poll(self) -> None:
        """
        Polling loop for processing messages.

        This method continuously polls for new messages and processes them by calling the `tick` method.
        It uses cooperative multitasking to ensure smooth interleaving with other tasks.

        Returns:
            None
        """
        consecutive_errors = 0

        while self.keep_going and not self.engine.shutting_down:
            try:
                with self.engine.domain.domain_context():
                    # Process messages
                    await self.tick()

                    # Reset error counter on successful tick
                    consecutive_errors = 0

                    # Use minimal sleep for cooperative multitasking
                    # This ensures interleaving without blocking
                    if self.tick_interval > 0:
                        await asyncio.sleep(self.tick_interval)
                    else:
                        # Always yield control to allow other tasks to run
                        await asyncio.sleep(0)

            except asyncio.CancelledError:
                logger.info(
                    "subscription.cancelled",
                    extra={"subscriber": self.subscriber_name},
                )
                break

            except Exception:
                consecutive_errors += 1
                logger.exception(
                    "subscription.error",
                    extra={
                        "subscriber": self.subscriber_name,
                        "attempt": consecutive_errors,
                    },
                )
                # Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
                backoff = min(2 ** (consecutive_errors - 1), 30)
                await asyncio.sleep(backoff)

    async def tick(self) -> None:
        """
        This method retrieves the next batch of messages to process and calls the `process_batch` method
        to handle each message.

        Returns:
            None
        """
        messages = await self.get_next_batch_of_messages()
        if messages:
            await self.process_batch(messages)

    async def shutdown(self) -> None:
        """
        Shutdown the subscription.

        This method signals the subscription to stop polling and performs any necessary cleanup.

        Returns:
            None
        """
        self.keep_going = False  # Signal to stop polling
        await self.cleanup()
        logger.info(
            "subscription.shutdown",
            extra={"subscriber": self.subscriber_name},
        )

    async def initialize(self) -> None:
        """
        Perform backend-specific initialization.

        This method should be implemented by subclasses to handle any initialization
        specific to their backend (event store, broker, etc.).

        Returns:
            None
        """
        pass

    @abstractmethod
    async def get_next_batch_of_messages(self) -> list[Any]:
        """
        Get the next batch of messages to process.

        This method should be implemented by subclasses to retrieve messages
        from their specific backend. The element type of the returned list is
        backend-specific (domain ``Message``, broker ``(id, payload)`` tuples,
        ``Outbox`` rows, ...), hence the ``list[Any]`` contract at the port.

        Returns:
            The next batch of messages to process.
        """

    @abstractmethod
    async def process_batch(self, messages: Any) -> int:
        """
        Process a batch of messages.

        This method should be implemented by subclasses to handle the processing
        of messages specific to their backend. ``messages`` is backend-specific
        (see :meth:`get_next_batch_of_messages`), hence typed ``Any`` at the port.

        Args:
            messages: The batch of messages to process.

        Returns:
            int: The number of messages processed successfully.
        """

    async def cleanup(self) -> None:
        """
        Perform any cleanup tasks during shutdown.

        This method should be implemented by subclasses to handle any cleanup
        specific to their backend.

        Returns:
            None
        """
        pass


def event_store_subscription_handlers(domain: "Domain") -> list[str]:
    """Return the names of handlers whose subscriptions resolve to EVENT_STORE.

    Event-store subscriptions read directly from the event store and have no
    cluster-wide ownership: every worker reading the same stream processes the
    same events. They are therefore single-writer, and running more than one
    worker double-processes their events. Entry points use this helper to refuse
    to start multiple workers when any such subscription exists.

    The handler groups iterated here mirror those that
    :meth:`Engine._register_handler_subscriptions
    <protean.server.engine.Engine._register_handler_subscriptions>` turns into
    subscriptions — event handlers, command handlers, projectors, and process
    managers. Broker subscribers are intentionally excluded: they use a separate
    ``BrokerSubscription`` path, and whether that path is multi-worker-safe is a
    property of the broker adapter (Redis Streams consumer groups distribute
    across workers; Redis Pub/Sub and the in-memory ``inline`` broker do not),
    not of this guard. This guard only governs the event-store path. Keep the two
    lists in sync if a new handler group is ever added to the engine.

    Command handlers are a deliberate over-approximation: the engine groups
    them by stream category into one ``CommandDispatcher`` per group and
    resolves that dispatcher's subscription type from only the first handler
    registered in the group, but this helper resolves each command-handler
    class independently. A handler sharing a stream category with an
    event-store handler can therefore be reported here even if the group's
    actual runtime subscription resolves to ``stream``. This is intentional:
    the helper must never miss a real event-store subscription, and the
    conservative direction for a safety guard is to occasionally over-block
    rather than risk under-blocking.

    Args:
        domain: An initialized domain whose registry has been populated.

    Returns:
        The names of registered handlers resolving to event-store
        subscriptions, in registry order. Empty when every handler resolves to a
        stream subscription or the domain has no handlers.
    """
    resolver = ConfigResolver(domain)
    registry = domain.registry
    handler_groups = (
        registry.event_handlers,
        registry.command_handlers,
        registry.projectors,
        registry.process_managers,
    )

    offenders: list[str] = []
    for group in handler_groups:
        for record in group.values():
            config = resolver.resolve(record.cls)
            if config.subscription_type == SubscriptionType.EVENT_STORE:
                offenders.append(record.name)

    return offenders


def event_store_multi_worker_error(handler_names: list[str], num_workers: int) -> str:
    """Build the actionable error shown when multi-worker startup is refused.

    Shared by the ``protean server`` CLI guard and the programmatic
    :class:`~protean.server.supervisor.Supervisor` guard so both entry points
    speak with one voice.

    Args:
        handler_names: The offending event-store handler names.
        num_workers: The requested worker count (``> 1``).

    Returns:
        A multi-line message naming the offending handlers and the three ways
        forward.
    """
    listed = "\n".join(f"  - {name}" for name in handler_names)
    return (
        f"Refusing to start {num_workers} workers: the following handler(s) use "
        f"event-store subscriptions, which are single-writer (they read directly "
        f"from the event store with no cluster-wide ownership). Running more than "
        f"one worker would process the same events in every worker, "
        f"double-processing them:\n"
        f"{listed}\n"
        f"Resolve this by either:\n"
        f"  - running a single worker,\n"
        f'  - switching these handlers to stream subscriptions (subscription_type = "stream"), '
        f"which coordinate across workers via Redis consumer groups, or\n"
        f"  - explicitly acknowledging the risk (CLI: --allow-event-store-multiworker; "
        f"Supervisor: acknowledge_event_store_risk=True)."
    )


__all__ = [
    "BaseSubscription",
    "event_store_subscription_handlers",
    "event_store_multi_worker_error",
]
