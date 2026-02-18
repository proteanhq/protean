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

from typing import Optional

import typer
from rich import print
from typing_extensions import Annotated

from protean.cli.database import app as db_app
from protean.cli.docs import app as docs_app
from protean.cli.generate import app as generate_app
from protean.cli.new import new
from protean.cli.observatory import observatory
from protean.cli.shell import shell
from protean.cli.test import app as test_app
from protean.exceptions import NoDomainException
from protean.server.engine import Engine
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)

# Create the Typer app
#   `no_args_is_help=True` will show the help message when no arguments are passed
app = typer.Typer(no_args_is_help=True)

app.command()(new)
app.command()(observatory)
app.command()(shell)
app.add_typer(db_app, name="db")
app.add_typer(generate_app, name="generate")
app.add_typer(docs_app, name="docs")
app.add_typer(test_app, name="test")


def version_callback(value: bool):
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
):
    """
    Protean CLI
    """


@app.command()
def server(
    domain: Annotated[str, typer.Option()] = ".",
    test_mode: Annotated[Optional[bool], typer.Option()] = False,
    debug: Annotated[Optional[bool], typer.Option()] = False,
    workers: Annotated[int, typer.Option(help="Number of worker processes")] = 1,
):
    """Run Async Background Server"""
    # Configure logging based on debug flag
    configure_logging(level="DEBUG" if debug else "INFO")

    if workers < 1:
        print("Error: --workers must be >= 1")
        raise typer.Abort()

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
