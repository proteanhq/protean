"""
Module that contains the command line app.

Why does this file exist, and why not put this in __main__?

  You might be tempted to import things from __main__ later, but that will cause
  problems: the code will get executed twice:

  - When you run `python -mprotean` python will execute
    ``__main__.py`` as a script. That means there won't be any
    ``protean.__main__`` in ``sys.modules``.
  - When you import __main__ it will get executed again (as a module) because
    there's no ``protean.__main__`` in ``sys.modules``.

  Also see (1) from http://click.pocoo.org/5/setuptools/#setuptools-integration
"""

import json
import warnings
from pathlib import Path
from typing import Any, Optional

import typer
from rich import print
from typing_extensions import Annotated

from protean.cli._helpers import CTX_LOG_CONFIGURED  # noqa: F401 — re-exported
from protean.cli._helpers import cli_exception_handler  # noqa: F401 — re-exported
from protean.cli._helpers import handle_cli_exceptions  # noqa: F401 — re-exported
from protean.cli.check import check
from protean.cli.database import app as db_app
from protean.cli.dlq import app as dlq_app
from protean.cli.docs import app as docs_app
from protean.cli.events import app as events_app
from protean.cli.generate import app as generate_app
from protean.cli.ir import app as ir_app
from protean.cli.schema import app as schema_app
from protean.cli.new import new
from protean.cli.observatory import observatory
from protean.cli.projection import app as projection_app
from protean.cli.shell import shell
from protean.cli.snapshot import app as snapshot_app
from protean.cli.subscriptions import app as subscriptions_app
from protean.cli.test import app as test_app
from protean.exceptions import NoDomainException
from protean.server.engine import Engine
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


# Create the Typer app
#   `no_args_is_help=True` will show the help message when no arguments are passed
app = typer.Typer(no_args_is_help=True)

app.command()(check)
app.command()(new)
app.command()(observatory)
app.command()(shell)
app.add_typer(db_app, name="db")
app.add_typer(dlq_app, name="dlq")
app.add_typer(events_app, name="events")
app.add_typer(generate_app, name="generate")
app.add_typer(ir_app, name="ir")
app.add_typer(schema_app, name="schema")
app.add_typer(docs_app, name="docs")
app.add_typer(projection_app, name="projection")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(subscriptions_app, name="subscriptions")
app.add_typer(test_app, name="test")


_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LOG_FORMATS = ("auto", "console", "json")


def version_callback(value: bool) -> None:
    if value:
        from protean import __version__

        typer.echo(f"Protean {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option(help="Show version information", callback=version_callback)
    ] = False,
    log_level: Annotated[
        Optional[str],
        typer.Option(
            "--log-level",
            help="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL",
        ),
    ] = None,
    log_format: Annotated[
        Optional[str],
        typer.Option(
            "--log-format",
            help="Logging output format: auto, console, json",
        ),
    ] = None,
    log_config: Annotated[
        Optional[Path],
        typer.Option(
            "--log-config",
            help="Path to a JSON dictConfig file for logging",
            exists=True,
            readable=True,
        ),
    ] = None,
) -> None:
    """Protean CLI"""
    # Resolve effective logging configuration per the documented precedence:
    #   1. --log-config PATH  →  dictConfig
    #   2. --log-level / --log-format  →  configure_logging(level=..., format=...)
    #   3. Otherwise  →  defer to Domain.init() auto-configuration
    ctx.ensure_object(dict)

    if log_config is not None:
        try:
            payload = json.loads(log_config.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"Error: Unable to read log config '{log_config}': {exc}")
            raise typer.Exit(code=2) from exc
        except json.JSONDecodeError as exc:
            print(f"Error: Invalid JSON in log config '{log_config}': {exc}")
            raise typer.Exit(code=2) from exc
        configure_logging(dict_config=payload)
        ctx.obj[CTX_LOG_CONFIGURED] = True
    elif log_level is not None or log_format is not None:
        kwargs: dict[str, Any] = {}
        if log_level is not None:
            upper = log_level.upper()
            if upper not in _LOG_LEVELS:
                print(
                    f"Error: Invalid log level '{log_level}'. "
                    f"Choose from: {', '.join(_LOG_LEVELS)}"
                )
                raise typer.Exit(code=2)
            kwargs["level"] = upper
        if log_format is not None:
            if log_format not in _LOG_FORMATS:
                print(
                    f"Error: Invalid log format '{log_format}'. "
                    f"Choose from: {', '.join(_LOG_FORMATS)}"
                )
                raise typer.Exit(code=2)
            kwargs["format"] = log_format
        configure_logging(**kwargs)
        ctx.obj[CTX_LOG_CONFIGURED] = True


@app.command()
def server(
    ctx: typer.Context,
    domain: Annotated[str, typer.Option()] = ".",
    test_mode: Annotated[Optional[bool], typer.Option()] = False,
    debug: Annotated[Optional[bool], typer.Option()] = False,
    workers: Annotated[int, typer.Option(help="Number of worker processes")] = 1,
    reload: Annotated[
        bool,
        typer.Option(
            "--reload",
            help="Enable auto-reload on file changes (development only)",
        ),
    ] = False,
) -> None:
    """Run Async Background Server"""

    if debug:
        warnings.warn(
            "--debug is deprecated; use --log-level DEBUG. Will be removed in v0.17.0.",
            DeprecationWarning,
            stacklevel=1,
        )

    parent_obj = getattr(ctx, "obj", None) or {}
    if not parent_obj.get(CTX_LOG_CONFIGURED):
        configure_logging(level="DEBUG" if debug else "INFO")

    with cli_exception_handler("server"):
        if workers < 1:
            print("Error: --workers must be >= 1")
            raise typer.Abort()

        if reload and workers > 1:
            print("Error: --reload cannot be combined with --workers > 1")
            raise typer.Abort()

        if reload:
            # Development path: outer Reloader watches source files and
            # restarts the inner Engine process on change.
            try:
                from protean.server.reloader import Reloader
            except ModuleNotFoundError as exc:
                # Only translate the missing-watchfiles case into the
                # install hint. Any other ModuleNotFoundError almost
                # certainly indicates a real bug inside the reloader (or
                # one of its imports) and must be re-raised so it isn't
                # masked.
                if exc.name != "watchfiles":
                    raise
                msg = (
                    "Error: --reload requires the 'watchfiles' package. "
                    "Install it with 'pip install \"protean[dev]\"'."
                )
                print(msg)
                logger.error("%s (%s)", msg, exc)
                raise typer.Abort()

            reloader = Reloader(
                domain_path=domain,
                test_mode=test_mode,
                debug=debug,
            )
            reloader.run()

            if reloader.exit_code != 0:
                raise typer.Exit(code=reloader.exit_code)
            return

        try:
            derived_domain = derive_domain(domain)
        except NoDomainException as exc:
            msg = f"Error loading Protean domain: {exc.args[0]}"
            print(msg)  # Required for tests to capture output
            logger.error(msg)

            raise typer.Abort()

        assert derived_domain is not None

        if workers == 1:
            # Single-worker path: identical to previous behavior, zero overhead.
            # Traverse and initialize domain — loads all aggregates, entities,
            # services, and other domain elements.
            derived_domain.init()

            with derived_domain.domain_context():
                engine = Engine(derived_domain, test_mode=test_mode, debug=debug)
                engine.run()

            if engine.exit_code != 0:
                raise typer.Exit(code=engine.exit_code)
        else:
            # Multi-worker path: Supervisor spawns N independent Engine processes.
            # Each worker derives and initializes the domain independently.
            from protean.server.supervisor import Supervisor

            supervisor = Supervisor(
                domain_path=domain,
                num_workers=workers,
                test_mode=test_mode,
                debug=debug,
            )
            supervisor.run()

            if supervisor.exit_code != 0:
                raise typer.Exit(code=supervisor.exit_code)
