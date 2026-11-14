"""CLI commands for database lifecycle management."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypeVar

import typer
from rich import print

from protean.adapters.repository.schema_migrator import (
    _migrations_provider_name,
    migration_provider,
)
from protean.cli._helpers import handle_cli_exceptions, load_domain
from protean.exceptions import ConfigurationError, NotSupportedError

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.provider import SchemaMigrator

T = TypeVar("T")

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


def _with_migrator(
    derived_domain: "Domain",
    directory: Path,
    provider: str | None,
    action: "Callable[[SchemaMigrator], T]",
) -> T:
    """Run ``action`` on the schema migrator of a checked provider.

    ``provider`` names the provider; when it is None, the name is read from
    the ``alembic.ini`` in ``directory``. A ``ConfigurationError`` or
    ``NotSupportedError`` is printed and aborts the command.
    """
    try:
        with derived_domain.domain_context():
            name = (
                provider
                if provider is not None
                else _migrations_provider_name(directory)
            )
            checked = migration_provider(derived_domain, name)
            return action(checked.schema_migrator(directory))
    except (ConfigurationError, NotSupportedError) as exc:
        # typer.echo, not rich's print: rich would read "[sqlite]" in an
        # install hint such as "protean[sqlite]" as markup and drop it.
        typer.echo(f"Error: {exc.args[0]}")
        raise typer.Abort() from exc


DomainOption = Annotated[str, typer.Option(help="Domain module path")]
DirectoryOption = Annotated[
    str, typer.Option(help="Folder that holds the provider's migrations")
]
SqlOption = Annotated[
    bool,
    typer.Option("--sql", help="Print the SQL instead of running it, offline"),
]


@app.command(name="init")
@handle_cli_exceptions("db init")
def init(
    domain: DomainOption = ".",
    provider: Annotated[
        str, typer.Option(help="Name of the provider the migrations belong to")
    ] = "default",
    directory: Annotated[
        str, typer.Option(help="Folder to create the migrations in")
    ] = "migrations",
) -> None:
    """Create a migrations folder for one database provider."""
    derived_domain = load_domain(domain)
    # Record the path the domain was loaded from, which is PROTEAN_DOMAIN when
    # it is set, so a plain ``alembic`` run loads the same domain.
    domain_path = os.environ.get("PROTEAN_DOMAIN") or domain
    _with_migrator(
        derived_domain,
        Path(directory),
        provider,
        lambda migrator: migrator.init(domain_path),
    )

    typer.echo(f"Created migrations for provider '{provider}' in {directory}.")


def _require_message(value: str) -> str:
    # A blank message would name the migration file by its hash alone.
    if not value.strip():
        raise typer.BadParameter("describe what the migration changes")
    return value


@app.command(name="migrate")
@handle_cli_exceptions("db migrate")
def migrate(
    message: Annotated[
        str,
        typer.Option(
            "--message",
            "-m",
            help="What the migration changes",
            callback=_require_message,
        ),
    ],
    domain: DomainOption = ".",
    directory: DirectoryOption = "migrations",
) -> None:
    """Write a migration for the changes between the model and the database."""
    derived_domain = load_domain(domain)
    path = _with_migrator(
        derived_domain,
        Path(directory),
        None,
        lambda migrator: migrator.migrate(message),
    )

    if path is None:
        typer.echo("No changes detected; no migration written.")
    else:
        typer.echo(f"Wrote migration {path}.")


@app.command(name="upgrade")
@handle_cli_exceptions("db upgrade")
def upgrade(
    revision: Annotated[
        str, typer.Argument(help="Revision to upgrade to, such as head or +1")
    ] = "head",
    domain: DomainOption = ".",
    directory: DirectoryOption = "migrations",
    sql: SqlOption = False,
) -> None:
    """Apply migrations to the database, up to the latest by default."""
    derived_domain = load_domain(domain, connect=not sql)
    _with_migrator(
        derived_domain,
        Path(directory),
        None,
        lambda migrator: migrator.upgrade(revision, sql=sql),
    )

    # With --sql, the output is the SQL script, and a message would break it.
    if not sql:
        typer.echo(f"Upgraded the database to {revision}.")


# ``ignore_unknown_options`` lets ``-1`` through as the revision, where Click
# would reject it as an unknown option.
@app.command(name="downgrade", context_settings={"ignore_unknown_options": True})
@handle_cli_exceptions("db downgrade")
def downgrade(
    revision: Annotated[
        str,
        typer.Argument(
            help="Revision to downgrade to, such as -1, a revision id or base. "
            "With --sql, a range such as head:base."
        ),
    ],
    domain: DomainOption = ".",
    directory: DirectoryOption = "migrations",
    sql: SqlOption = False,
) -> None:
    """Revert migrations in the database, down to the revision given."""
    derived_domain = load_domain(domain, connect=not sql)
    _with_migrator(
        derived_domain,
        Path(directory),
        None,
        lambda migrator: migrator.downgrade(revision, sql=sql),
    )

    if not sql:
        typer.echo(f"Downgraded the database to {revision}.")
