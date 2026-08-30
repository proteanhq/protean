"""Tests for the MCP server wiring in :mod:`protean.mcp.server`.

These check that the server registers the five tools with the right schemas and
that a call round-trips through the SDK to the underlying tool function, both for
a success and for a caller-facing error.
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from protean import __version__
from protean.mcp import tools
from protean.mcp.server import _as_tool, build_server

EXPECTED_TOOLS = {"validate", "check", "introspect", "explain", "scaffold"}


def _tools_by_name():
    server = build_server()
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def test_server_is_stamped_with_the_framework_version():
    server = build_server()
    assert server.name == "protean"
    assert server.version == __version__
    assert server.instructions


def test_server_exposes_exactly_the_five_tools():
    assert set(_tools_by_name()) == EXPECTED_TOOLS


@pytest.mark.parametrize(
    "tool_name, expected_params",
    [
        ("validate", {"domain"}),
        ("check", {"domain"}),
        ("introspect", {"domain"}),
        ("explain", {"code"}),
        ("scaffold", {"element", "name", "project", "apply"}),
    ],
)
def test_each_tool_declares_its_input_schema(tool_name, expected_params):
    tool = _tools_by_name()[tool_name]
    properties = set((tool.input_schema or {}).get("properties", {}))
    assert properties == expected_params
    assert tool.description  # the docstring reaches the client as the description


def test_a_tool_call_round_trips_to_the_function():
    server = build_server()
    result = asyncio.run(server.call_tool("explain", {"code": "UNHANDLED_EVENT"}))
    assert result.is_error is False
    assert result.structured_content["code"] == "UNHANDLED_EVENT"


def test_a_caller_facing_error_becomes_a_tool_error():
    server = build_server()
    # The SDK re-raises a deliberately-raised ToolError from call_tool; over the
    # wire the kernel renders it as an error result the model sees.
    with pytest.raises(ToolError, match="Unknown diagnostic code"):
        asyncio.run(server.call_tool("explain", {"code": "NOPE"}))


def test_the_authored_tools_declare_an_output_schema():
    # validate and explain build a fixed shape here, typed as TypedDicts, so the
    # SDK hands the client a structured output contract for them.
    by_name = _tools_by_name()
    for name in ("validate", "explain"):
        schema = by_name[name].output_schema
        assert schema and schema.get("properties"), name


def test_the_wrapper_only_translates_mcp_tool_error():
    # A deliberately-raised McpToolError becomes a ToolError shown to the model;
    # any other exception passes through unchanged so the SDK logs it as a crash.
    def raises_mcp():
        raise tools.McpToolError("caller-facing")

    def raises_other():
        raise ValueError("real bug")

    with pytest.raises(ToolError, match="caller-facing"):
        _as_tool(raises_mcp)()

    with pytest.raises(ValueError, match="real bug"):
        _as_tool(raises_other)()
