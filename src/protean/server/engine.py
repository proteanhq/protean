import asyncio
import logging
import platform
import signal
import time
import traceback
from collections import defaultdict
from typing import Type, Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.subscriber import BaseSubscriber
from protean.exceptions import ConfigurationError
from protean.utils.globals import g
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
    new_correlation_id,
)
from protean.utils.processing import processing_priority
from protean.utils.telemetry import (
    extract_context_from_traceparent,
    get_tracer,
    set_span_error,
)

from .subscription.broker_subscription import BrokerSubscription
from .subscription.factory import SubscriptionFactory
from .tracing import TraceEmitter
from .outbox_processor import OutboxProcessor

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """Routes commands from a single stream to the correct command handler.

    Instead of creating N separate subscriptions (one per command handler) on the
    same stream category, the engine creates ONE subscription with a CommandDispatcher
    that routes each command to its designated handler.
    """

    def __init__(
        self,
        stream_category: str,
        handler_map: dict[str, Type[BaseCommandHandler]],
        source_handler_cls: Type[BaseCommandHandler],
    ) -> None:
        """
        Args:
            stream_category: The stream category this dispatcher covers.
            handler_map: Dict mapping command __type__ string to handler class.
            source_handler_cls: One of the handler classes, used to inherit
                subscription configuration (meta_) for the factory.
        """
        self._stream_category = stream_category
        self._handler_map = handler_map
        self._last_resolved_handler: Type[BaseCommandHandler] | None = None
        self._last_resolved_item: object | None = None

        # Identity attributes for fqn() and logging
        self.__name__ = f"Commands:{stream_category}"
        self.__qualname__ = self.__name__
        self.__module__ = "protean.server.engine"

        # Copy meta_ from the source handler so ConfigResolver can resolve
        # subscription settings (type, profile, tick interval, etc.)
        self.meta_ = source_handler_cls.meta_

    def _to_domain_object(self, message: Message | object) -> object:
        """Convert a message to its domain object, using cached result if available."""
        if self._last_resolved_item is not None:
            item = self._last_resolved_item
            self._last_resolved_item = None
            return item
        return message.to_domain_object() if isinstance(message, Message) else message

    def resolve_handler(
        self, message: Message | object
    ) -> Type[BaseCommandHandler] | None:
        """Look up the specific handler class for a message.

        Caches the deserialized domain object so that _handle() can reuse it
        without deserializing the message twice.

        Returns:
            The handler class, or None if no handler is registered for this command type.
        """
        item = message.to_domain_object() if isinstance(message, Message) else message
        if item is None:
            logger.warning(
                f"Failed to deserialize message in stream '{self._stream_category}'"
            )
            return None
        self._last_resolved_item = item
        command_type = item.__class__.__type__
        return self._handler_map.get(command_type)

    def _handle(self, message: Message | object) -> object | None:
        """Route the message to the correct command handler."""
        item = self._to_domain_object(message)
        if item is None:
            logger.warning(
                f"Failed to deserialize message in stream '{self._stream_category}'"
            )
            return None
        command_type = item.__class__.__type__
        handler_cls = self._handler_map.get(command_type)
        self._last_resolved_handler = handler_cls

        if handler_cls is None:
            logger.warning(
                f"No command handler registered for '{command_type}' "
                f"in stream '{self._stream_category}'"
            )
            return None

        return handler_cls._handle(item)

    def handle_error(self, exc: Exception, message: Message | object) -> None:
        """Delegate error handling to the resolved handler."""
        handler_cls = self._last_resolved_handler
        if handler_cls and hasattr(handler_cls, "handle_error"):
            handler_cls.handle_error(exc, message)


def _extract_source_message_id(message: dict) -> str | None:
    """Extract the source event's message_id from an incoming broker message.

    When Protean publishes events to a broker, the original event store
    message_id is embedded at ``metadata.headers.id``.  This is the
    identity that downstream commands should use as their ``causation_id``
    so that the Observatory can stitch cross-domain causation trees.

    Returns ``None`` when the payload does not carry a recognizable
    source message_id (e.g. a raw external message not published by
    Protean).
    """
    try:
        value = message["metadata"]["headers"]["id"]
    except (KeyError, TypeError):
        return None

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_correlation_id(message: dict) -> str:
    """Extract correlation_id from an incoming broker message dict.

    Checks the Protean external message format paths, in order:
    ``metadata.domain.correlation_id``, ``metadata.correlation_id``,
    and top-level ``correlation_id``.  Returns a fresh UUID when the
    incoming message carries no usable correlation context (the subscriber
    acts as an ACL and legitimately starts a new causal chain).
    Empty or whitespace-only values are treated as missing.
    """

    def _normalize(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    for path in (
        ("metadata", "domain", "correlation_id"),
        ("metadata", "correlation_id"),
        ("correlation_id",),
    ):
        try:
            current: object = message
            for key in path:
                current = current[key]  # type: ignore[index]
        except (KeyError, TypeError):
            continue

        normalized = _normalize(current)
        if normalized is not None:
            return normalized

    return new_correlation_id()


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

        # Initialize trace emitter for real-time message tracing
        try:
            observatory_config = domain.config.get("observatory", {})
            trace_retention_days = int(
                observatory_config.get("trace_retention_days", 7)
            )
        except (AttributeError, TypeError, ValueError):
            trace_retention_days = 7
        self.emitter = TraceEmitter(domain, trace_retention_days=trace_retention_days)

        # Create a new event loop instead of getting the current one
        # This avoids fragility when the caller already has a running loop
        self.loop = asyncio.new_event_loop()

        # Initialize subscription factory for creating subscriptions
        self._subscription_factory = SubscriptionFactory(self)

        # Gather all handler subscriptions
        self._subscriptions = {}
        self._register_handler_subscriptions()

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
        if self.domain.has_outbox:
            logger.debug("Outbox enabled, initializing processors")
            # Get the broker provider name from the config with validation
            outbox_config = self.domain.config.get("outbox", {})
            broker_provider_name = outbox_config.get("broker", "default")

            if broker_provider_name not in self.domain.brokers:
                raise ValueError(
                    f"Broker provider '{broker_provider_name}' not configured in domain"
                )

            messages_per_tick = outbox_config.get("messages_per_tick", 10)
            tick_interval = outbox_config.get("tick_interval", 1)
            logger.debug(
                f"Outbox configuration: batch_size={messages_per_tick}, interval={tick_interval}s"
            )

            # Create an outbox processor for each managed database provider
            for database_provider_name, provider in self.domain.providers.items():
                if not provider.managed:
                    continue
                processor_name = f"outbox-processor-{database_provider_name}-to-{broker_provider_name}"
                logger.debug(f"Creating outbox processor: {processor_name}")
                self._outbox_processors[processor_name] = OutboxProcessor(
                    self,
                    database_provider_name,
                    broker_provider_name,
                    messages_per_tick=messages_per_tick,
                    tick_interval=tick_interval,
                )

            # Create external outbox processors for published event dispatch
            external_brokers: list[str] = outbox_config.get("external_brokers", [])
            for ext_broker_name in external_brokers:
                if ext_broker_name not in self.domain.brokers:
                    raise ValueError(
                        f"External broker '{ext_broker_name}' configured in "
                        f"outbox.external_brokers but not found in domain "
                        f"broker configuration"
                    )
                for database_provider_name, provider in self.domain.providers.items():
                    if not provider.managed:
                        continue
                    processor_name = f"outbox-processor-{database_provider_name}-to-{ext_broker_name}-external"
                    logger.debug(
                        f"Creating external outbox processor: {processor_name}"
                    )
                    self._outbox_processors[processor_name] = OutboxProcessor(
                        self,
                        database_provider_name,
                        ext_broker_name,
                        messages_per_tick=messages_per_tick,
                        tick_interval=tick_interval,
                        is_external=True,
                    )

            # Verify outbox repos are initialised and DAO-accessible
            for provider_name, outbox_repo in self.domain._outbox_repos.items():
                try:
                    outbox_repo._dao  # noqa: B018
                except Exception:
                    raise ConfigurationError(
                        f"Outbox table not found for provider '{provider_name}'. "
                        "Run 'protean db setup' or 'protean db setup-outbox' to create it."
                    )
        else:
            logger.debug("Outbox disabled")

    @property
    def subscription_factory(self) -> SubscriptionFactory:
        """Get the subscription factory used to create subscriptions."""
        return self._subscription_factory

    def _register_handler_subscriptions(self) -> None:
        """Register subscriptions for all event handlers, command handlers, and projectors.

        This method iterates through all registered handlers and creates appropriate
        subscriptions using the SubscriptionFactory. The factory handles configuration
        resolution and subscription type selection.
        """
        # Register event handler subscriptions
        for handler_name, handler_record in self.domain.registry.event_handlers.items():
            handler_cls = handler_record.cls
            stream_category = self._infer_stream_category(handler_cls)

            self._subscriptions[handler_name] = (
                self._subscription_factory.create_subscription(
                    handler=handler_cls,
                    stream_category=stream_category,
                )
            )
            logger.debug(
                f"Registered subscription for event handler '{handler_name}' "
                f"on stream '{stream_category}'"
            )

        # Register command handler subscriptions — one per stream category
        # Group all command handlers by their stream category, then create a single
        # CommandDispatcher subscription per group. This ensures each command message
        # is read by exactly one subscription and routed to the correct handler.
        handlers_by_stream = defaultdict(list)
        for (
            handler_name,
            handler_record,
        ) in self.domain.registry.command_handlers.items():
            handler_cls = handler_record.cls
            stream_category = self._infer_stream_category(handler_cls)
            handlers_by_stream[stream_category].append(handler_cls)

        for stream_category, handler_classes in handlers_by_stream.items():
            # Build command_type -> handler_cls mapping
            handler_map = {}
            handler_names = []
            for handler_cls in handler_classes:
                handler_names.append(handler_cls.__name__)
                for command_type in handler_cls._handlers:
                    if command_type != "$any":
                        handler_map[command_type] = handler_cls

            dispatcher = CommandDispatcher(
                stream_category, handler_map, handler_classes[0]
            )

            subscription_key = f"commands:{stream_category}"
            self._subscriptions[subscription_key] = (
                self._subscription_factory.create_subscription(
                    handler=dispatcher,
                    stream_category=stream_category,
                )
            )
            logger.debug(
                f"Registered command subscription on stream '{stream_category}' "
                f"with handlers: {', '.join(handler_names)}"
            )

        # Register projector subscriptions (one per stream category)
        for handler_name, handler_record in self.domain.registry.projectors.items():
            handler_cls = handler_record.cls

            # Projectors may subscribe to multiple stream categories
            for stream_category in handler_cls.meta_.stream_categories:
                subscription_key = f"{handler_name}-{stream_category}"

                self._subscriptions[subscription_key] = (
                    self._subscription_factory.create_subscription(
                        handler=handler_cls,
                        stream_category=stream_category,
                    )
                )
                logger.debug(
                    f"Registered subscription for projector '{handler_name}' "
                    f"on stream '{stream_category}'"
                )

        # Register process manager subscriptions (one per stream category)
        for pm_name, pm_record in self.domain.registry.process_managers.items():
            pm_cls = pm_record.cls

            for stream_category in pm_cls.meta_.stream_categories:
                subscription_key = f"{pm_name}-{stream_category}"

                self._subscriptions[subscription_key] = (
                    self._subscription_factory.create_subscription(
                        handler=pm_cls,
                        stream_category=stream_category,
                    )
                )
                logger.debug(
                    f"Registered subscription for process manager '{pm_name}' "
                    f"on stream '{stream_category}'"
                )

    def _infer_stream_category(
        self, handler_cls: Type[Union[BaseCommandHandler, BaseEventHandler]]
    ) -> str:
        """Infer the stream category for a handler.

        Resolution priority:
        1. Handler Meta.stream_category (explicit)
        2. Associated aggregate's stream_category (via part_of)
        3. Raise error if cannot infer

        Args:
            handler_cls: The handler class to infer stream category for.

        Returns:
            The inferred stream category.

        Raises:
            ValueError: If stream category cannot be inferred.
        """
        meta = getattr(handler_cls, "meta_", None)
        if meta is None:
            raise ValueError(
                f"Handler '{handler_cls.__name__}' has no meta_ attribute. "
                f"Cannot infer stream category."
            )

        # Priority 1: Explicit stream_category on handler
        stream_category = getattr(meta, "stream_category", None)
        if stream_category:
            return stream_category

        # Priority 2: Infer from part_of aggregate
        part_of = getattr(meta, "part_of", None)
        if part_of:
            aggregate_meta = getattr(part_of, "meta_", None)
            if aggregate_meta:
                aggregate_stream = getattr(aggregate_meta, "stream_category", None)
                if aggregate_stream:
                    return aggregate_stream

        # Cannot infer - raise error
        raise ValueError(
            f"Cannot infer stream category for handler '{handler_cls.__name__}'. "
            f"Either set 'stream_category' on the handler or associate it with an "
            f"aggregate using 'part_of'."
        )

    async def handle_broker_message(
        self,
        subscriber_cls: Type[BaseSubscriber],
        message: dict,
        *,
        message_id: str | None = None,
        stream: str | None = None,
        worker_id: str | None = None,
    ) -> bool:
        """
        Handle a message received from the broker.

        Args:
            subscriber_cls (Type[BaseSubscriber]): The subscriber class to handle the message
            message (dict): The message to be handled
            message_id (str | None): The broker-assigned message identifier
            stream (str | None): The broker stream from which the message was consumed

        Returns:
            bool: True if the message was processed successfully, False otherwise
        """

        if self.shutting_down:
            return False  # Skip handling if shutdown is in progress

        with self.domain.domain_context():
            # Set message context so subscribers (and any commands they
            # dispatch) participate in the same tracing infrastructure
            # as internal handlers.  Commands processed by the subscriber
            # will inherit causation_id = message_id automatically.
            if message_id is not None and stream is not None:
                # Extract correlation_id from the incoming broker message.
                # Protean's external message format nests it under
                # metadata.domain.correlation_id.  If not present,
                # generate a fresh ID (subscriber as ACL starts a new chain).
                correlation_id = _extract_correlation_id(message)

                # Prefer the source event's message_id from the payload
                # over the broker delivery ID.  The delivery ID (e.g. a
                # Redis Stream timestamp like "1734567890-0") is broker-
                # specific and doesn't match any event store record.
                # Using the source message_id ensures downstream commands
                # get the correct causation_id for cross-domain causation
                # trees.
                source_id = _extract_source_message_id(message) or message_id

                g.message_in_context = Message(
                    data=message,
                    metadata=Metadata(
                        headers=MessageHeaders(id=source_id, stream=stream),
                        domain=DomainMeta(
                            kind="BROKER_MESSAGE",
                            correlation_id=correlation_id,
                        ),
                    ),
                )

            try:
                subscriber = subscriber_cls()
                subscriber(message)

                logger.debug(f"Message processed by {subscriber_cls.__name__}")
                return True
            except Exception as exc:
                logger.exception(f"Error in {subscriber_cls.__name__}: {exc}")
                try:
                    subscriber_cls.handle_error(exc, message)
                except Exception as error_exc:
                    logger.exception(f"Error handler failed: {error_exc}")
                # Continue processing instead of shutting down
                return False
            finally:
                g.pop("message_in_context", None)

    async def handle_message(
        self,
        handler_cls: Type[Union[BaseCommandHandler, BaseEventHandler]],
        message: Message,
        worker_id: str | None = None,
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

        # Propagate metadata extensions into g so that handlers see the
        # same context (tenant_id, user_id, etc.) that enrichers injected
        # when the event/command was originally raised.
        extensions = {}
        if message.metadata and message.metadata.extensions:
            extensions = message.metadata.extensions

        with self.domain.domain_context(**extensions):
            # Set context from current message, so that further processes
            #   carry the metadata forward.
            g.message_in_context = message

            # Initialize variables used in the except block to avoid
            # UnboundLocalError if an exception occurs before assignment.
            message_id = "unknown"
            message_type = "unknown"
            stream = "unknown"
            handler_name = "unknown"
            start_time = time.monotonic()
            correlation_id = None
            causation_id = None

            try:
                assert message.metadata is not None, "Message metadata cannot be None"

                message_id = message.metadata.headers.id or "unknown"
                message_type = message.metadata.headers.type or "unknown"
                stream = (
                    message.metadata.domain.stream_category
                    if message.metadata.domain
                    else None
                ) or "unknown"
                correlation_id = (
                    message.metadata.domain.correlation_id
                    if message.metadata.domain
                    else None
                )
                causation_id = (
                    message.metadata.domain.causation_id
                    if message.metadata.domain
                    else None
                )

                # Resolve actual handler name (for CommandDispatcher, look up the specific handler)
                if hasattr(handler_cls, "resolve_handler"):
                    resolved = handler_cls.resolve_handler(message)
                    handler_name = (
                        resolved.__name__ if resolved else handler_cls.__name__
                    )
                else:
                    handler_name = handler_cls.__name__

                # Emit handler.started trace (includes payload for lifecycle view)
                self.emitter.emit(
                    event="handler.started",
                    stream=stream,
                    message_id=message_id,
                    message_type=message_type,
                    handler=handler_name,
                    payload=message.data,
                    worker_id=worker_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                )

                start_time = time.monotonic()

                tracer = get_tracer(self.domain)

                # Extract incoming traceparent as parent OTEL context so the
                # processing span becomes a child of the distributed trace.
                parent_ctx = None
                if message.metadata and message.metadata.headers:
                    parent_ctx = extract_context_from_traceparent(
                        message.metadata.headers.traceparent
                    )

                with tracer.start_as_current_span(
                    "protean.engine.handle_message",
                    context=parent_ctx,
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    span.set_attribute("protean.handler.name", handler_name)
                    span.set_attribute("protean.message.type", message_type)
                    span.set_attribute("protean.message.id", message_id)
                    span.set_attribute("protean.stream_category", stream)
                    if worker_id:
                        span.set_attribute("protean.worker_id", worker_id)

                    # Determine subscription type from handler
                    if hasattr(handler_cls, "resolve_handler"):
                        span.set_attribute(
                            "protean.subscription_type", "command_dispatcher"
                        )
                    elif issubclass(handler_cls, BaseProcessManager):
                        span.set_attribute(
                            "protean.subscription_type", "process_manager"
                        )
                    elif issubclass(handler_cls, BaseEventHandler):
                        span.set_attribute("protean.subscription_type", "event_handler")
                    elif issubclass(handler_cls, BaseCommandHandler):
                        span.set_attribute(
                            "protean.subscription_type", "command_handler"
                        )

                    try:
                        # Reconstruct the processing priority context from the
                        # message metadata so that UoW.commit() tags outbox records
                        # with the correct priority (important for async commands
                        # where the original processing_priority() context is gone).
                        msg_priority = 0
                        if message.metadata.domain:
                            msg_priority = getattr(
                                message.metadata.domain, "priority", 0
                            )
                        with processing_priority(msg_priority):
                            handler_cls._handle(message)
                    except Exception as exc:
                        set_span_error(span, exc)
                        raise

                duration_ms = (time.monotonic() - start_time) * 1000
                logger.debug(
                    f"Processed {message_type} "
                    f"(ID: {message_id[:8]}...) in {handler_name} [{duration_ms:.1f}ms]"
                )

                # Emit handler.completed trace
                self.emitter.emit(
                    event="handler.completed",
                    stream=stream,
                    message_id=message_id,
                    message_type=message_type,
                    handler=handler_name,
                    duration_ms=round(duration_ms, 2),
                    worker_id=worker_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                )

                # Emit pm.transition trace for process managers
                if issubclass(handler_cls, BaseProcessManager):
                    self.emitter.emit(
                        event="pm.transition",
                        stream=stream,
                        message_id=message_id,
                        message_type=message_type,
                        handler=handler_name,
                        metadata={
                            "pm_type": handler_cls.__name__,
                            "pm_stream_category": getattr(
                                handler_cls.meta_, "stream_category", None
                            ),
                        },
                        duration_ms=round(duration_ms, 2),
                        worker_id=worker_id,
                        correlation_id=correlation_id,
                        causation_id=causation_id,
                    )

                return True
            except Exception as exc:  # Includes handling `ConfigurationError`
                duration_ms = (time.monotonic() - start_time) * 1000
                logger.exception(
                    f"Failed to process {message_type} "
                    f"(ID: {message_id[:8]}...) in {handler_name}: {exc}"
                )

                # Emit handler.failed trace
                self.emitter.emit(
                    event="handler.failed",
                    stream=stream,
                    message_id=message_id,
                    message_type=message_type,
                    status="error",
                    handler=handler_name,
                    duration_ms=round(duration_ms, 2),
                    error=str(exc),
                    worker_id=worker_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                )

                try:
                    # Call the error handler if it exists
                    handler_cls.handle_error(exc, message)
                except Exception as error_exc:
                    logger.exception(f"Error handler failed: {error_exc}")
                # Continue processing instead of shutting down
                return False
            finally:
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
                    # Create a proper signal handler that ensures task creation works
                    # even when called from a signal context
                    def handle_signal(sig=s):
                        if not self.shutting_down:
                            # Ensure we create the task in the proper context
                            self.loop.call_soon_threadsafe(
                                lambda: asyncio.create_task(self.shutdown(signal=sig))
                            )

                    self.loop.add_signal_handler(s, handle_signal)
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

        Shutdown ordering:
        1. Signal all subscriptions to stop accepting new messages
        2. Wait for in-flight tasks to complete (bounded timeout), then cancel stragglers
        3. Close domain infrastructure (event store, brokers, caches, providers)
        4. Clean up signal handlers and stop the event loop

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

            # Step 1: Signal all subscriptions to stop (sets keep_going=False
            # and runs backend-specific cleanup like persisting positions)
            subscription_shutdown_coros = [
                subscription.shutdown()
                for _, subscription in self._subscriptions.items()
            ]
            subscription_shutdown_coros.extend(
                subscription.shutdown()
                for _, subscription in self._broker_subscriptions.items()
            )
            subscription_shutdown_coros.extend(
                processor.shutdown() for _, processor in self._outbox_processors.items()
            )

            await asyncio.gather(*subscription_shutdown_coros, return_exceptions=True)
            logger.info("All subscriptions have been shut down.")

            # Step 2: Wait for in-flight tasks to finish with a bounded timeout.
            # This gives handlers processing messages a chance to complete
            # gracefully before we force-cancel them.
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if tasks:
                logger.debug(f"Waiting for {len(tasks)} in-flight tasks to complete...")
                _done, pending = await asyncio.wait(tasks, timeout=10.0)
                if pending:
                    logger.debug(
                        f"Cancelling {len(pending)} tasks that didn't finish in time"
                    )
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

            # Step 3: Close domain infrastructure connections
            try:
                self.domain.close()
            except Exception:
                logger.exception("Error during domain infrastructure cleanup")

            # Step 4: Clean up signal handlers
            self._cleanup_signal_handlers()
        finally:
            self.loop.stop()

    def run(self) -> None:
        """
        Start the Protean Engine and run all registered subscriptions.

        This method sets up the custom event loop for the engine, attaches signal and
        exception handlers, and launches all subscription coroutines for event handlers,
        command handlers, broker subscribers, and outbox processors.

        For regular operation, the engine will run indefinitely until a shutdown signal is received.
        For test mode, the engine will step through several processing cycles, ensuring propagation
        of events and messages, before performing a graceful shutdown.

        On shutdown, all running subscriptions and processors are stopped cleanly and
        the event loop is closed.

        Raises:
            Any unhandled exceptions are propagated to the custom exception handler, which will
            trigger a graceful shutdown.
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

            # Print the stack trace
            if "exception" in context and context["exception"]:
                traceback.print_exception(
                    type(context["exception"]),
                    context["exception"],
                    context["exception"].__traceback__,
                )
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

        # Create all tasks with names for better debugging
        subscription_tasks = []
        for name, subscription in self._subscriptions.items():
            task = self.loop.create_task(subscription.start())
            task.set_name(f"subscription-{name}")
            subscription_tasks.append(task)
            logger.debug(f"Started subscription: {name}")

        broker_subscription_tasks = []
        for name, subscription in self._broker_subscriptions.items():
            task = self.loop.create_task(subscription.start())
            task.set_name(f"broker-{name}")
            broker_subscription_tasks.append(task)
            logger.debug(f"Started broker subscription: {name}")

        outbox_processor_tasks = []
        for name, processor in self._outbox_processors.items():
            task = self.loop.create_task(processor.start())
            task.set_name(f"outbox-{name}")
            outbox_processor_tasks.append(task)
            logger.debug(f"Started outbox processor: {name}")

        try:
            if self.test_mode:
                # In test mode, run the loop multiple times to ensure all messages are processed
                # This is necessary for multi-step flows where handlers generate new messages
                async def run_test_cycles():
                    # Start all tasks
                    all_tasks = (
                        subscription_tasks
                        + broker_subscription_tasks
                        + outbox_processor_tasks
                    )

                    # Run enough cycles to allow message propagation across
                    # all subscription types (events, commands, broker).
                    # Each cycle yields control so poll() tasks can process
                    # their next batch.
                    #
                    # The start() tasks complete immediately (they just spawn
                    # poll loops as child tasks), so we always run at least
                    # `min_cycles` to give poll loops time to process messages
                    # before checking the early-exit condition.
                    # 50 cycles × 100ms = 5s max.
                    min_cycles = 10
                    max_cycles = 50
                    for cycle in range(max_cycles):
                        logger.debug(f"Test mode cycle {cycle + 1}/{max_cycles}")
                        # Give tasks time to process messages
                        await asyncio.sleep(0.1)

                        # Only check early exit after minimum cycles
                        if cycle >= min_cycles:
                            still_running = [t for t in all_tasks if not t.done()]
                            if not still_running:
                                logger.debug("All tasks completed")
                                break

                    # Cancel remaining tasks
                    for task in all_tasks:
                        if not task.done():
                            task.cancel()

                    # Wait for cancellation to complete
                    await asyncio.gather(*all_tasks, return_exceptions=True)

                self.loop.run_until_complete(run_test_cycles())
                # Then immediately call and await the shutdown directly
                self.loop.run_until_complete(self.shutdown())
            else:
                logger.info("Engine started successfully")
                self.loop.run_forever()
        finally:
            # Clean up signal handlers before closing the loop
            self._cleanup_signal_handlers()

            if not self.loop.is_running():
                self.loop.close()
            logger.info("Engine stopped")
