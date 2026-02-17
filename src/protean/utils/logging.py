"""Structured logging for Protean applications.

Provides environment-aware structured logging built on structlog. Out of the box:
- JSON output in production/staging, colored console in development
- Environment-based log levels (DEBUG dev, INFO production, WARNING test)
- Context variable support for enriching logs across async boundaries
- Method call tracing decorator for debugging handlers
- Third-party and framework logger noise suppression
- Optional rotating file handlers

Typical usage in application code::

    from protean.utils.logging import configure_logging, get_logger

    configure_logging()                          # Console only, auto-detect env
    configure_logging(log_dir="logs")            # + rotating file handlers

    logger = get_logger(__name__)
    logger.info("customer_registered", customer_id="abc-123")
"""

import functools
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Union

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
    "protean.core": logging.WARNING,
    "protean.adapters": logging.WARNING,
}


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
    """
    env = _detect_env()

    # Resolve log level: explicit arg > env var > environment default
    if level is None:
        level = os.getenv("PROTEAN_LOG_LEVEL", _ENV_LEVEL_MAP.get(env, "INFO")).upper()
    else:
        level = level.upper()

    numeric_level = getattr(logging, level, logging.INFO)

    # --- stdlib logging setup ---
    _setup_stdlib_logging(
        numeric_level=numeric_level,
        log_dir=Path(log_dir) if log_dir else None,
        log_file_prefix=log_file_prefix or "protean",
        max_bytes=max_bytes,
        backup_count=backup_count,
    )

    # --- structlog setup ---
    _setup_structlog(env=env, format=format)


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


def _setup_stdlib_logging(
    numeric_level: int,
    log_dir: Optional[Path],
    log_file_prefix: str,
    max_bytes: int,
    backup_count: int,
) -> None:
    """Configure stdlib logging: console handler + optional rotating file handlers."""
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates on re-configuration
    root.handlers = []

    # Console handler (always present)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(numeric_level)
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
        root.addHandler(main_file)

        error_file = logging.handlers.RotatingFileHandler(
            filename=log_dir / f"{log_file_prefix}_error.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_file.setLevel(logging.ERROR)
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


def _setup_structlog(env: str, format: str) -> None:
    """Configure structlog processors and renderer."""
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
