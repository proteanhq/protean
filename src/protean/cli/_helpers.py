"""Shared CLI helpers.

This module exists separately to avoid circular imports — ``cli/__init__.py``
imports every subcommand module, so subcommand modules cannot import from
``cli/__init__.py`` directly.
"""

import functools
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib.util import find_spec
from typing import TYPE_CHECKING, Any, NoReturn

import typer
from rich import print

from protean.exceptions import NoDomainException
from protean.utils.dependencies import (
    FEATURE_EXTRA_MODULES,
    FeatureExtra,
    missing_dependency_message,
)
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

if TYPE_CHECKING:
    from protean.domain import Domain

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


def abort_for_missing_dependency(
    extra: FeatureExtra,
    feature: str,
    exc: ImportError,
) -> NoReturn:
    """Turn an absent optional dependency into a clean install hint and abort.

    Call this from a subcommand's ``except ImportError`` block after a lazy
    import of a feature's optional stack (``copier`` for ``protean new``,
    ``IPython`` for ``protean shell``, the FastAPI stack for
    ``protean observatory``). If a package the ``extra`` provides is genuinely
    not installed, it prints a one-line message naming the extra to install and
    raises ``typer.Abort`` so Typer exits non-zero, mirroring the
    ``--reload``/watchfiles handling instead of surfacing a raw traceback.

    The "is it installed?" test uses ``importlib.util.find_spec`` on the extra's
    packages, not ``exc.name``: an ``ImportError`` from a package that IS
    installed but broken (an incompatible version, a renamed symbol) names that
    same package, so keying off the name would tell the user to install a package
    they already have. When every package the extra provides is importable, the
    ``ImportError`` is a real bug inside the feature and is re-raised unchanged.
    """
    missing = [pkg for pkg in FEATURE_EXTRA_MODULES[extra] if find_spec(pkg) is None]
    if not missing:
        raise exc
    msg = f"Error: {missing_dependency_message(missing[0], extra, feature)}"
    # Use typer.echo, not rich's print: the message contains "protean[<extra>]",
    # and rich would treat "[<extra>]" as a markup tag and strip it, printing a
    # wrong (and unusable) install command.
    typer.echo(msg)
    logger.error(msg)
    raise typer.Abort() from exc


def load_domain(domain_path: str) -> "Domain":
    """Load and initialize a domain from ``domain_path``, or abort cleanly.

    Shared by the ``protean`` subcommands that operate on a domain (``outbox``
    and others). Kept here — rather than copy-pasted into each subcommand
    module — so the error handling stays identical across commands. On a
    missing/undiscoverable domain it prints a clear message and raises
    ``typer.Abort`` so Typer exits non-zero.
    """
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort() from exc

    assert derived_domain is not None
    derived_domain.init()
    return derived_domain


def handle_cli_exceptions(
    command_name: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that wraps a CLI command with structured exception logging.

    Usage::

        @app.command()
        @handle_cli_exceptions("db setup")
        def setup(...):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with cli_exception_handler(command_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator
