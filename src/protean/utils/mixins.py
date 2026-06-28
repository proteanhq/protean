import functools
import importlib
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Union

from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.query import BaseQuery
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import (
    ConfigurationError,
    ExpectedVersionError,
    SendError,
)
from protean.utils import DomainObjects
from protean.utils.eventing import Message

logger = logging.getLogger(__name__)


_VERSION_RETRY_DEFAULTS = {
    "enabled": True,
    "max_retries": 3,
    "base_delay_seconds": 0.05,
    "max_delay_seconds": 1.0,
}

# Transient-failure retry is distinct from version (OCC) retry above: it retries
# handlers that fail with *transient* infrastructure exceptions (a dropped
# connection, a timeout, an email-dispatch blip) rather than version conflicts.
# It is **opt-in** (``enabled=False``) so existing behavior is unchanged until an
# operator turns it on, either domain-wide via ``server.transient_retry`` or
# per-handler via ``@domain.command_handler(retries=...)``.
#
# The default exception set is deliberately narrow — every entry must be
# genuinely transient so a retry has a chance of succeeding. ``ConnectionError``
# and ``TimeoutError`` are builtin I/O failures; ``SendError`` wraps transient
# email-gateway failures. Non-transient errors (validation, business-rule, or
# database constraint violations) must never be retried by default.
_TRANSIENT_RETRY_DEFAULTS = {
    "enabled": False,
    "max_retries": 3,
    "backoff": "exponential",
    "base_delay_seconds": 0.1,
    "max_delay_seconds": 5.0,
    "exceptions": (ConnectionError, TimeoutError, SendError),
}

_VALID_BACKOFF_STRATEGIES = ("exponential", "linear", "fixed")


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


@functools.lru_cache(maxsize=None)
def _import_exception_type(path: str) -> type[BaseException]:
    """Resolve a dotted path (or bare builtin name) to an exception class.

    Cached: a dotted path always resolves to the same class, so the import is
    paid once rather than on every handler invocation that resolves config.

    ``"builtins.ConnectionError"`` and ``"ConnectionError"`` both resolve to
    :class:`ConnectionError`; ``"protean.exceptions.SendError"`` resolves to
    :class:`~protean.exceptions.SendError`.
    """
    module_name, _, attr = path.rpartition(".")
    if not module_name:
        module_name, attr = "builtins", path
    try:
        obj = getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        raise ConfigurationError(
            f"Cannot resolve transient retry exception `{path}`"
        ) from exc
    if not (isinstance(obj, type) and issubclass(obj, BaseException)):
        raise ConfigurationError(
            f"Transient retry entry `{path}` is not an exception type"
        )
    return obj


def _coerce_bool(value: Any) -> bool:
    """Coerce a config flag to a bool, honoring string forms.

    ``bool("false")`` is ``True``, which would silently enable a feature when
    config arrives as a string (e.g. via ``${VAR}`` env substitution). Treat the
    usual falsy strings as ``False`` instead.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _resolve_exception_types(specs: Any) -> tuple[type[BaseException], ...]:
    """Normalize an exception spec into a tuple of exception classes.

    Accepts a single exception class, a single dotted-path string, or an
    iterable mixing exception classes and dotted-path strings (the form used in
    ``domain.toml``).
    """
    if isinstance(specs, type) and issubclass(specs, BaseException):
        return (specs,)

    # A lone dotted-path string is a common config shorthand; wrap it so we
    # don't iterate over its characters.
    if isinstance(specs, str):
        specs = [specs]

    try:
        iterator = iter(specs)
    except TypeError:
        raise ConfigurationError(
            f"Invalid transient retry exceptions `{specs!r}`; expected an "
            f"exception type, a dotted-path string, or a list of them"
        )

    resolved: list[type[BaseException]] = []
    for spec in iterator:
        if isinstance(spec, str):
            resolved.append(_import_exception_type(spec))
        elif isinstance(spec, type) and issubclass(spec, BaseException):
            resolved.append(spec)
        else:
            raise ConfigurationError(
                f"Invalid transient retry exception `{spec!r}`; expected an "
                f"exception type or dotted-path string"
            )
    return tuple(resolved)


def _get_transient_retry_config(instance: Any = None) -> dict:
    """Resolve the effective transient-retry policy for a handler.

    Precedence (highest first): per-handler ``retries`` / ``backoff`` /
    ``retry_exceptions`` options, then the domain-level
    ``server.transient_retry`` config, then :data:`_TRANSIENT_RETRY_DEFAULTS`.
    The returned ``max_retries`` is ``0`` whenever the policy is inactive, so
    callers can gate purely on that value.
    """
    cfg: dict[str, Any] = dict(_TRANSIENT_RETRY_DEFAULTS)
    # Exception specs are kept unresolved (dotted-path strings or classes) and
    # only imported below when the policy is actually active, so the common
    # disabled path never pays the import cost.
    exception_spec: Any = None

    # --- Domain-level configuration ---
    try:
        from protean.utils.globals import current_domain

        if current_domain:
            raw = current_domain.config.get("server", {}).get("transient_retry", {})
            if raw:
                cfg["enabled"] = _coerce_bool(raw.get("enabled", cfg["enabled"]))
                cfg["max_retries"] = int(raw.get("max_retries", cfg["max_retries"]))
                cfg["backoff"] = raw.get("backoff", cfg["backoff"])
                cfg["base_delay_seconds"] = float(
                    raw.get("base_delay_seconds", cfg["base_delay_seconds"])
                )
                cfg["max_delay_seconds"] = float(
                    raw.get("max_delay_seconds", cfg["max_delay_seconds"])
                )
                exception_spec = raw.get("exceptions")
    except Exception:
        cfg = dict(_TRANSIENT_RETRY_DEFAULTS)
        exception_spec = None

    # The domain-level toggle only gates the default; a per-handler `retries`
    # value overrides it either way.
    if not cfg["enabled"]:
        cfg["max_retries"] = 0

    # --- Per-handler overrides ---
    meta = getattr(instance, "meta_", None)
    if meta is not None:
        retries = getattr(meta, "retries", None)
        if retries is not None:
            cfg["max_retries"] = int(retries)
        backoff = getattr(meta, "backoff", None)
        if backoff is not None:
            cfg["backoff"] = backoff
        retry_exceptions = getattr(meta, "retry_exceptions", None)
        if retry_exceptions is not None:
            exception_spec = retry_exceptions

    max_retries = max(0, cfg["max_retries"])
    cfg["max_retries"] = max_retries

    if cfg["backoff"] not in _VALID_BACKOFF_STRATEGIES:
        raise ConfigurationError(
            f"Invalid transient retry backoff `{cfg['backoff']}`; "
            f"choose from {_VALID_BACKOFF_STRATEGIES}"
        )

    # Resolve exceptions only when retries are active — the wrapper ignores the
    # exception set otherwise.
    if max_retries > 0 and exception_spec is not None:
        cfg["exceptions"] = _resolve_exception_types(exception_spec)

    return cfg


def _transient_backoff_delay(
    strategy: str, attempt: int, base_delay: float, max_delay: float
) -> float:
    """Compute the (capped) backoff delay for the ``attempt``-th transient retry."""
    if strategy == "fixed":
        delay = base_delay
    elif strategy == "linear":
        delay = base_delay * (attempt + 1)
    else:  # exponential
        delay = base_delay * (2**attempt)
    return min(delay, max_delay)


def _record_handler_retry(instance: Any, exc: BaseException) -> None:
    """Increment the ``protean.handler.retried`` counter for a transient retry."""
    try:
        from protean.utils.globals import current_domain

        if not current_domain:
            return
        from protean.utils.telemetry import get_domain_metrics

        element_type = getattr(instance, "element_type", None)
        get_domain_metrics(current_domain).handler_retried.add(
            1,
            {
                "handler_name": type(instance).__name__,
                "handler_type": element_type.value if element_type else "unknown",
                "exception": type(exc).__name__,
            },
        )
    except Exception:  # metrics must never break the retry path
        pass


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
            # Two independent, composable auto-retry policies wrap every handler
            # invocation. Version (OCC) retry resolves `ExpectedVersionError`
            # from concurrent writes; transient retry (opt-in) re-runs handlers
            # that fail with transient infrastructure exceptions. Each keeps its
            # own attempt counter and backoff, and each attempt runs in a fresh
            # UnitOfWork so a failed attempt rolls back cleanly before the retry.
            version_cfg = _get_version_retry_config()
            transient_cfg = _get_transient_retry_config(instance)

            version_max = (
                version_cfg["max_retries"]
                if version_cfg["enabled"] and version_cfg["max_retries"] > 0
                else 0
            )
            transient_max = transient_cfg["max_retries"]
            # `except ()` matches nothing, so an empty tuple cleanly disables the
            # transient branch when no policy is active.
            transient_excs: tuple[type[BaseException], ...] = (
                transient_cfg["exceptions"] if transient_max > 0 else ()
            )

            # Fast path: neither policy active — run once without a retry loop.
            if version_max == 0 and transient_max == 0:
                with UnitOfWork():
                    return fn(instance, target_obj)

            version_attempt = 0
            transient_attempt = 0
            while True:
                try:
                    with UnitOfWork():
                        return fn(instance, target_obj)
                except ExpectedVersionError:
                    if version_attempt >= version_max:
                        raise
                    # Version (OCC) retry is always exponential.
                    delay = _transient_backoff_delay(
                        "exponential",
                        version_attempt,
                        version_cfg["base_delay_seconds"],
                        version_cfg["max_delay_seconds"],
                    )
                    logger.debug(
                        "Version conflict in %s, retrying (%d/%d) after %.3fs",
                        fn.__qualname__,
                        version_attempt + 1,
                        version_max,
                        delay,
                    )
                    version_attempt += 1
                    time.sleep(delay)
                except transient_excs as exc:
                    if transient_attempt >= transient_max:
                        raise
                    delay = _transient_backoff_delay(
                        transient_cfg["backoff"],
                        transient_attempt,
                        transient_cfg["base_delay_seconds"],
                        transient_cfg["max_delay_seconds"],
                    )
                    logger.debug(
                        "Transient error %s in %s, retrying (%d/%d) after %.3fs",
                        type(exc).__name__,
                        fn.__qualname__,
                        transient_attempt + 1,
                        transient_max,
                        delay,
                    )
                    _record_handler_retry(instance, exc)
                    transient_attempt += 1
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
            "protean.handler.execute",
            record_exception=False,
            set_status_on_exception=False,
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
        from protean.utils.logging import access_log_handler

        # Map element_type to access log kind
        _KIND_MAP = {
            DomainObjects.COMMAND_HANDLER: "command",
            DomainObjects.EVENT_HANDLER: "event",
            DomainObjects.QUERY_HANDLER: "query",
            DomainObjects.PROJECTOR: "projector",
        }
        kind = _KIND_MAP.get(cls.element_type, "unknown")

        if cls.element_type in (
            DomainObjects.COMMAND_HANDLER,
            DomainObjects.QUERY_HANDLER,
        ):
            handler_method = next(iter(handlers))
            with access_log_handler(kind, item, cls, handler_method.__name__):
                return handler_method(cls(), item)
        else:
            for handler_method in handlers:
                with access_log_handler(kind, item, cls, handler_method.__name__):
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
