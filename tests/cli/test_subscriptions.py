"""Tests for CLI subscriptions commands (protean subscriptions ...)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from protean.server.subscription_status import SubscriptionStatus
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
            patch("protean.cli.subscriptions.derive_domain", return_value=mock_domain),
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
            patch("protean.cli.subscriptions.derive_domain", return_value=mock_domain),
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
            patch("protean.cli.subscriptions.derive_domain", return_value=mock_domain),
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
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["handler_name"] == "OrderHandler"

    def test_json_output_empty(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_for_cli()

        with (
            patch("protean.cli.subscriptions.derive_domain", return_value=mock_domain),
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
        parsed = json.loads(result.output)
        assert parsed == []

    def test_domain_loading_error(self):
        change_working_directory_to("test7")

        with patch(
            "protean.cli.subscriptions.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                ["subscriptions", "status", "--domain", "nonexistent.py"],
            )

        assert result.exit_code != 0

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
            patch("protean.cli.subscriptions.derive_domain", return_value=mock_domain),
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
            patch("protean.cli.subscriptions.derive_domain", return_value=mock_domain),
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
