"""Tests for CLI events commands (protean events ...)."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.events import (
    _data_keys_summary,
    _extract_trace_ids,
    _format_time,
    _truncate_id,
)
from protean.exceptions import NoDomainException
from tests.shared import change_working_directory_to

runner = CliRunner()


def _make_raw_event(
    position: int = 0,
    global_position: int = 0,
    event_type: str = "Test.UserRegistered.v1",
    stream_name: str = "test::user-abc123",
    data: dict | None = None,
) -> dict:
    """Create a raw event dict matching the format returned by `_read()`."""
    return {
        "data": data or {"name": "John", "email": "john@example.com"},
        "type": event_type,
        "stream_name": stream_name,
        "position": position,
        "global_position": global_position,
        "id": f"evt-{global_position}",
        "time": "2026-02-22T10:00:00",
    }


def _mock_domain_with_store(
    read_return: list | None = None,
    read_last_return: dict | None = None,
    identifiers_return: list | None = None,
    aggregates: dict | None = None,
) -> MagicMock:
    """Create a MagicMock domain with an event store configured."""
    mock_domain = MagicMock()
    mock_store = MagicMock()
    mock_domain.event_store.store = mock_store

    mock_store._read.return_value = read_return or []
    mock_store._read_last_message.return_value = read_last_return
    mock_store._stream_identifiers.return_value = identifiers_return or []

    if aggregates is not None:
        mock_domain.registry._elements = {"AGGREGATE": aggregates}
    else:
        mock_domain.registry._elements = {"AGGREGATE": {}}

    return mock_domain


def _make_aggregate_record(
    name: str, stream_category: str = "", is_event_sourced: bool = True
) -> MagicMock:
    """Create a mock aggregate registry record."""
    record = MagicMock()
    record.cls.__name__ = name
    record.cls.meta_.stream_category = stream_category or f"test::{name.lower()}"
    record.cls.meta_.is_event_sourced = is_event_sourced
    return record


# ---------------------------------------------------------------------------
# protean events read
# ---------------------------------------------------------------------------


class TestEventsRead:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_read_stream_with_events(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event(0, 1),
            _make_raw_event(1, 3, event_type="Test.UserEmailChanged.v1"),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "read", "test::user-abc123", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            # Rich may truncate long type names in the table, so check for
            # the summary line and key data instead of full type strings.
            assert "Showing 2 event(s) from position 0" in result.output
            assert "name, email" in result.output

    def test_read_empty_stream(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_with_store(read_return=[])

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "read", "test::user-abc123", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "No events found in stream 'test::user-abc123'" in result.output

    def test_read_with_from_offset(self):
        change_working_directory_to("test7")

        events = [_make_raw_event(5, 10)]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "read",
                    "test::user-abc123",
                    "--domain",
                    "publishing7.py",
                    "--from",
                    "5",
                ],
            )
            assert result.exit_code == 0
            mock_domain.event_store.store._read.assert_called_once_with(
                "test::user-abc123", position=5, no_of_messages=20
            )

    def test_read_with_limit(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_with_store(read_return=[_make_raw_event()])

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "read",
                    "test::user-abc123",
                    "--domain",
                    "publishing7.py",
                    "--limit",
                    "5",
                ],
            )
            assert result.exit_code == 0
            mock_domain.event_store.store._read.assert_called_once_with(
                "test::user-abc123", position=0, no_of_messages=5
            )

    def test_read_with_data_flag(self):
        change_working_directory_to("test7")

        events = [_make_raw_event(data={"email": "test@example.com"})]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "read",
                    "test::user-abc123",
                    "--domain",
                    "publishing7.py",
                    "--data",
                ],
            )
            assert result.exit_code == 0
            assert "test@example.com" in result.output

    def test_read_invalid_domain(self):
        with patch(
            "protean.cli.events.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app, ["events", "read", "some-stream", "--domain", "invalid.py"]
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


# ---------------------------------------------------------------------------
# protean events stats
# ---------------------------------------------------------------------------


class TestEventsStats:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_stats_with_aggregates(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        order_record = _make_aggregate_record(
            "Order", "test::order", is_event_sourced=False
        )

        aggregates = {
            "test.User": user_record,
            "test.Order": order_record,
        }

        events_user = [
            _make_raw_event(0, 1, stream_name="test::user-id1"),
            _make_raw_event(1, 2, stream_name="test::user-id1"),
            _make_raw_event(0, 3, stream_name="test::user-id2"),
        ]

        mock_domain = _mock_domain_with_store(aggregates=aggregates)
        store = mock_domain.event_store.store

        def side_effect_read(stream, **kwargs):
            if stream == "test::user":
                return events_user
            return []

        store._read.side_effect = side_effect_read

        def side_effect_identifiers(stream_category):
            if stream_category == "test::user":
                return ["id1", "id2"]
            return []

        store._stream_identifiers.side_effect = side_effect_identifiers

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "stats", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "User" in result.output
            assert "Order" in result.output
            assert "Yes" in result.output  # User is ES
            assert "No" in result.output  # Order is not ES
            assert "Total:" in result.output

    def test_stats_no_aggregates(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_with_store(aggregates={})

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "stats", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "No aggregates registered in domain" in result.output

    def test_stats_empty_event_store(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}

        mock_domain = _mock_domain_with_store(
            read_return=[],
            identifiers_return=[],
            aggregates=aggregates,
        )

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "stats", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "User" in result.output
            assert "Total: 0 event(s) across 0 aggregate instance(s)" in result.output

    def test_stats_invalid_domain(self):
        with patch(
            "protean.cli.events.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(app, ["events", "stats", "--domain", "invalid.py"])
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


# ---------------------------------------------------------------------------
# protean events search
# ---------------------------------------------------------------------------


class TestEventsSearch:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_search_by_exact_type(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event(0, 1, event_type="Test.UserRegistered.v1"),
            _make_raw_event(1, 2, event_type="Test.OrderPlaced.v1"),
            _make_raw_event(2, 3, event_type="Test.UserRegistered.v1"),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "Test.UserRegistered.v1",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert (
                "Found 2 event(s) matching type 'Test.UserRegistered.v1'"
                in result.output
            )

    def test_search_by_partial_type(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event(0, 1, event_type="Test.UserRegistered.v1"),
            _make_raw_event(1, 2, event_type="Test.OrderPlaced.v1"),
            _make_raw_event(2, 3, event_type="Test.UserEmailChanged.v1"),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "User",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            # Should match both User events (partial, case-insensitive)
            assert "Found 2 event(s) matching type 'User'" in result.output

    def test_search_with_category_filter(self):
        change_working_directory_to("test7")

        events = [_make_raw_event(0, 1)]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "UserRegistered",
                    "--domain",
                    "publishing7.py",
                    "--category",
                    "test::user",
                ],
            )
            assert result.exit_code == 0
            mock_domain.event_store.store._read.assert_called_once_with(
                "test::user", no_of_messages=1_000_000
            )

    def test_search_no_results(self):
        change_working_directory_to("test7")

        events = [_make_raw_event(0, 1, event_type="Test.OrderPlaced.v1")]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "UserRegistered",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "No events found matching type 'UserRegistered'" in result.output

    def test_search_with_limit(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event(i, i, event_type="Test.UserRegistered.v1")
            for i in range(10)
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "UserRegistered",
                    "--domain",
                    "publishing7.py",
                    "--limit",
                    "3",
                ],
            )
            assert result.exit_code == 0
            assert "Found 10 event(s)" in result.output
            assert "showing first 3" in result.output

    def test_search_invalid_domain(self):
        with patch(
            "protean.cli.events.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app,
                ["events", "search", "--type", "Foo", "--domain", "invalid.py"],
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


# ---------------------------------------------------------------------------
# protean events history
# ---------------------------------------------------------------------------


class TestEventsHistory:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_history_with_events(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}
        events = [
            _make_raw_event(0, 1, event_type="Test.UserRegistered.v1"),
            _make_raw_event(1, 3, event_type="Test.UserEmailChanged.v1"),
        ]

        mock_domain = _mock_domain_with_store(
            read_return=events,
            aggregates=aggregates,
        )
        # _read_last_message for snapshot check returns None
        mock_domain.event_store.store._read_last_message.return_value = None

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "abc123",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "UserRegistered" in result.output
            assert "UserEmailChanged" in result.output
            assert "2 event(s), current version: 1" in result.output

    def test_history_no_events(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}

        mock_domain = _mock_domain_with_store(
            read_return=[],
            aggregates=aggregates,
        )

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "nonexistent",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert (
                "No events found for User with identifier 'nonexistent'"
                in result.output
            )

    def test_history_with_snapshot(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}
        events = [
            _make_raw_event(0, 1, event_type="Test.UserRegistered.v1"),
            _make_raw_event(1, 3, event_type="Test.UserEmailChanged.v1"),
        ]
        snapshot = {"data": {"_version": 1, "name": "John"}, "type": "SNAPSHOT"}

        mock_domain = _mock_domain_with_store(
            read_return=events,
            read_last_return=snapshot,
            aggregates=aggregates,
        )

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "abc123",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "Snapshot exists at version 1" in result.output

    def test_history_aggregate_not_found(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_with_store(aggregates={})

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "NonExistent",
                    "--id",
                    "abc123",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code != 0
            assert "Aggregate 'NonExistent' not found" in result.output

    def test_history_with_data_flag(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}
        events = [
            _make_raw_event(
                0,
                1,
                data={"email": "john@example.com", "name": "John"},
            )
        ]

        mock_domain = _mock_domain_with_store(
            read_return=events,
            aggregates=aggregates,
        )
        mock_domain.event_store.store._read_last_message.return_value = None

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "abc123",
                    "--domain",
                    "publishing7.py",
                    "--data",
                ],
            )
            assert result.exit_code == 0
            assert "john@example.com" in result.output

    def test_history_invalid_domain(self):
        with patch(
            "protean.cli.events.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "abc123",
                    "--domain",
                    "invalid.py",
                ],
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestFormatTime:
    def test_none_returns_dash(self):
        assert _format_time(None) == "-"

    def test_datetime_object(self):
        dt = datetime(2026, 2, 22, 10, 30, 0, tzinfo=timezone.utc)
        assert _format_time(dt) == "2026-02-22 10:30:00"

    def test_iso_string(self):
        assert _format_time("2026-02-22T10:30:00") == "2026-02-22 10:30:00"

    def test_invalid_string_returned_as_is(self):
        assert _format_time("not-a-date") == "not-a-date"

    def test_other_type_returns_str(self):
        assert _format_time(12345) == "12345"


class TestDataKeysSummary:
    def test_none_returns_dash(self):
        assert _data_keys_summary(None) == "-"

    def test_empty_dict_returns_dash(self):
        assert _data_keys_summary({}) == "-"

    def test_few_keys(self):
        assert _data_keys_summary({"a": 1, "b": 2}) == "a, b"

    def test_more_than_five_keys(self):
        data = {f"key{i}": i for i in range(8)}
        result = _data_keys_summary(data)
        assert "(+3 more)" in result


# ---------------------------------------------------------------------------
# Stats exception handling
# ---------------------------------------------------------------------------


class TestEventsStatsExceptions:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_stats_handles_stream_identifiers_exception(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}

        mock_domain = _mock_domain_with_store(aggregates=aggregates)
        store = mock_domain.event_store.store
        store._stream_identifiers.side_effect = Exception("Connection error")
        store._read.return_value = [_make_raw_event(0, 1)]

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "stats", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "User" in result.output

    def test_stats_handles_read_exception(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}

        mock_domain = _mock_domain_with_store(aggregates=aggregates)
        store = mock_domain.event_store.store
        store._stream_identifiers.return_value = ["id1"]
        store._read.side_effect = Exception("Connection error")

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                ["events", "stats", "--domain", "publishing7.py"],
            )
            assert result.exit_code == 0
            assert "User" in result.output


# ---------------------------------------------------------------------------
# Search with --data flag
# ---------------------------------------------------------------------------


class TestEventsSearchData:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_search_with_data_flag(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event(0, 1, data={"email": "test@example.com"}),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "UserRegistered",
                    "--domain",
                    "publishing7.py",
                    "--data",
                ],
            )
            assert result.exit_code == 0
            assert "test@example.com" in result.output


# ---------------------------------------------------------------------------
# Helper: raw event with trace metadata
# ---------------------------------------------------------------------------


def _make_raw_event_with_trace(
    position: int = 0,
    global_position: int = 0,
    event_type: str = "Test.UserRegistered.v1",
    stream_name: str = "test::user-abc123",
    data: dict | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict:
    """Create a raw event dict with trace metadata populated."""
    event = _make_raw_event(
        position=position,
        global_position=global_position,
        event_type=event_type,
        stream_name=stream_name,
        data=data,
    )
    event["metadata"] = {
        "domain": {
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "kind": "EVENT",
            "fqn": f"tests.{event_type}",
        }
    }
    return event


# ---------------------------------------------------------------------------
# Helper unit tests: _extract_trace_ids, _truncate_id
# ---------------------------------------------------------------------------


class TestExtractTraceIds:
    def test_with_valid_metadata(self):
        msg = _make_raw_event_with_trace(
            correlation_id="corr-abc", causation_id="cause-xyz"
        )
        corr, cause = _extract_trace_ids(msg)
        assert corr == "corr-abc"
        assert cause == "cause-xyz"

    def test_with_none_values(self):
        msg = _make_raw_event_with_trace(correlation_id=None, causation_id=None)
        corr, cause = _extract_trace_ids(msg)
        assert corr == ""
        assert cause == ""

    def test_with_no_metadata_key(self):
        msg = _make_raw_event()
        # _make_raw_event doesn't add metadata key
        corr, cause = _extract_trace_ids(msg)
        assert corr == ""
        assert cause == ""

    def test_with_metadata_not_dict(self):
        msg = _make_raw_event()
        msg["metadata"] = "not-a-dict"
        corr, cause = _extract_trace_ids(msg)
        assert corr == ""
        assert cause == ""

    def test_with_no_domain_in_metadata(self):
        msg = _make_raw_event()
        msg["metadata"] = {"headers": {"id": "test"}}
        corr, cause = _extract_trace_ids(msg)
        assert corr == ""
        assert cause == ""

    def test_with_domain_not_dict(self):
        msg = _make_raw_event()
        msg["metadata"] = {"domain": "not-a-dict"}
        corr, cause = _extract_trace_ids(msg)
        assert corr == ""
        assert cause == ""


class TestTruncateId:
    def test_short_id_not_truncated(self):
        assert _truncate_id("abc") == "abc"

    def test_exact_length_not_truncated(self):
        assert _truncate_id("12345678") == "12345678"

    def test_long_id_truncated(self):
        assert _truncate_id("abcdefghijklmnop") == "abcdefgh..."

    def test_custom_length(self):
        assert _truncate_id("abcdefghij", length=4) == "abcd..."

    def test_empty_string(self):
        assert _truncate_id("") == ""


# ---------------------------------------------------------------------------
# protean events read --trace
# ---------------------------------------------------------------------------


class TestEventsReadTrace:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_read_with_trace_flag(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event_with_trace(
                0, 1, correlation_id="corr-111", causation_id="cause-222"
            ),
            _make_raw_event_with_trace(
                1,
                3,
                event_type="Test.UserEmailChanged.v1",
                correlation_id="corr-111",
                causation_id="cause-333",
            ),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "read",
                    "test::user-abc123",
                    "--domain",
                    "publishing7.py",
                    "--trace",
                ],
            )
            assert result.exit_code == 0
            # Rich may truncate column headers; check for partial match
            assert "Correlat" in result.output
            assert "Causat" in result.output
            assert "corr-111" in result.output

    def test_read_without_trace_flag_no_trace_columns(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event_with_trace(
                0, 1, correlation_id="corr-111", causation_id="cause-222"
            )
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "read",
                    "test::user-abc123",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "Correlation ID" not in result.output
            assert "Causation ID" not in result.output


# ---------------------------------------------------------------------------
# protean events search --trace
# ---------------------------------------------------------------------------


class TestEventsSearchTrace:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_search_with_trace_flag(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event_with_trace(
                0, 1, correlation_id="search-corr", causation_id="search-cause"
            ),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "search",
                    "--type",
                    "UserRegistered",
                    "--domain",
                    "publishing7.py",
                    "--trace",
                ],
            )
            assert result.exit_code == 0
            # Rich may truncate column headers; check for partial match
            assert "Correlat" in result.output or "Correl" in result.output
            assert "Causat" in result.output or "Causa" in result.output


# ---------------------------------------------------------------------------
# protean events history --trace
# ---------------------------------------------------------------------------


class TestEventsHistoryTrace:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_history_with_trace_flag(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}
        events = [
            _make_raw_event_with_trace(
                0,
                1,
                event_type="Test.UserRegistered.v1",
                correlation_id="hist-corr-123",
                causation_id="hist-cause-456",
            ),
            _make_raw_event_with_trace(
                1,
                3,
                event_type="Test.UserEmailChanged.v1",
                correlation_id="hist-corr-123",
                causation_id="hist-cause-789",
            ),
        ]

        mock_domain = _mock_domain_with_store(
            read_return=events,
            aggregates=aggregates,
        )
        mock_domain.event_store.store._read_last_message.return_value = None

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "abc123",
                    "--domain",
                    "publishing7.py",
                    "--trace",
                ],
            )
            assert result.exit_code == 0
            # Rich may truncate column headers; check for partial match
            assert "Correlation" in result.output or "Correlat" in result.output
            assert "Causation" in result.output or "Causat" in result.output
            assert "hist-cor" in result.output

    def test_history_without_trace_flag_no_trace_columns(self):
        change_working_directory_to("test7")

        user_record = _make_aggregate_record("User", "test::user")
        aggregates = {"test.User": user_record}
        events = [
            _make_raw_event_with_trace(
                0,
                1,
                event_type="Test.UserRegistered.v1",
                correlation_id="hist-corr-123",
                causation_id="hist-cause-456",
            ),
        ]

        mock_domain = _mock_domain_with_store(
            read_return=events,
            aggregates=aggregates,
        )
        mock_domain.event_store.store._read_last_message.return_value = None

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "history",
                    "--aggregate",
                    "User",
                    "--id",
                    "abc123",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "Correlation ID" not in result.output
            assert "Causation ID" not in result.output


# ---------------------------------------------------------------------------
# protean events trace
# ---------------------------------------------------------------------------


class TestEventsTrace:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_trace_finds_matching_events(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event_with_trace(
                0,
                1,
                event_type="Test.PlaceOrder.v1",
                stream_name="test::order:command-abc123",
                correlation_id="trace-corr-abc",
                causation_id=None,
            ),
            _make_raw_event_with_trace(
                0,
                2,
                event_type="Test.OrderPlaced.v1",
                stream_name="test::order-abc123",
                correlation_id="trace-corr-abc",
                causation_id="test::order:command-abc123-0",
            ),
            _make_raw_event_with_trace(
                0,
                3,
                event_type="Test.UserRegistered.v1",
                stream_name="test::user-xyz",
                correlation_id="other-corr-id",
                causation_id=None,
            ),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "trace",
                    "trace-corr-abc",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert (
                "Found 2 event(s) for correlation ID 'trace-corr-abc'" in result.output
            )

    def test_trace_no_matching_events(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event_with_trace(
                0, 1, correlation_id="other-corr", causation_id=None
            ),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "trace",
                    "nonexistent-corr-id",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert (
                "No events found for correlation ID 'nonexistent-corr-id'"
                in result.output
            )

    def test_trace_with_data_flag(self):
        change_working_directory_to("test7")

        events = [
            _make_raw_event_with_trace(
                0,
                1,
                correlation_id="trace-data-corr",
                causation_id=None,
                data={"customer": "Alice", "amount": 100.0},
            ),
        ]
        mock_domain = _mock_domain_with_store(read_return=events)

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "trace",
                    "trace-data-corr",
                    "--domain",
                    "publishing7.py",
                    "--data",
                ],
            )
            assert result.exit_code == 0
            assert "Alice" in result.output
            assert "100.0" in result.output

    def test_trace_with_empty_event_store(self):
        change_working_directory_to("test7")

        mock_domain = _mock_domain_with_store(read_return=[])

        with patch("protean.cli.events.derive_domain", return_value=mock_domain):
            result = runner.invoke(
                app,
                [
                    "events",
                    "trace",
                    "any-corr-id",
                    "--domain",
                    "publishing7.py",
                ],
            )
            assert result.exit_code == 0
            assert "No events found for correlation ID 'any-corr-id'" in result.output

    def test_trace_invalid_domain(self):
        with patch(
            "protean.cli.events.derive_domain",
            side_effect=NoDomainException("Not found"),
        ):
            result = runner.invoke(
                app,
                ["events", "trace", "any-corr-id", "--domain", "invalid.py"],
            )
            assert result.exit_code != 0
            assert "Error loading Protean domain" in result.output
