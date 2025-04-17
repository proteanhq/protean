"""CLI command for running the FastAPI server."""

import logging
from typing import Optional

import typer
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.server.fastapi_server import ProteanFastAPIServer
from protean.utils.domain_discovery import derive_domain

logger = logging.getLogger(__name__)

app = typer.Typer()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    domain: Annotated[str, typer.Option(help="Path to the domain")] = ".",
    host: Annotated[str, typer.Option(help="Host to bind to")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Port to bind to")] = 8000,
    debug: Annotated[Optional[bool], typer.Option(help="Enable debug mode")] = False,
    cors: Annotated[Optional[bool], typer.Option(help="Enable CORS")] = True,
    cors_origins: Annotated[
        Optional[str],
        typer.Option(
            help="Comma-separated list of allowed CORS origins. Defaults to '*'"
        ),
    ] = None,
):
    """Run the FastAPI server for Protean applications.

    This command starts a FastAPI server that loads the domain and sets up the necessary
    context for processing requests.
    """
    # Exit if another command is being run
    if ctx.invoked_subcommand is not None:
        return

    # Validate that CORS origins are not provided when CORS is disabled
    if not cors and cors_origins:
        msg = "Cannot specify CORS origins when CORS is disabled"
        typer.echo(msg, err=True)
        logger.error(msg)
        raise typer.Abort()

    try:
        domain_instance = derive_domain(domain)

        typer.echo(f"Starting Protean FastAPI server at {host}:{port}...")

        # Parse CORS origins if provided
        cors_origins_list = cors_origins.split(",") if cors_origins else None

        # Create and run server
        server = ProteanFastAPIServer(
            domain=domain_instance,
            debug=debug,
            enable_cors=cors,
            cors_origins=cors_origins_list,
        )
        server.run(host=host, port=port)

    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        typer.echo(msg, err=True)
        logger.error(msg)

        raise typer.Abort()
    except Exception as exc:
        msg = f"Error starting server: {exc}"
        typer.echo(msg, err=True)
        logger.error(msg)

        raise typer.Abort()
