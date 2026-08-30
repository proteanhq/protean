"""Tests for the ``protean mcp`` CLI command.

These cover the command's help, the two transports, and the missing-extra guard.
The server itself is exercised in ``tests/mcp``; here ``build_server`` is
replaced with a stand-in so the command's wiring is tested without launching a
real stdio/HTTP server.
"""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from protean.cli import app
from tests.shared import module_unavailable

runner = CliRunner()


def test_help_lists_the_tools():
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    for tool in ("validate", "check", "introspect", "explain", "scaffold"):
        assert tool in result.output


def test_default_transport_is_stdio():
    fake_server = MagicMock()
    with patch("protean.mcp.server.build_server", return_value=fake_server):
        result = runner.invoke(app, ["mcp"])

    assert result.exit_code == 0
    # stdio is the default: run() is called with no transport arguments.
    fake_server.run.assert_called_once_with()


def test_logs_are_routed_to_stderr_before_serving():
    # stdout is the JSON-RPC channel on stdio, so the command must route logging
    # to stderr up front, before any tool call imports a domain module.
    fake_server = MagicMock()
    with (
        patch("protean.mcp.server.build_server", return_value=fake_server),
        patch("protean.cli.mcp.route_logs_to_stderr") as route,
    ):
        result = runner.invoke(app, ["mcp"])

    assert result.exit_code == 0
    route.assert_called_once()


def test_log_routing_is_skipped_when_the_cli_already_configured_it():
    # A global --log-level configures logging in the root callback; the command
    # must pass that through so route_logs_to_stderr does not rebuild (and discard)
    # the operator's configuration.
    fake_server = MagicMock()
    with (
        patch("protean.mcp.server.build_server", return_value=fake_server),
        patch("protean.cli.mcp.route_logs_to_stderr") as route,
    ):
        result = runner.invoke(app, ["--log-level", "DEBUG", "mcp"])

    assert result.exit_code == 0
    route.assert_called_once_with(log_already_configured=True)


def test_http_transport_passes_host_and_port():
    fake_server = MagicMock()
    with patch("protean.mcp.server.build_server", return_value=fake_server):
        result = runner.invoke(
            app, ["mcp", "--http", "--host", "0.0.0.0", "--port", "9999"]
        )

    assert result.exit_code == 0
    fake_server.run.assert_called_once_with(
        transport="streamable-http", host="0.0.0.0", port=9999
    )


def test_missing_extra_aborts_with_install_hint():
    # Simulate the `mcp` SDK being absent and force the server module to
    # re-import so it hits the missing dependency.
    with module_unavailable("mcp", reload=("protean.mcp.server",)):
        result = runner.invoke(app, ["mcp"])

    assert result.exit_code == 1
    assert "mcp" in result.output
    assert 'pip install "protean[mcp]"' in result.output
