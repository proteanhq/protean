"""CLI commands for database lifecycle management."""

import typer
from rich import print
from typing_extensions import Annotated

from protean.exceptions import ConfigurationError, NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Manage database tables for a Protean domain."""


@app.command()
def setup(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
) -> None:
    """Create all database tables (aggregates, entities, projections, outbox)."""
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None

    derived_domain.init()
    with derived_domain.domain_context():
        derived_domain.setup_database()

    print("Database tables created successfully.")


@app.command()
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

    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None

    derived_domain.init()
    with derived_domain.domain_context():
        derived_domain.drop_database()

    print("Database tables dropped successfully.")


@app.command(name="setup-outbox")
def setup_outbox(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
) -> None:
    """Create only outbox tables (for stream subscription migration)."""
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None

    derived_domain.init()
    try:
        with derived_domain.domain_context():
            derived_domain.setup_outbox()
    except ConfigurationError as exc:
        print(f"Error: {exc.args[0]}")
        raise typer.Abort()

    print("Outbox tables created successfully.")
