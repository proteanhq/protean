"""The Protean MCP server.

Exposes framework operations (``validate``, ``check``, ``introspect``,
``explain``, ``scaffold``) as Model Context Protocol tools, each answered from
the installed framework. Run it with ``protean mcp`` (stdio by default,
``--http`` for streamable HTTP).

The tool implementations live in :mod:`protean.mcp.tools` and import no MCP SDK,
so they stay importable without the ``mcp`` extra. :mod:`protean.mcp.server`
wraps them for the SDK and is imported only when the server actually runs.

:func:`mcp_registration` returns the client-facing launch shape for this server.
It imports no SDK, so ``protean dx`` can read it on every install to write the
``.mcp.json`` entry that points a client at the server.
"""

from __future__ import annotations

from typing import Any

__all__ = ["mcp_registration"]


def mcp_registration() -> dict[str, Any]:
    """Return the ``.mcp.json`` entry a client reads to launch this server.

    The shape is the stdio launch ``protean mcp`` runs by default: run the
    ``protean`` executable with the ``mcp`` subcommand. A client merges this under
    ``mcpServers.protean``. It carries no SDK import, so ``protean dx`` can build
    the ``.mcp.json`` render without the ``mcp`` extra installed.
    """
    return {"command": "protean", "args": ["mcp"]}
