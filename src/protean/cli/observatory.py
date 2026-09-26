"""CLI command for running the Protean Observatory observability server."""

import os
from typing import Annotated

import typer

from protean.cli._helpers import (
    CTX_LOG_CONFIGURED,
    abort_for_missing_dependency,
    apply_domain_logging,
    handle_cli_exceptions,
)
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@handle_cli_exceptions("observatory")
def observatory(
    ctx: typer.Context,
    domain: Annotated[
        list[str],
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
) -> None:
    """Run the Observatory observability dashboard."""
    # The Observatory runs on the optional FastAPI/uvicorn stack
    # (protean[server]); a missing extra fails with an install hint instead of a
    # raw ModuleNotFoundError from deep inside the server package.
    try:
        from protean.server.observatory import Observatory  # noqa: PLC0415
    except ImportError as exc:
        abort_for_missing_dependency("server", "'protean observatory'", exc)

    parent_obj = getattr(ctx, "obj", None) or {}
    if not parent_obj.get(CTX_LOG_CONFIGURED):
        # Bootstrap handlers so errors raised while the domains load reach the
        # console. The first domain's [logging] replaces them once all load.
        configure_logging(level=os.getenv("PROTEAN_LOG_LEVEL", "INFO"))

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
            raise typer.Abort() from exc

        assert derived is not None
        domains.append(derived)

    # Logging is process-wide, so the first domain's [logging] wins. Apply it
    # after every domain loads, so a load failure in a later domain still
    # reports through the bootstrap handlers.
    apply_domain_logging(domains[0], parent_obj)
    for derived in domains:
        derived.init()

    obs = Observatory(domains=domains, title=title)
    obs.run(host=host, port=port)
