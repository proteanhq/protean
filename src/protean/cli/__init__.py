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

import subprocess

from enum import Enum
from typing import Optional

import typer

from rich import print
from typing_extensions import Annotated

from protean.cli.docs import app as docs_app
from protean.cli.generate import app as generate_app
from protean.cli.new import new
from protean.exceptions import NoDomainException
from protean.utils.domain import derive_domain

# Create the Typer app
#   `no_args_is_help=True` will show the help message when no arguments are passed
app = typer.Typer(no_args_is_help=True)

app.command()(new)
app.add_typer(generate_app, name="generate")
app.add_typer(docs_app, name="docs")


class Category(str, Enum):
    CORE = "CORE"
    EVENTSTORE = "EVENTSTORE"
    DATABASE = "DATABASE"
    FULL = "FULL"


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
def test(
    category: Annotated[
        Category, typer.Option("-c", "--category", case_sensitive=False)
    ] = Category.CORE
):
    commands = ["pytest", "--cache-clear", "--ignore=tests/support/"]

    match category.value:
        case "EVENTSTORE":
            # Run tests for EventStore adapters
            # FIXME: Add support for auto-fetching supported event stores
            for store in ["MEMORY", "MESSAGE_DB"]:
                print(f"Running tests for EVENTSTORE: {store}...")
                subprocess.call(commands + ["-m", "eventstore", f"--store={store}"])
        case "DATABASE":
            # Run tests for database adapters
            # FIXME: Add support for auto-fetching supported databases
            for db in ["POSTGRESQL", "SQLITE"]:
                print(f"Running tests for DATABASE: {db}...")
                subprocess.call(commands + ["-m", "database", f"--db={db}"])
        case "FULL":
            # Run full suite of tests with coverage
            # FIXME: Add support for auto-fetching supported adapters
            subprocess.call(
                commands
                + [
                    "--slow",
                    "--sqlite",
                    "--postgresql",
                    "--elasticsearch",
                    "--redis",
                    "--message_db",
                    "--cov=protean",
                    "--cov-config",
                    ".coveragerc",
                    "tests",
                ]
            )

            # Test against each supported database
            for db in ["POSTGRESQL", "SQLITE"]:
                print(f"Running tests for DB: {db}...")

                subprocess.call(commands + ["-m", "database", f"--db={db}"])

            for store in ["MESSAGE_DB"]:
                print(f"Running tests for EVENTSTORE: {store}...")
                subprocess.call(commands + ["-m", "eventstore", f"--store={store}"])
        case _:
            print("Running core tests...")
            subprocess.call(commands)


@app.command()
def server(
    domain_path: Annotated[str, typer.Argument()] = "",
    test_mode: Annotated[Optional[bool], typer.Option()] = False,
):
    """Run Async Background Server"""
    # FIXME Accept MAX_WORKERS as command-line input as well
    from protean.server import Engine

    domain = derive_domain(domain_path)
    if not domain:
        raise NoDomainException(
            "Could not locate a Protean domain. You should provide a domain in"
            '"PROTEAN_DOMAIN" environment variable or pass a domain file in options '
            'and a "domain.py" module was not found in the current directory.'
        )

    engine = Engine(domain, test_mode=test_mode)
    engine.run()
