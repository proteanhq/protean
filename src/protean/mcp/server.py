"""The Protean MCP server: framework capabilities exposed as MCP tools.

[`build_server`][protean.mcp.server.build_server] assembles an
:class:`~mcp.server.MCPServer` with five tools, each backed by a plain function
in :mod:`protean.mcp.tools` that answers from the installed framework:

- ``validate`` and ``check`` run the domain's validation and diagnostics.
- ``introspect`` returns the domain's Intermediate Representation.
- ``explain`` explains a diagnostic code.
- ``scaffold`` previews a new element slice, and writes it only on consent.

This module imports the ``mcp`` SDK at import time, so importing it requires the
``mcp`` extra. Nothing in ``import protean`` reaches it; the ``protean mcp``
command imports it lazily and turns a missing extra into an install hint.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import TypeVar, cast

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from protean import __version__
from protean.mcp import tools

_F = TypeVar("_F", bound=Callable[..., object])

_INSTRUCTIONS = (
    "Protean framework tools answered from the installed version. Use `validate` "
    "for a go/no-go check that a domain loads and passes validation, `check` for "
    "the full diagnostic report, `introspect` for the domain's Intermediate "
    "Representation, `explain` to understand a diagnostic code, and `scaffold` to "
    "preview (and, on consent, write) a new element slice. The read tools "
    "auto-discover the domain from the working directory; pass `domain` to point "
    "at another."
)


def _as_tool(fn: _F) -> _F:
    """Adapt a :mod:`protean.mcp.tools` function into an MCP tool body.

    A tool signals a caller-facing failure by raising
    [`McpToolError`][protean.mcp.tools.McpToolError]. The SDK shows a
    deliberately-raised ``ToolError`` to the model as an error result but treats
    any other exception as a server crash whose message is hidden, so this
    translates one into the other. ``functools.wraps`` sets ``__wrapped__`` on the
    wrapper, and ``inspect.signature`` (which the SDK uses to build the input
    schema) follows it, so the wrapped function's real signature and docstring
    reach the SDK even though ``wrapper`` itself takes ``*args``/``**kwargs``.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return fn(*args, **kwargs)
        except tools.McpToolError as exc:
            raise ToolError(str(exc)) from exc

    # ``wrapper`` is statically typed as ``(*args, **kwargs) -> object``; cast it
    # back to the wrapped function's own type so callers keep its real signature.
    return cast(_F, wrapper)


def build_server() -> MCPServer:
    """Build the Protean MCP server with its five tools registered.

    The server is version-stamped with the installed framework version, so a
    client sees exactly which Protean it is talking to.
    """
    server: MCPServer = MCPServer(
        name="protean",
        version=__version__,
        instructions=_INSTRUCTIONS,
    )

    # The SDK derives each tool's input schema from the function's type hints and
    # its description from the docstring, both preserved through the wrapper.
    for fn in (
        tools.validate,
        tools.check,
        tools.introspect,
        tools.explain,
        tools.scaffold,
    ):
        server.tool()(_as_tool(fn))

    return server
