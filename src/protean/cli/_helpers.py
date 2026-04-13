"""Shared CLI helpers.

This module exists separately to avoid circular imports — ``cli/__init__.py``
imports every subcommand module, so subcommand modules cannot import from
``cli/__init__.py`` directly.
"""

import functools
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import typer

from protean.utils.logging import get_logger

logger = get_logger(__name__)

# Key used to store CLI logging state in the Typer context.
# Shared between cli/__init__.py (callback) and subcommands that have their
# own logging setup (server, observatory) to avoid double-configuration.
CTX_LOG_CONFIGURED = "_protean_log_configured"


@contextmanager
def cli_exception_handler(command: str) -> Iterator[None]:
    """Context manager that logs unhandled exceptions from CLI commands.

    Wraps the command body in ``try/except Exception``, logs the failure
    with ``logger.exception`` for structured output, and re-raises so
    Typer produces a non-zero exit code.
    """
    try:
        yield
    except (typer.Exit, typer.Abort, SystemExit, KeyboardInterrupt):
        raise
    except Exception:
        logger.exception("cli.command_failed", command=command, argv=sys.argv)
        raise


def handle_cli_exceptions(command_name: str) -> Callable:
    """Decorator that wraps a CLI command with structured exception logging.

    Usage::

        @app.command()
        @handle_cli_exceptions("db setup")
        def setup(...):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with cli_exception_handler(command_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
