"""CLI command for running the Protean MCP server."""

from typing import Annotated

import typer

from protean.cli._helpers import (
    CTX_LOG_CONFIGURED,
    abort_for_missing_dependency,
    handle_cli_exceptions,
)
from protean.cli.result import route_logs_to_stderr
from protean.utils.logging import get_logger

logger = get_logger(__name__)


@handle_cli_exceptions("mcp")
def mcp(
    ctx: typer.Context,
    http: Annotated[
        bool,
        typer.Option(
            help=(
                "Serve over streamable HTTP instead of stdio. stdio is the "
                "default and needs no host/port."
            )
        ),
    ] = False,
    host: Annotated[
        str,
        typer.Option(
            help=(
                "Host to bind to for --http. Defaults to loopback (127.0.0.1); "
                "the server is unauthenticated, so pass 0.0.0.0 only on a "
                "trusted network behind an authenticating proxy."
            )
        ),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind to for --http")] = 8000,
) -> None:
    """Run the Protean MCP server, exposing framework tools to a coding agent.

    Serves validate, check, introspect, explain, and scaffold over the Model
    Context Protocol, each answered from the installed framework. Runs on stdio
    by default so an MCP client can launch it directly; pass --http to serve over
    streamable HTTP instead.
    """
    # On stdio, stdout is the JSON-RPC protocol channel. Route logging to stderr
    # before any tool call imports a domain module, so a stray import-time log (or
    # a log during check/init) cannot land on stdout and corrupt a frame. Skip if
    # the CLI's --log-config/--log-level/--log-format callback already configured
    # logging, so that configuration is not silently discarded.
    parent_obj = ctx.obj or {}
    route_logs_to_stderr(
        log_already_configured=bool(parent_obj.get(CTX_LOG_CONFIGURED))
    )

    # The server runs on the optional MCP SDK (protean[mcp]); a missing extra
    # fails with an install hint instead of a raw ModuleNotFoundError from the
    # SDK. The import stays lazy so `protean --help` never pulls the SDK in.
    try:
        from protean.mcp.server import build_server  # noqa: PLC0415
    except ImportError as exc:
        abort_for_missing_dependency("mcp", "'protean mcp'", exc)

    server = build_server()

    if http:
        logger.info("mcp.serving", transport="streamable-http", host=host, port=port)
        server.run(transport="streamable-http", host=host, port=port)
    else:
        server.run()
