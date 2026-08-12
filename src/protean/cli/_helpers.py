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

from protean.cli.result import emit_usage_error
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


def load_domain(domain_path: str, *, as_json: bool = False) -> "Domain":
    """Load and initialize a domain from ``domain_path``, or abort cleanly.

    Shared by the ``protean`` subcommands that operate on a domain (``outbox``
    and others). Kept here — rather than copy-pasted into each subcommand
    module — so the error handling stays identical across commands. On a
    missing/undiscoverable domain it prints a clear message and raises
    ``typer.Abort`` so Typer exits non-zero.

    Pass ``as_json=True`` from a command emitting the result envelope: a load
    failure then becomes the shared ``status="error"`` envelope on stdout and
    exit ``2``, so machine output stays exactly one JSON object.
    """
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        logger.error(msg)
        if as_json:
            emit_usage_error(as_json=True, message=msg)
        print(msg)
        raise typer.Abort() from exc

    assert derived_domain is not None

    try:
        derived_domain.init()
    except Exception as exc:
        # Under ``--json`` an init failure (bad config, an adapter that will not
        # connect) becomes the error envelope too, so the machine payload stays
        # one JSON object. Without it, re-raise so the historical handling
        # (logged and surfaced by ``handle_cli_exceptions``) is unchanged for
        # every other caller.
        if as_json:
            msg = f"Error initialising Protean domain: {exc}"
            logger.error(msg)
            emit_usage_error(as_json=True, message=msg)
        raise
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
