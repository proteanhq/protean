"""The Protean MCP server.

Exposes framework operations (``validate``, ``check``, ``introspect``,
``explain``, ``scaffold``) as Model Context Protocol tools, each answered from
the installed framework. Run it with ``protean mcp`` (stdio by default,
``--http`` for streamable HTTP).

The tool implementations live in :mod:`protean.mcp.tools` and import no MCP SDK,
so they stay importable without the ``mcp`` extra. :mod:`protean.mcp.server`
wraps them for the SDK and is imported only when the server actually runs.
"""
