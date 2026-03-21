import functools
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Union

from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.query import BaseQuery
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.utils import DomainObjects
from protean.utils.eventing import Message

logger = logging.getLogger(__name__)


_VERSION_RETRY_DEFAULTS = {
    "enabled": True,
    "max_retries": 3,
    "base_delay_seconds": 0.05,
    "max_delay_seconds": 1.0,
}


def _get_version_retry_config() -> dict:
    """Read version retry configuration from the active domain.

    Falls back to defaults if no domain is active (e.g. during tests
    that call handlers directly without a domain context).
    """
    try:
        from protean.utils.globals import current_domain

        if current_domain:
            server_config = current_domain.config.get("server", {})
            cfg = server_config.get("version_retry", {})
            return {
                "enabled": cfg.get("enabled", _VERSION_RETRY_DEFAULTS["enabled"]),
                "max_retries": int(
                    cfg.get("max_retries", _VERSION_RETRY_DEFAULTS["max_retries"])
                ),
                "base_delay_seconds": float(
                    cfg.get(
                        "base_delay_seconds",
                        _VERSION_RETRY_DEFAULTS["base_delay_seconds"],
                    )
                ),
                "max_delay_seconds": float(
                    cfg.get(
                        "max_delay_seconds",
                        _VERSION_RETRY_DEFAULTS["max_delay_seconds"],
                    )
                ),
            }
    except Exception:
        pass
    return dict(_VERSION_RETRY_DEFAULTS)


class handle:
    """Class decorator to mark handler methods in EventHandler, CommandHandler,
    and ProcessManager classes.

    For EventHandler and CommandHandler, only ``target_cls`` is needed::

        @handle(OrderPlaced)
        def on_order_placed(self, event): ...

    For ProcessManager handlers, ``correlate`` is required and ``start`` / ``end``
    control the process manager lifecycle::

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_order_placed(self, event): ...
    """

    def __init__(
        self,
        target_cls: type,
        start: bool = False,
        correlate: Union[str, dict[str, str], None] = None,
        end: bool = False,
    ) -> None:
        self._target_cls = target_cls
        self._start = start
        self._correlate = correlate
        self._end = end

    def __call__(self, fn: Callable) -> Callable:
        """Marks the method with special attributes to construct a handler map later.

        Args:
            fn (Callable): Handler method

        Returns:
            Callable: Handler method with handler metadata attributes
        """

        @functools.wraps(fn)
        def wrapper(instance, target_obj):
            config = _get_version_retry_config()

            if not config["enabled"] or config["max_retries"] <= 0:
                with UnitOfWork():
                    return fn(instance, target_obj)

            max_retries = config["max_retries"]
            base_delay = config["base_delay_seconds"]
            max_delay = config["max_delay_seconds"]

            for attempt in range(max_retries + 1):
                try:
                    with UnitOfWork():
                        return fn(instance, target_obj)
                except ExpectedVersionError:
                    if attempt >= max_retries:
                        raise
                    delay = min(base_delay * (2**attempt), max_delay)
                    logger.debug(
                        "Version conflict in %s, retrying (%d/%d) after %.3fs",
                        fn.__qualname__,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)

        setattr(wrapper, "_target_cls", self._target_cls)
        setattr(wrapper, "_start", self._start)
        setattr(wrapper, "_correlate", self._correlate)
        setattr(wrapper, "_end", self._end)
        return wrapper


class read:
    """Decorator to mark handler methods in QueryHandler classes.

    Like ``@handle`` but does **not** wrap in ``UnitOfWork`` — reads are
    stateless and must not trigger side-effects.

    Only ``target_cls`` is accepted (no ``start``, ``correlate``, or
    ``end`` — those are ProcessManager-specific)::

        @read(GetOrdersByCustomer)
        def get_by_customer(self, query): ...
    """

    def __init__(self, target_cls: type) -> None:
        self._target_cls = target_cls

    def __call__(self, fn: Callable) -> Callable:
        """Marks the method with ``_target_cls`` metadata for handler map construction.

        Args:
            fn (Callable): Handler method

        Returns:
            Callable: Handler method with handler metadata attributes
        """

        @functools.wraps(fn)
        def wrapper(instance: Any, target_obj: Any) -> Any:
            # No UoW wrapping — reads are stateless
            return fn(instance, target_obj)

        setattr(wrapper, "_target_cls", self._target_cls)
        return wrapper


class HandlerMixin:
    """Mixin to add common handler behavior to Event Handlers and Command Handlers"""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Associate a `_handlers` map with subclasses.
        # `_handlers` is a dictionary mapping the event/command to handler methods.
        #
        #   It needs to be initialized here because if it
        #   were initialized in __init__, the same collection object
        #   would be made available across all subclasses,
        #   defeating its purpose.
        setattr(cls, "_handlers", defaultdict(set))

    @classmethod
    def _handle(cls, item: Union[Message, BaseCommand, BaseEvent, BaseQuery]) -> Any:
        """Handle a message, command, event, or query.

        Returns:
            Any: Return value from the handler method (for command and query handlers)
        """
        from protean.utils.globals import current_domain

        # Convert Message to object if necessary
        item = item.to_domain_object() if isinstance(item, Message) else item

        # Use specific handlers if available, or fallback on `$any` if defined
        handlers = cls._handlers[item.__class__.__type__] or cls._handlers["$any"]

        # Resolve handler type label for the span
        handler_type = cls.element_type.value if cls.element_type else "unknown"

        tracer = current_domain.tracer if current_domain else None

        if tracer is None:
            # No domain context — execute without tracing
            return cls._dispatch_handlers(handlers, item)

        from protean.utils.telemetry import get_domain_metrics

        metrics = get_domain_metrics(current_domain)
        handler_start = time.monotonic()

        with tracer.start_as_current_span(
            "protean.handler.execute", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("protean.handler.name", cls.__name__)
            span.set_attribute("protean.handler.type", handler_type)

            # Propagate correlation/causation IDs from the message being handled
            from protean.utils.globals import g

            msg = g.get("message_in_context")
            if msg is not None and hasattr(msg, "metadata") and msg.metadata:
                domain_meta = getattr(msg.metadata, "domain", None)
                if domain_meta is not None:
                    if domain_meta.correlation_id:
                        span.set_attribute(
                            "protean.correlation_id", domain_meta.correlation_id
                        )
                    if domain_meta.causation_id:
                        span.set_attribute(
                            "protean.causation_id", domain_meta.causation_id
                        )

            try:
                result = cls._dispatch_handlers(handlers, item)
            except Exception as exc:
                from protean.utils.telemetry import set_span_error

                set_span_error(span, exc)

                # Record handler metrics on error
                duration_s = time.monotonic() - handler_start
                handler_attrs = {
                    "handler_name": cls.__name__,
                    "handler_type": handler_type,
                    "status": "error",
                }
                metrics.handler_invocations.add(1, handler_attrs)
                metrics.handler_duration.record(duration_s, handler_attrs)
                raise

            # Record handler metrics on success
            duration_s = time.monotonic() - handler_start
            handler_attrs = {
                "handler_name": cls.__name__,
                "handler_type": handler_type,
                "status": "ok",
            }
            metrics.handler_invocations.add(1, handler_attrs)
            metrics.handler_duration.record(duration_s, handler_attrs)
            return result

    @classmethod
    def _dispatch_handlers(
        cls, handlers: set, item: Union[BaseCommand, BaseEvent, BaseQuery]
    ) -> Any:
        """Dispatch item to registered handler methods."""
        if cls.element_type in (
            DomainObjects.COMMAND_HANDLER,
            DomainObjects.QUERY_HANDLER,
        ):
            handler_method = next(iter(handlers))
            return handler_method(cls(), item)
        else:
            for handler_method in handlers:
                handler_method(cls(), item)

        return None

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        """Error handler method called when exceptions occur during message handling.

        This method can be overridden in subclasses to provide custom error handling
        for exceptions that occur during message processing. It allows handlers to
        recover from errors, log additional information, or perform cleanup operations.

        When an exception occurs in a handler method:
        1. The exception is caught in Engine.handle_message or Engine.handle_broker_message
        2. Details are logged with traceback information
        3. This handle_error method is called with the exception and original message
        4. Processing continues with the next message (the engine does not shut down)

        If this method raises an exception itself, that exception is also caught and logged,
        but not propagated further.

        Args:
            exc (Exception): The exception that was raised during message handling
            message (Message): The original message being processed when the exception occurred

        Returns:
            None

        Note:
            - The default implementation does nothing, allowing processing to continue
            - Subclasses can override this method to implement custom error handling strategies
            - This method is called from a try/except block, so exceptions raised here won't crash the engine
        """
