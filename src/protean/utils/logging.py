"""Structured logging for Protean applications.

Provides environment-aware structured logging built on structlog. Out of the box:
- JSON output in production/staging, colored console in development
- Environment-based log levels (DEBUG dev, INFO production, WARNING test)
- Context variable support for enriching logs across async boundaries
- Method call tracing decorator for debugging handlers
- Third-party and framework logger noise suppression
- Optional rotating file handlers
- Wide event access log for handler observability

Typical usage in application code::

    from protean.utils.logging import configure_logging, get_logger

    configure_logging()                          # Console only, auto-detect env
    configure_logging(log_dir="logs")            # + rotating file handlers

    logger = get_logger(__name__)
    logger.info("customer_registered", customer_id="abc-123")

Wide event access log usage::

    from protean.utils.logging import bind_event_context

    class PlaceOrderHandler:
        @handle(PlaceOrder)
        def handle(self, command):
            bind_event_context(user_id=command.user_id, order_total=command.total)
            # ... handler logic ...
"""

import functools
import logging
import logging.config
import logging.handlers
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Union

import structlog


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def _detect_env() -> str:
    """Detect the runtime environment from standard env vars."""
    return (
        os.getenv("PROTEAN_ENV")
        or os.getenv("ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).lower()


_ENV_LEVEL_MAP = {
    "production": "INFO",
    "staging": "INFO",
    "development": "DEBUG",
    "test": "WARNING",
}

# Third-party loggers that are noisy at DEBUG/INFO
_NOISY_LOGGERS = {
    "urllib3": logging.WARNING,
    "asyncio": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "sqlalchemy.pool": logging.WARNING,
    "elasticsearch": logging.WARNING,
    "redis": logging.WARNING,
}

# Protean framework loggers — reasonable defaults so apps don't have to
# manually suppress framework noise
_FRAMEWORK_LOGGERS_NORMAL = {
    "protean.server.engine": logging.INFO,
    "protean.server.subscription": logging.INFO,
    "protean.server.outbox_processor": logging.INFO,
    "protean.access": logging.INFO,
    "protean.perf": logging.WARNING,
    "protean.core": logging.WARNING,
    "protean.adapters": logging.WARNING,
}

# Dedicated loggers for the wide event access log and slow-handler detection
access_logger = logging.getLogger("protean.access")
perf_logger = logging.getLogger("protean.perf")

# Framework-reserved field names that application context cannot overwrite
_FRAMEWORK_FIELDS = frozenset(
    {
        "kind",
        "message_type",
        "message_id",
        "aggregate",
        "aggregate_id",
        "events_raised",
        "events_raised_count",
        "repo_operations",
        "uow_outcome",
        "handler",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "correlation_id",
        "causation_id",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    level: Optional[str] = None,
    format: str = "auto",
    log_dir: Optional[Union[str, Path]] = None,
    log_file_prefix: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    extra_processors: Optional[list] = None,
    per_logger: Optional[dict[str, str]] = None,
    dict_config: Optional[dict[str, Any]] = None,
) -> None:
    """Configure structured logging for a Protean application.

    When called with no arguments, auto-detects ``PROTEAN_ENV`` and sets up
    environment-appropriate structured logging:

    - **production / staging** — JSON output, INFO level
    - **development** — colored console output with rich tracebacks, DEBUG level
    - **test** — WARNING level, minimal output

    Args:
        level: Logging level override (``DEBUG``, ``INFO``, ``WARNING``,
            ``ERROR``, ``CRITICAL``). When *None*, determined by environment.
            Can also be overridden via the ``PROTEAN_LOG_LEVEL`` env var.
        format: Output format. ``"json"`` forces JSON, ``"console"`` forces
            colored console, ``"auto"`` (default) picks based on environment.
        log_dir: Directory for rotating log files. *None* disables file
            logging (suitable for containerized deployments using stdout).
        log_file_prefix: Filename prefix for log files (e.g. ``"myapp"``
            produces ``myapp.log`` and ``myapp_error.log``). Defaults to
            ``"protean"`` if not specified.
        max_bytes: Maximum size in bytes before log file rotation. Default 10 MB.
        backup_count: Number of rotated log files to keep. Default 5.
        extra_processors: Optional list of additional structlog processors to
            insert before the renderer (e.g. correlation-context injection).
        per_logger: Optional mapping of logger names to level strings. Applied
            after global setup so individual loggers can be tuned independently.
            Example: ``{"protean.server.engine": "WARNING", "myapp.orders": "DEBUG"}``.
        dict_config: Optional ``logging.config.dictConfig``-compatible dict.
            When provided, bypasses the environment-aware setup and applies the
            dict directly via ``logging.config.dictConfig()``. The user-supplied
            dict is expected to include any handlers/formatters desired. After
            applying, ``ProteanCorrelationFilter`` is still installed on the
            root logger for consistency with ``Domain.configure_logging()``.
    """
    if dict_config is not None:
        logging.config.dictConfig(dict_config)
        # Set up structlog so that get_logger() calls produce well-formed
        # output even when the user supplies their own stdlib dictConfig.
        env = _detect_env()
        _setup_structlog(env=env, format="auto", extra_processors=extra_processors)
        # Install ProteanCorrelationFilter on the root logger so correlation_id
        # and causation_id are available in every log record, matching the
        # behavior of Domain.configure_logging().
        try:
            from protean.integrations.logging import ProteanCorrelationFilter

            root = logging.getLogger()
            if not any(isinstance(f, ProteanCorrelationFilter) for f in root.filters):
                root.addFilter(ProteanCorrelationFilter())
        except ImportError:
            pass
        return

    env = _detect_env()

    # Resolve log level: explicit arg > env var > environment default
    if level is None:
        level = os.getenv("PROTEAN_LOG_LEVEL", _ENV_LEVEL_MAP.get(env, "INFO")).upper()
    else:
        level = level.upper()

    numeric_level = getattr(logging, level, logging.INFO)

    # --- stdlib logging setup (with ProcessorFormatter bridge) ---
    _setup_stdlib_logging(
        numeric_level=numeric_level,
        log_dir=Path(log_dir) if log_dir else None,
        log_file_prefix=log_file_prefix or "protean",
        max_bytes=max_bytes,
        backup_count=backup_count,
        env=env,
        format=format,
        extra_processors=extra_processors,
    )

    # --- structlog setup ---
    _setup_structlog(env=env, format=format, extra_processors=extra_processors)

    # --- per-logger overrides ---
    if per_logger:
        for logger_name, logger_level in per_logger.items():
            logging.getLogger(logger_name).setLevel(
                getattr(logging, logger_level.upper(), logging.INFO)
            )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a configured structlog logger instance.

    Args:
        name: Logger name (typically ``__name__``).

    Returns:
        A structlog ``BoundLogger`` wrapping the stdlib logger.
    """
    return structlog.get_logger(name)


def add_context(**kwargs: Any) -> None:
    """Bind context variables that will appear in all subsequent log messages.

    Uses ``contextvars`` so context propagates correctly across ``await``
    boundaries and thread-local storage.

    Example::

        add_context(request_id="abc-123", customer_id="cust-001")
        logger.info("processing")  # includes request_id and customer_id
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context variables."""
    structlog.contextvars.clear_contextvars()


def bind_event_context(**kwargs: Any) -> None:
    """Add business-specific fields to the current wide event.

    Called from handler code to enrich the access log with domain context
    that only the application knows (user tier, order total, feature flags, etc.).
    Fields are merged — multiple calls accumulate, later calls overwrite
    conflicting keys. Safe to call outside handler context (no-op).
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_event_context(*keys: str) -> None:
    """Remove specific fields from the current wide event context."""
    structlog.contextvars.unbind_contextvars(*keys)


def _reset_access_log_counters() -> None:
    """Reset per-handler access log counters on g."""
    try:
        from protean.utils.globals import g

        g._access_log_repo_loads = 0
        g._access_log_repo_saves = 0
        g._access_log_events_raised = []
        g._access_log_uow_outcome = "no_uow"
    except Exception:
        pass


def _get_correlation_context() -> tuple[str, str]:
    """Extract correlation_id and causation_id from the current message context."""
    try:
        from protean.utils.globals import g

        msg = g.get("message_in_context")
        if msg is None:
            return ("", "")
        metadata = getattr(msg, "metadata", None)
        domain_meta = getattr(metadata, "domain", None) if metadata else None
        if domain_meta is None:
            return ("", "")
        return (
            domain_meta.correlation_id or "",
            domain_meta.causation_id or "",
        )
    except Exception:
        return ("", "")


def _extract_aggregate_info(item: Any, handler_cls: type) -> tuple[str, str]:
    """Extract aggregate type name and aggregate ID from item or handler class."""
    aggregate = ""
    aggregate_id = ""

    # Get aggregate type from item's meta or handler's meta
    part_of = getattr(getattr(item, "meta_", None), "part_of", None)
    if part_of is None:
        part_of = getattr(getattr(handler_cls, "meta_", None), "part_of", None)

    if part_of is not None:
        aggregate = part_of.__name__

        # Try to extract aggregate_id from the message stream
        metadata = getattr(item, "_metadata", None)
        if metadata is not None:
            headers = getattr(metadata, "headers", None)
            if headers is not None:
                stream = getattr(headers, "stream", None) or ""
                stream_category = getattr(
                    getattr(part_of, "meta_", None), "stream_category", ""
                )
                if stream and stream_category:
                    cmd_prefix = f"{stream_category}:command-"
                    evt_prefix = f"{stream_category}-"
                    if cmd_prefix in stream:
                        aggregate_id = stream.split(cmd_prefix, 1)[1]
                    elif stream.startswith(evt_prefix):
                        aggregate_id = stream[len(evt_prefix) :]

    return aggregate, aggregate_id


def _read_access_log_counters() -> tuple[list[str], dict[str, int], str]:
    """Read per-handler access log counters from g.

    Returns:
        Tuple of (events_raised, repo_operations, uow_outcome)
    """
    try:
        from protean.utils.globals import g

        events_raised = getattr(g, "_access_log_events_raised", []) or []
        repo_loads = getattr(g, "_access_log_repo_loads", 0) or 0
        repo_saves = getattr(g, "_access_log_repo_saves", 0) or 0
        uow_outcome = getattr(g, "_access_log_uow_outcome", "no_uow") or "no_uow"
        return (
            list(events_raised),
            {"loads": repo_loads, "saves": repo_saves},
            uow_outcome,
        )
    except Exception:
        return ([], {"loads": 0, "saves": 0}, "no_uow")


def _get_slow_handler_threshold() -> float:
    """Read slow_handler_threshold_ms from domain config. Returns 0 to disable."""
    try:
        from protean.utils.globals import current_domain

        if current_domain:
            logging_config = current_domain.config.get("logging", {})
            return float(logging_config.get("slow_handler_threshold_ms", 500))
    except Exception:
        pass
    return 500.0


@contextmanager
def access_log_handler(
    kind: str, item: Any, handler_cls: type, handler_method_name: str
) -> Iterator[None]:
    """Context manager that measures handler duration and emits a wide event.

    Clears structlog contextvars at entry, collects framework + app context,
    emits a single wide event on exit.

    Args:
        kind: Handler kind — "command", "event", "query", or "projector".
        item: The domain object being handled (command, event, or query).
        handler_cls: The handler class dispatching the item.
        handler_method_name: The name of the specific handler method.
    """
    structlog.contextvars.clear_contextvars()
    _reset_access_log_counters()

    started_at = time.perf_counter()
    error_info: Optional[Exception] = None
    try:
        yield
    except Exception as exc:
        error_info = exc
        raise
    finally:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)

        # Collect application-provided context (via bind_event_context)
        app_context = structlog.contextvars.get_contextvars()

        # Clear context vars before emitting to avoid double-merge
        structlog.contextvars.clear_contextvars()

        # Extract framework fields
        message_type = getattr(item, "__class__", None)
        message_type_name = (
            getattr(message_type, "__type__", None)
            or getattr(message_type, "__name__", "unknown")
            if message_type
            else "unknown"
        )
        message_id = ""
        metadata = getattr(item, "_metadata", None)
        if metadata is not None:
            headers = getattr(metadata, "headers", None)
            if headers is not None:
                message_id = getattr(headers, "id", "") or ""

        aggregate, aggregate_id = _extract_aggregate_info(item, handler_cls)
        correlation_id, causation_id = _get_correlation_context()
        events_raised, repo_operations, uow_outcome = _read_access_log_counters()

        handler_name = f"{handler_cls.__name__}.{handler_method_name}"

        # Determine status
        if error_info is not None:
            status = "failed"
        else:
            threshold = _get_slow_handler_threshold()
            status = "slow" if (threshold > 0 and duration_ms > threshold) else "ok"

        # Build the wide event — framework fields take precedence over app context
        wide_event = {
            k: v for k, v in app_context.items() if k not in _FRAMEWORK_FIELDS
        }
        wide_event.update(
            {
                "kind": kind,
                "message_type": message_type_name,
                "message_id": str(message_id),
                "aggregate": aggregate,
                "aggregate_id": str(aggregate_id),
                "events_raised": events_raised,
                "events_raised_count": len(events_raised),
                "repo_operations": repo_operations,
                "uow_outcome": uow_outcome,
                "handler": handler_name,
                "duration_ms": duration_ms,
                "status": status,
                "error_type": type(error_info).__name__ if error_info else None,
                "error_message": (str(error_info)[:256] if error_info else None),
                "correlation_id": correlation_id,
                "causation_id": causation_id,
            }
        )

        # Emit the wide event
        if error_info is not None:
            access_logger.error(
                "access.handler_failed",
                extra=wide_event,
                exc_info=(
                    type(error_info),
                    error_info,
                    error_info.__traceback__,
                ),
            )
        elif status == "slow":
            access_logger.warning("access.handler_completed", extra=wide_event)
            # Separate perf logger for routing slow-handler alerts independently
            perf_logger.warning("slow_handler", extra=wide_event)
        else:
            access_logger.info("access.handler_completed", extra=wide_event)


def log_method_call(func: Callable) -> Callable:
    """Decorator that logs method entry, exit, and exceptions.

    Useful for tracing command and event handler execution::

        @log_method_call
        def handle(self, command):
            ...

    Logs at DEBUG level, so only visible when ``level="DEBUG"``.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)

        logger.debug(
            "method_call_start",
            method=func.__name__,
            args=args[1:] if args else [],  # Skip self
            kwargs=kwargs,
        )

        try:
            result = func(*args, **kwargs)
            logger.debug(
                "method_call_end",
                method=func.__name__,
                result=result,
            )
            return result
        except Exception as e:
            logger.exception(
                "method_call_error",
                method=func.__name__,
                error=str(e),
            )
            raise

    return wrapper


def configure_for_testing() -> None:
    """Minimize logging noise in test runs.

    Sets root logger to WARNING and removes any file handlers. Call this
    from a test fixture (e.g. ``conftest.py``)::

        from protean.utils.logging import configure_for_testing
        configure_for_testing()
    """
    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    for handler in root.handlers[:]:
        if isinstance(handler, logging.FileHandler):
            root.removeHandler(handler)


# ---------------------------------------------------------------------------
# Internal setup
# ---------------------------------------------------------------------------


def _build_shared_processors(extra_processors: Optional[list] = None) -> list:
    """Build the shared processor chain used by both stdlib and structlog paths.

    This chain runs on every log event — whether it originated from a stdlib
    ``logging.getLogger()`` call or a structlog ``get_logger()`` call — before
    the final renderer produces output.
    """
    processors: list = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.contextvars.merge_contextvars,
    ]
    if extra_processors:
        processors.extend(extra_processors)
    return processors


def _build_renderer(env: str, format: str):
    """Build the final renderer (JSON or console) based on environment."""
    use_json = format == "json" or (
        format == "auto" and env in ("production", "staging")
    )
    if use_json:
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer(
        colors=True,
        exception_formatter=structlog.dev.RichTracebackFormatter(
            show_locals=True,
            max_frames=2,
        ),
    )


def _build_processor_formatter(
    env: str,
    format: str,
    shared_processors: list,
) -> structlog.stdlib.ProcessorFormatter:
    """Build a ``ProcessorFormatter`` that handles final rendering.

    Both stdlib ``LogRecord`` objects (via ``foreign_pre_chain``) and structlog
    events (pre-processed by structlog's chain ending in ``wrap_for_formatter``)
    converge here for a single rendering pass.  This avoids double-encoding.
    """
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _build_renderer(env, format),
        ],
        foreign_pre_chain=shared_processors,
    )


def _setup_stdlib_logging(
    numeric_level: int,
    log_dir: Optional[Path],
    log_file_prefix: str,
    max_bytes: int,
    backup_count: int,
    env: str = "development",
    format: str = "auto",
    extra_processors: Optional[list] = None,
) -> None:
    """Configure stdlib logging with ``ProcessorFormatter`` bridge.

    Every stdlib handler is given a ``structlog.stdlib.ProcessorFormatter``
    so that ``logging.getLogger()`` records flow through the same processor
    chain as ``get_logger()`` events.  This guarantees uniform output shape
    (JSON in production, colored console in development) regardless of
    whether the call site uses stdlib or structlog.
    """
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates on re-configuration
    root.handlers = []

    shared_processors = _build_shared_processors(extra_processors)
    formatter = _build_processor_formatter(env, format, shared_processors)

    # Console handler (always present)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handlers (opt-in)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)

        main_file = logging.handlers.RotatingFileHandler(
            filename=log_dir / f"{log_file_prefix}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        main_file.setLevel(numeric_level)
        main_file.setFormatter(formatter)
        root.addHandler(main_file)

        error_file = logging.handlers.RotatingFileHandler(
            filename=log_dir / f"{log_file_prefix}_error.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_file.setLevel(logging.ERROR)
        error_file.setFormatter(formatter)
        root.addHandler(error_file)

    # Suppress noisy third-party loggers
    for logger_name, logger_level in _NOISY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(logger_level)

    # Set Protean framework loggers to sensible levels
    if numeric_level == logging.DEBUG:
        logging.getLogger("protean").setLevel(logging.DEBUG)
    else:
        for logger_name, logger_level in _FRAMEWORK_LOGGERS_NORMAL.items():
            logging.getLogger(logger_name).setLevel(logger_level)


def _setup_structlog(
    env: str,
    format: str,
    extra_processors: Optional[list] = None,
) -> None:
    """Configure structlog processors and renderer.

    The structlog chain retains its own renderer so that events logged via
    ``get_logger()`` produce a fully rendered string *before* hitting the
    stdlib handler.  This is compatible with pytest's ``caplog`` and any
    handler that does not use ``ProcessorFormatter``.

    Stdlib loggers (``logging.getLogger()``) take a separate path through
    the ``ProcessorFormatter`` on each handler — see ``_setup_stdlib_logging``.
    """
    processors: list = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.contextvars.merge_contextvars,
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ]
        ),
    ]

    if extra_processors:
        processors.extend(extra_processors)

    # Choose renderer
    use_json = format == "json" or (
        format == "auto" and env in ("production", "staging")
    )

    if use_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.RichTracebackFormatter(
                    show_locals=True,
                    max_frames=2,
                ),
            )
        )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
