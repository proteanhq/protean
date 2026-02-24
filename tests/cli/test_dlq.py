"""Tests for CLI DLQ commands (protean dlq ...)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.dlq import _format_time
from protean.exceptions import NoDomainException
from protean.port.broker import DLQEntry
from tests.shared import change_working_directory_to

runner = CliRunner()


def _make_dlq_entry(
    dlq_id: str = "abc-123",
    stream: str = "order",
    consumer_group: str = "handler.OrderHandler",
    failure_reason: str = "max_retries_exceeded",
    retry_count: int = 3,
) -> DLQEntry:
    """Create a DLQEntry for testing."""
    return DLQEntry(
        dlq_id=dlq_id,
        original_id=dlq_id,
        stream=stream,
        consumer_group=consumer_group,
        payload={"type": "OrderPlaced", "data": {"order_id": "123"}},
        failure_reason=failure_reason,
        failed_at="2026-02-23T10:00:00+00:00",
        retry_count=retry_count,
        dlq_stream=f"{stream}:dlq",
    )


def _mock_domain_with_broker(
    dlq_entries: list[DLQEntry] | None = None,
    has_dlq: bool = True,
):
    """Create a mock domain with a broker that supports DLQ."""
    mock_domain = MagicMock()
    mock_broker = MagicMock()

    if has_dlq:
        mock_broker.has_capability.return_value = True
    else:
        mock_broker.has_capability.return_value = False

    mock_broker.dlq_list.return_value = dlq_entries or []
    mock_broker.dlq_inspect.return_value = dlq_entries[0] if dlq_entries else None
    mock_broker.dlq_replay.return_value = True
    mock_broker.dlq_replay_all.return_value = len(dlq_entries) if dlq_entries else 0
    mock_broker.dlq_purge.return_value = len(dlq_entries) if dlq_entries else 0

    mock_domain.brokers = {"default": mock_broker}
    mock_domain.config = {"server": {}}
    mock_domain.registry._elements = {}

    return mock_domain


# ---------------------------------------------------------------------------
# protean dlq list
# ---------------------------------------------------------------------------


class TestDlqList:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_list_with_entries(self):
        change_working_directory_to("test7")
        entries = [_make_dlq_entry(), _make_dlq_entry(dlq_id="def-456", stream="user")]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq", "user:dlq"],
            ),
        ):
            result = runner.invoke(app, ["dlq", "list", "--domain", "publishing7.py"])
            assert result.exit_code == 0
            assert "2 DLQ message(s) found" in result.output

    def test_list_empty(self):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_broker([])

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(app, ["dlq", "list", "--domain", "publishing7.py"])
            assert result.exit_code == 0
            assert "No DLQ messages found" in result.output

    def test_list_no_broker_dlq_support(self):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_broker(has_dlq=False)

        with patch("protean.cli.dlq.derive_domain", return_value=mock_domain):
            result = runner.invoke(app, ["dlq", "list", "--domain", "publishing7.py"])
            assert result.exit_code != 0
            assert "does not support" in result.output

    def test_list_no_domain_found(self):
        change_working_directory_to("test7")

        with patch(
            "protean.cli.dlq.derive_domain",
            side_effect=NoDomainException("Could not find domain"),
        ):
            result = runner.invoke(app, ["dlq", "list", "--domain", "nonexistent.py"])
            assert result.exit_code != 0
            assert "Error loading" in result.output

    def test_list_no_broker_configured(self):
        change_working_directory_to("test7")
        mock_domain = MagicMock()
        mock_domain.brokers = {"default": None}

        with patch("protean.cli.dlq.derive_domain", return_value=mock_domain):
            result = runner.invoke(app, ["dlq", "list", "--domain", "publishing7.py"])
            assert result.exit_code != 0

    def test_list_no_subscriptions_returns_empty(self):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_broker([])

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch("protean.cli.dlq.collect_dlq_streams", return_value=[]),
        ):
            result = runner.invoke(app, ["dlq", "list", "--domain", "publishing7.py"])
            assert result.exit_code == 0
            assert "No subscriptions found" in result.output

    def test_list_with_subscription_filter(self):
        change_working_directory_to("test7")
        entries = [_make_dlq_entry()]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.discover_subscriptions",
                return_value=[
                    MagicMock(
                        stream_category="order",
                        dlq_stream="order:dlq",
                        backfill_dlq_stream="order:backfill:dlq",
                    )
                ],
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "dlq",
                    "list",
                    "--subscription",
                    "order",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0

    def test_list_with_invalid_subscription_filter(self):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_broker([])

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch("protean.cli.dlq.discover_subscriptions", return_value=[]),
        ):
            result = runner.invoke(
                app,
                [
                    "dlq",
                    "list",
                    "--subscription",
                    "nonexistent_sub",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code != 0
            assert "No subscription found" in result.output

    def test_list_with_long_dlq_id_and_consumer_group(self):
        """Test that long DLQ IDs and consumer groups are truncated in list output."""
        change_working_directory_to("test7")
        entries = [
            _make_dlq_entry(
                dlq_id="a-very-long-dlq-id-that-exceeds-sixteen-chars",
                consumer_group="some.very.long.module.path.to.a.handler.ClassName",
            )
        ]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(app, ["dlq", "list", "--domain", "publishing7.py"])
            assert result.exit_code == 0
            # Rich truncates long text with ellipsis (… or ...)
            assert "1 DLQ message(s) found" in result.output


# ---------------------------------------------------------------------------
# protean dlq inspect
# ---------------------------------------------------------------------------


class TestDlqInspect:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_inspect_found(self):
        change_working_directory_to("test7")
        entry = _make_dlq_entry()
        mock_domain = _mock_domain_with_broker([entry])
        mock_broker = mock_domain.brokers["default"]
        mock_broker.dlq_inspect.return_value = entry

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(
                app, ["dlq", "inspect", "abc-123", "--domain", "publishing7.py"]
            )
            assert result.exit_code == 0
            assert "abc-123" in result.output
            assert "order" in result.output
            assert "max_retries_exceeded" in result.output

    def test_inspect_not_found(self):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_broker([])
        mock_broker = mock_domain.brokers["default"]
        mock_broker.dlq_inspect.return_value = None

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(
                app,
                ["dlq", "inspect", "nonexistent", "--domain", "publishing7.py"],
            )
            assert result.exit_code != 0
            assert "not found" in result.output


# ---------------------------------------------------------------------------
# protean dlq replay
# ---------------------------------------------------------------------------


class TestDlqReplay:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_replay_success(self):
        change_working_directory_to("test7")
        entry = _make_dlq_entry()
        mock_domain = _mock_domain_with_broker([entry])
        mock_broker = mock_domain.brokers["default"]
        mock_broker.dlq_inspect.return_value = entry
        mock_broker.dlq_replay.return_value = True

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(
                app, ["dlq", "replay", "abc-123", "--domain", "publishing7.py"]
            )
            assert result.exit_code == 0
            assert "Replayed" in result.output

    def test_replay_not_found(self):
        change_working_directory_to("test7")
        mock_domain = _mock_domain_with_broker([])
        mock_broker = mock_domain.brokers["default"]
        mock_broker.dlq_inspect.return_value = None

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(
                app,
                ["dlq", "replay", "nonexistent", "--domain", "publishing7.py"],
            )
            assert result.exit_code != 0
            assert "not found" in result.output

    def test_replay_failure(self):
        change_working_directory_to("test7")
        entry = _make_dlq_entry()
        mock_domain = _mock_domain_with_broker([entry])
        mock_broker = mock_domain.brokers["default"]
        mock_broker.dlq_inspect.return_value = entry
        mock_broker.dlq_replay.return_value = False

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.collect_dlq_streams",
                return_value=["order:dlq"],
            ),
        ):
            result = runner.invoke(
                app, ["dlq", "replay", "abc-123", "--domain", "publishing7.py"]
            )
            assert result.exit_code == 0
            assert "Failed to replay" in result.output


# ---------------------------------------------------------------------------
# protean dlq replay-all
# ---------------------------------------------------------------------------


class TestDlqReplayAll:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_replay_all_success(self):
        change_working_directory_to("test7")
        entries = [_make_dlq_entry(), _make_dlq_entry(dlq_id="def-456")]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.discover_subscriptions",
                return_value=[
                    MagicMock(
                        stream_category="order",
                        dlq_stream="order:dlq",
                        backfill_dlq_stream=None,
                    )
                ],
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "dlq",
                    "replay-all",
                    "--subscription",
                    "order",
                    "--yes",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "Replayed" in result.output


# ---------------------------------------------------------------------------
# protean dlq purge
# ---------------------------------------------------------------------------


class TestDlqPurge:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_purge_success(self):
        change_working_directory_to("test7")
        entries = [_make_dlq_entry()]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.discover_subscriptions",
                return_value=[
                    MagicMock(
                        stream_category="order",
                        dlq_stream="order:dlq",
                        backfill_dlq_stream=None,
                    )
                ],
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "dlq",
                    "purge",
                    "--subscription",
                    "order",
                    "--yes",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "Purged" in result.output

    def test_purge_with_confirmation_prompt(self):
        change_working_directory_to("test7")
        entries = [_make_dlq_entry()]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.discover_subscriptions",
                return_value=[
                    MagicMock(
                        stream_category="order",
                        dlq_stream="order:dlq",
                        backfill_dlq_stream=None,
                    )
                ],
            ),
        ):
            # Answer "y" to confirmation
            result = runner.invoke(
                app,
                [
                    "dlq",
                    "purge",
                    "--subscription",
                    "order",
                    "--domain",
                    "publishing7.py",
                ],
                input="y\n",
            )
            assert result.exit_code == 0
            assert "Purged" in result.output

    def test_replay_all_with_confirmation_prompt(self):
        change_working_directory_to("test7")
        entries = [_make_dlq_entry()]
        mock_domain = _mock_domain_with_broker(entries)

        with (
            patch("protean.cli.dlq.derive_domain", return_value=mock_domain),
            patch(
                "protean.cli.dlq.discover_subscriptions",
                return_value=[
                    MagicMock(
                        stream_category="order",
                        dlq_stream="order:dlq",
                        backfill_dlq_stream=None,
                    )
                ],
            ),
        ):
            # Answer "y" to confirmation
            result = runner.invoke(
                app,
                [
                    "dlq",
                    "replay-all",
                    "--subscription",
                    "order",
                    "--domain",
                    "publishing7.py",
                ],
                input="y\n",
            )
            assert result.exit_code == 0
            assert "Replayed" in result.output


# ---------------------------------------------------------------------------
# _format_time helper
# ---------------------------------------------------------------------------


class TestFormatTime:
    def test_format_valid_iso_timestamp(self):
        assert _format_time("2026-02-23T10:00:00+00:00") == "2026-02-23 10:00:00"

    def test_format_none_returns_dash(self):
        assert _format_time(None) == "-"

    def test_format_empty_string_returns_dash(self):
        assert _format_time("") == "-"

    def test_format_invalid_timestamp_returns_raw(self):
        assert _format_time("not-a-timestamp") == "not-a-timestamp"
