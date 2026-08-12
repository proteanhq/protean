"""Tests for CLI subscriptions commands (protean subscriptions ...)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.result import EXIT_USAGE
from protean.exceptions import NoDomainException
from protean.server.subscription_status import SubscriptionStatus
from tests.cli._envelope import assert_envelope
from tests.shared import change_working_directory_to

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status(
    handler_name: str = "TestHandler",
    subscription_type: str = "stream",
    stream_category: str = "test",
    lag: int | None = 0,
    pending: int = 0,
    dlq_depth: int = 0,
    consumer_count: int = 1,
    status: str = "ok",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=lag,
        pending=pending,
        current_position="10",
        head_position="10",
        status=status,
        consumer_count=consumer_count,
        dlq_depth=dlq_depth,
    )


def _mock_domain_for_cli() -> MagicMock:
    """Create a mock domain suitable for CLI testing."""
    mock_domain = MagicMock()
    mock_domain.name = "test-domain"
    return mock_domain


# ---------------------------------------------------------------------------
# protean subscriptions status
# ---------------------------------------------------------------------------


class TestSubscriptionsStatus:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run."""
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_shows_table_with_subscriptions(self):
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", "event_store", "order"),
            _make_status(
                "PaymentHandler",
                "stream",
                "payment",
                lag=42,
                pending=3,
                dlq_depth=1,
                status="lagging",
            ),
        ]
        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=statuses,
            ),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 0
        # Rich may truncate handler names in narrow terminals
        assert "OrderHan" in result.output
        assert "PaymentH" in result.output
        assert "2 subscription(s)" in result.output

    def test_shows_empty_message(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=[],
            ),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 0
        assert "No subscriptions found" in result.output

    def test_json_output(self):
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", "event_store", "order"),
        ]
        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=statuses,
            ),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py", "--json"],
            )

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        subs = env["data"]["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["handler_name"] == "OrderHandler"

    def test_json_output_empty(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=[],
            ),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py", "--json"],
            )

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["subscriptions"] == []

    def test_domain_loading_error(self):
        change_working_directory_to("test7")

        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "nonexistent.py"],
            )

        # Historical human path: typer.Abort, exit 1 (not the envelope's exit 2).
        assert result.exit_code == 1

    def test_json_load_error_is_envelope(self):
        """A domain-load failure under --json is the error envelope on stdout,
        exit 2, with no rich markup leaking onto the machine payload."""
        change_working_directory_to("test7")

        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "nonexistent.py", "--json"],
            )

        assert result.exit_code == EXIT_USAGE
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert "Error loading Protean domain" in env["data"]["error"]
        assert "[red]" not in result.stdout

    def test_json_init_failure_is_envelope(self):
        """A domain that derives but fails to init, under --json, is the error
        envelope (the _helpers.load_domain init branch)."""
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.name = "test-domain"
        mock_domain.init.side_effect = RuntimeError("adapter down")

        with patch("protean.cli._helpers.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py", "--json"],
            )

        assert result.exit_code == EXIT_USAGE
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert "Error initialising Protean domain" in env["data"]["error"]
        assert "[red]" not in result.stdout

    def test_non_json_init_failure_is_unchanged(self):
        """Without --json an init failure keeps its historical propagation:
        surfaced by handle_cli_exceptions at exit 1, never the envelope."""
        change_working_directory_to("test7")

        mock_domain = MagicMock()
        mock_domain.name = "test-domain"
        mock_domain.init.side_effect = RuntimeError("adapter down")

        with patch("protean.cli._helpers.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 1
        assert '"status": "error"' not in result.stdout

    def test_table_with_unknown_and_zero_counts(self):
        """Table renders '-' for lag=None, dlq_depth=0, and consumer_count=0."""
        change_working_directory_to("test7")

        statuses = [
            _make_status(
                "UnknownHandler",
                lag=None,
                dlq_depth=0,
                consumer_count=0,
                status="unknown",
            ),
        ]
        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=statuses,
            ),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 0
        assert "1 subscription(s)" in result.output
        assert "unknown" in result.output

    def test_summary_counts(self):
        change_working_directory_to("test7")

        statuses = [
            _make_status("A", status="ok"),
            _make_status("B", lag=5, status="lagging"),
            _make_status("C", lag=None, status="unknown"),
        ]
        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
            patch(
                "protean.server.subscription_status.collect_subscription_statuses",
                return_value=statuses,
            ),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "publishing7.py"],
            )

        assert result.exit_code == 0
        assert "3 subscription(s)" in result.output
        assert "1 ok" in result.output
        assert "1 lagging" in result.output
        assert "1 unknown" in result.output
