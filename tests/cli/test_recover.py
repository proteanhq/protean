"""Tests for the CLI recover command (protean recover --verify-checkpoints)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from protean.server.subscription_status import SubscriptionStatus
from tests.cli._envelope import assert_envelope
from tests.shared import change_working_directory_to

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status(
    handler_name: str = "OrderHandler",
    subscription_type: str = "event_store",
    stream_category: str = "order",
    current_position: str | None = "10",
    head_position: str | None = "10",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=0,
        pending=0,
        current_position=current_position,
        head_position=head_position,
        status="ok",
        consumer_count=0,
        dlq_depth=0,
    )


def _mock_domain_for_cli() -> MagicMock:
    mock_domain = MagicMock()
    mock_domain.name = "test-domain"
    return mock_domain


def _invoke(statuses, extra_args=None):
    mock_domain = _mock_domain_for_cli()
    with (
        patch("protean.cli._helpers.derive_domain", return_value=mock_domain),
        patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ),
    ):
        return runner.invoke(
            app,
            ["recover", "--verify-checkpoints", "--domain", "publishing7.py"]
            + (extra_args or []),
        )


class TestRecoverVerifyCheckpoints:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_beyond_head_is_flagged_and_named(self):
        """Criterion 1: a checkpoint past the head fails, naming the subscription
        and both positions."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="10", head_position="5"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 1
        assert "OrderHandler" in result.output
        assert "10" in result.output
        assert "5" in result.output
        assert "beyond head" in result.output

    def test_all_consistent_exits_zero(self):
        """Criterion 2: every checkpoint at or behind the head exits 0."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("A", current_position="5", head_position="5"),
            _make_status("B", current_position="3", head_position="9"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "consistent" in result.output

    def test_fresh_subscription_is_consistent(self):
        """Criterion 4: a fresh checkpoint (-1) against a real head reads
        consistent, exit 0."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Fresh", current_position="-1", head_position="7"),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "beyond head" not in result.output

    def test_non_event_store_is_ignored(self):
        """Negative test for the event-store filter: a broker subscription whose
        numeric current is past head is never flagged."""
        change_working_directory_to("test7")

        statuses = [
            _make_status(
                "BrokerHandler",
                subscription_type="broker",
                current_position="99",
                head_position="1",
            ),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "No event-store subscriptions found" in result.output
        assert "BrokerHandler" not in result.output

    def test_unknown_status_is_skipped_not_flagged(self):
        """An unreachable store (None positions) is not a violation and does not
        crash the int comparison."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("Unknown", current_position=None, head_position=None),
        ]
        result = _invoke(statuses)

        assert result.exit_code == 0
        assert "unknown" in result.output
        assert "beyond head" not in result.output

    def test_no_flag_prints_hint_and_exits_zero(self):
        """Without --verify-checkpoints the command prints its hint and exits 0
        without loading the domain."""
        change_working_directory_to("test7")

        with patch("protean.cli._helpers.derive_domain") as derive:
            result = runner.invoke(app, ["recover"])

        assert result.exit_code == 0
        assert "--verify-checkpoints" in result.output
        derive.assert_not_called()

    def test_domain_loading_error(self):
        """A missing domain exits non-zero on the human path (typer.Abort)."""
        change_working_directory_to("test7")

        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                ["recover", "--verify-checkpoints", "--domain", "nonexistent.py"],
            )

        assert result.exit_code == 1


class TestRecoverJson:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_fail_when_beyond_head(self):
        """Criterion 3: --json fails with the envelope, status=fail, and the
        per-subscription checkpoint/head/beyond_head fields."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="10", head_position="5"),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 1
        env = assert_envelope(result.stdout)
        assert env["status"] == "fail"
        subs = env["data"]["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["checkpoint_position"] == "10"
        assert subs[0]["head_position"] == "5"
        assert subs[0]["beyond_head"] is True
        assert env["data"]["summary"] == {"checked": 1, "beyond_head": 1}

    def test_json_pass_when_consistent(self):
        """--json passes (status=pass, exit 0) when no checkpoint is beyond head."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="5", head_position="5"),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["subscriptions"][0]["beyond_head"] is False
        assert env["data"]["summary"] == {"checked": 1, "beyond_head": 0}

    def test_json_only_event_store_in_payload(self):
        """--json lists only event-store subscriptions; a broker one is excluded."""
        change_working_directory_to("test7")

        statuses = [
            _make_status("OrderHandler", current_position="5", head_position="5"),
            _make_status(
                "BrokerHandler",
                subscription_type="broker",
                current_position="99",
                head_position="1",
            ),
        ]
        result = _invoke(statuses, ["--json"])

        assert result.exit_code == 0
        env = assert_envelope(result.stdout)
        names = [s["handler_name"] for s in env["data"]["subscriptions"]]
        assert names == ["OrderHandler"]

    def test_json_domain_load_error_is_envelope(self):
        """A domain-load failure under --json is the error envelope on stdout,
        exit 2, no rich markup leaked."""
        from protean.cli.result import EXIT_USAGE

        change_working_directory_to("test7")

        with patch(
            "protean.cli._helpers.derive_domain",
            side_effect=NoDomainException("not found"),
        ):
            result = runner.invoke(
                app,
                [
                    "recover",
                    "--verify-checkpoints",
                    "--domain",
                    "nonexistent.py",
                    "--json",
                ],
            )

        assert result.exit_code == EXIT_USAGE
        env = assert_envelope(result.stdout)
        assert env["status"] == "error"
        assert "Error loading Protean domain" in env["data"]["error"]
        assert "[red]" not in result.stdout
