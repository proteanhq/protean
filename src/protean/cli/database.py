"""CLI commands for database lifecycle management."""

from typing import Annotated

import typer
from rich import print

from protean.cli._helpers import handle_cli_exceptions, load_domain
from protean.exceptions import ConfigurationError

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Manage database tables for a Protean domain."""


@app.command()
@handle_cli_exceptions("db setup")
def setup(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
) -> None:
    """Create all database tables (aggregates, entities, projections, outbox)."""
    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        derived_domain.setup_database()

    print("Database tables created successfully.")


@app.command()
@handle_cli_exceptions("db drop")
def drop(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")
    ] = False,
) -> None:
    """Drop all database tables."""
    if not yes:
        confirmed = typer.confirm("This will drop all database tables. Are you sure?")
        if not confirmed:
            raise typer.Abort()

    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        derived_domain.drop_database()

    print("Database tables dropped successfully.")


@app.command()
@handle_cli_exceptions("db truncate")
def truncate(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")
    ] = False,
) -> None:
    """Delete all rows from every table, preserving the schema."""
    if not yes:
        confirmed = typer.confirm(
            "This will delete all data from every table. Are you sure?"
        )
        if not confirmed:
            raise typer.Abort()

    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        derived_domain.truncate_database()

    print("All table data deleted successfully.")


@app.command(name="setup-outbox")
@handle_cli_exceptions("db setup-outbox")
def setup_outbox(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
) -> None:
    """Create only outbox tables (for stream subscription migration)."""
    derived_domain = load_domain(domain)
    try:
        with derived_domain.domain_context():
            derived_domain.setup_outbox()
    except ConfigurationError as exc:
        print(f"Error: {exc.args[0]}")
        raise typer.Abort() from exc

    print("Outbox tables created successfully.")
