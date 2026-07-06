"""CLI command for running the Protean Observatory observability server."""

from typing import List, Optional

import click
import typer
from typing_extensions import Annotated

from protean.cli._helpers import (
    CTX_LOG_CONFIGURED,
    handle_cli_exceptions,
    warn_debug_flag_deprecated,
)
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@handle_cli_exceptions("observatory")
def observatory(
    domain: Annotated[
        List[str],
        typer.Option(help="Domain module path(s) to monitor"),
    ],
    host: Annotated[
        str,
        typer.Option(
            help=(
                "Host to bind to. Defaults to loopback (127.0.0.1); the "
                "Observatory is unauthenticated, so pass 0.0.0.0 only on a "
                "trusted network behind an authenticating proxy."
            )
        ),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind to")] = 9000,
    title: Annotated[
        str, typer.Option(help="Observatory title")
    ] = "Protean Observatory",
    debug: Annotated[Optional[bool], typer.Option(help="Enable debug logging")] = False,
) -> None:
    """Run the Observatory observability dashboard."""
    from protean.server.observatory import Observatory  # noqa: PLC0415

    if debug:
        warn_debug_flag_deprecated()

    # Check parent context for CLI-level logging configuration.
    # click.get_current_context may fail when called directly (not via CLI).
    ctx = click.get_current_context(silent=True)
    parent_obj = getattr(ctx, "obj", None) or {} if ctx else {}
    if not parent_obj.get(CTX_LOG_CONFIGURED):
        configure_logging(level="DEBUG" if debug else "INFO")

    if not domain:
        print("Error: at least one --domain is required")
        raise typer.Abort()

    domains = []
    for domain_path in domain:
        try:
            derived = derive_domain(domain_path)
        except NoDomainException as exc:
            msg = f"Error loading Protean domain '{domain_path}': {exc.args[0]}"
            print(msg)
            logger.error(msg)
            raise typer.Abort()

        assert derived is not None
        derived.init()
        domains.append(derived)

    obs = Observatory(domains=domains, title=title)
    obs.run(host=host, port=port)
