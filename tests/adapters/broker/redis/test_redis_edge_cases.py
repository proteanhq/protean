"""Tests for Redis broker edge cases and error scenarios."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
import redis

from protean.adapters.broker.redis import (
    _PUBLISHED_STREAMS_LIMIT,
    RedisBroker,
    get_field_value,
)
from tests.shared import REDIS_URI


@pytest.mark.redis
class TestRedisEdgeCases:
    """Test edge cases and error scenarios for Redis broker."""

    def test_read_new_messages_handle_redis_error_other_than_nogroup(self, test_domain):
        """Test _read_new_messages handling of non-NOGROUP Redis errors."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance to raise a non-NOGROUP error
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = redis.ResponseError(
            "WRONGTYPE Operation against a key holding the wrong kind of value"
        )
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        result = broker._read_new_messages("test-stream", "test-group", 1)

        # Should return no messages and not retry
        assert result == []
        # Should have been called only once (no retry)
        mock_redis.xreadgroup.assert_called_once()

    def test_read_new_messages_response_with_empty_inner_messages(self, test_domain):
        """Test _read_new_messages when response has empty inner messages."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance to return response with empty messages
        mock_redis = MagicMock()
        # Response format: [(stream_name, [])]  - empty messages list
        mock_redis.xreadgroup.return_value = [("test-stream", [])]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        result = broker._read_new_messages("test-stream", "test-group", 1)

        # Should return no messages when messages list is empty
        assert result == []

    def test_read_with_fields_none(self, test_domain):
        """Test read when response contains None fields."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        # Response with some messages having None fields
        mock_redis.xreadgroup.side_effect = [
            # First call for new messages
            [
                (
                    b"test-stream",
                    [
                        (b"1-0", {b"data": json.dumps({"test": "data1"}).encode()}),
                        (b"1-1", None),  # None fields - should be skipped
                        (b"1-2", {b"data": json.dumps({"test": "data2"}).encode()}),
                    ],
                )
            ],
            # Second call for pending messages (won't be reached)
            [],
        ]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker.read("test-stream", "test-group", 3)

        # Should only return messages with valid fields
        assert len(messages) == 2
        assert messages[0][1]["test"] == "data1"
        assert messages[1][1]["test"] == "data2"

    def test_read_pending_with_none_fields(self, test_domain):
        """Test read with pending messages having None fields."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = [
            # First call for new messages - returns 1 message
            [
                (
                    b"test-stream",
                    [(b"1-0", {b"data": json.dumps({"test": "data1"}).encode()})],
                )
            ],
            # Second call for pending messages - some with None fields
            [
                (
                    b"test-stream",
                    [
                        (b"0-1", None),  # None fields - should be skipped
                        (b"0-2", {b"data": json.dumps({"test": "data2"}).encode()}),
                        (b"0-3", None),  # Another None
                    ],
                )
            ],
        ]
        # The older pending entries the read takes after the new ones.
        mock_redis.xpending_range.return_value = [
            {"message_id": b"0-1"},
            {"message_id": b"0-2"},
        ]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker.read("test-stream", "test-group", 3)

        # Should return 2 valid messages (1 new + 1 pending)
        assert len(messages) == 2
        assert messages[0][1]["test"] == "data1"
        assert messages[1][1]["test"] == "data2"

    def test_read_respects_message_limit(self, test_domain):
        """Test read stops when reaching message limit."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = [
            # First call returns 2 messages
            [
                (
                    b"test-stream",
                    [
                        (b"1-0", {b"data": json.dumps({"test": "data1"}).encode()}),
                        (b"1-1", {b"data": json.dumps({"test": "data2"}).encode()}),
                    ],
                )
            ],
            # Second call would return more but should stop at limit
            [
                (
                    b"test-stream",
                    [
                        (b"0-1", {b"data": json.dumps({"test": "data3"}).encode()}),
                        (b"0-2", {b"data": json.dumps({"test": "data4"}).encode()}),
                        (b"0-3", {b"data": json.dumps({"test": "data5"}).encode()}),
                    ],
                )
            ],
        ]
        # The older pending entries the read takes after the new ones.
        mock_redis.xpending_range.return_value = [{"message_id": b"0-1"}]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        # Request only 3 messages
        messages = broker.read("test-stream", "test-group", 3)

        # Should return exactly 3 messages and stop
        assert len(messages) == 3
        assert messages[0][1]["test"] == "data1"
        assert messages[1][1]["test"] == "data2"
        assert messages[2][1]["test"] == "data3"

    def test_read_avoids_duplicates(self, test_domain):
        """Test read avoids duplicate message IDs."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = [
            # First call returns 2 messages
            [
                (
                    b"test-stream",
                    [
                        (b"1-0", {b"data": json.dumps({"test": "data1"}).encode()}),
                        (b"1-1", {b"data": json.dumps({"test": "data2"}).encode()}),
                    ],
                )
            ],
            # Second call includes a duplicate ID
            [
                (
                    b"test-stream",
                    [
                        (
                            b"1-1",
                            {b"data": json.dumps({"test": "duplicate"}).encode()},
                        ),  # Duplicate ID
                        (b"1-2", {b"data": json.dumps({"test": "data3"}).encode()}),
                    ],
                )
            ],
        ]
        # The older pending entries the read takes after the new ones.
        mock_redis.xpending_range.return_value = [
            {"message_id": b"0-1"},
            {"message_id": b"0-2"},
        ]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker.read("test-stream", "test-group", 4)

        # Should return 3 unique messages (duplicate skipped)
        assert len(messages) == 3
        message_ids = [msg[0] for msg in messages]
        assert message_ids == ["1-0", "1-1", "1-2"]
        # Verify the duplicate was skipped (data2, not duplicate)
        assert messages[1][1]["test"] == "data2"

    def test_read_blocking_with_pending_messages(self, test_domain):
        """Test _read_blocking returns pending messages first."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        # First call for pending messages returns data
        mock_redis.xreadgroup.side_effect = [
            # Pending messages response
            [
                (
                    b"test-stream",
                    [
                        (b"0-1", {b"data": json.dumps({"test": "pending1"}).encode()}),
                        (b"0-2", {b"data": json.dumps({"test": "pending2"}).encode()}),
                    ],
                )
            ],
            # This shouldn't be called since we have pending messages
        ]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker._read_blocking(
            "test-stream", "test-group", "consumer1", timeout_ms=1000, count=2
        )

        # Should return pending messages without calling for new messages
        assert len(messages) == 2
        assert messages[0][1]["test"] == "pending1"
        assert messages[1][1]["test"] == "pending2"
        # Should only call xreadgroup once (for pending messages)
        assert mock_redis.xreadgroup.call_count == 1

    def test_read_blocking_pending_with_none_fields(self, test_domain):
        """Test _read_blocking skips pending messages with None fields."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = [
            # Pending messages with some None fields
            [
                (
                    b"test-stream",
                    [
                        (b"0-1", None),  # None fields - should be skipped
                        (b"0-2", {b"data": json.dumps({"test": "pending1"}).encode()}),
                        (b"0-3", None),  # Another None
                        (b"0-4", {b"data": json.dumps({"test": "pending2"}).encode()}),
                    ],
                )
            ],
        ]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker._read_blocking(
            "test-stream", "test-group", "consumer1", timeout_ms=1000, count=4
        )

        # Should return only valid messages
        assert len(messages) == 2
        assert messages[0][1]["test"] == "pending1"
        assert messages[1][1]["test"] == "pending2"

    def test_read_blocking_nogroup_error(self, test_domain, caplog):
        """Test _read_blocking handling NOGROUP error."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        call_count = [0]

        def xreadgroup_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                # First two calls raise NOGROUP error (pending check and new messages check)
                raise redis.ResponseError("NOGROUP No such consumer group")
            else:
                # After group creation, return empty
                return []

        mock_redis.xreadgroup.side_effect = xreadgroup_side_effect
        mock_redis.xgroup_create.return_value = True
        broker.redis_instance = mock_redis

        with caplog.at_level(logging.DEBUG):
            messages = broker._read_blocking(
                "test-stream", "test-group", "consumer1", timeout_ms=100, count=1
            )

        # Should retry after creating group
        assert messages == []
        # _read_blocking flow:
        # 1. create_group at top of method → xgroup_create #1
        # 2. xreadgroup #1 (pending check) → raises NOGROUP
        # 3. NOGROUP handler: discard + create_group → xgroup_create #2
        # 4. xreadgroup #2 (retry) → raises NOGROUP again, caught by inner handler
        assert call_count[0] == 2
        assert mock_redis.xgroup_create.call_count == 2

    def test_read_blocking_other_response_error(self, test_domain, caplog):
        """Test _read_blocking handling non-NOGROUP ResponseError."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = redis.ResponseError(
            "WRONGTYPE Operation against wrong key type"
        )
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        with caplog.at_level(logging.ERROR):
            messages = broker._read_blocking(
                "test-stream", "test-group", "consumer1", timeout_ms=100, count=1
            )

        # Should return empty and log error
        assert messages == []
        assert "broker.redis.read_blocking_failed" in caplog.text

    def test_read_blocking_unexpected_error(self, test_domain, caplog):
        """Test _read_blocking handling unexpected exceptions."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = ValueError("Unexpected error")
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        with caplog.at_level(logging.ERROR):
            messages = broker._read_blocking(
                "test-stream", "test-group", "consumer1", timeout_ms=100, count=1
            )

        # Should return empty and log error
        assert messages == []
        assert "broker.redis.read_blocking_failed" in caplog.text

    def test_create_group_existing_group_tracking(self, test_domain):
        """Test create_group tracks creation time for existing groups."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        # Simulate BUSYGROUP error (group already exists)
        mock_redis.xgroup_create.side_effect = redis.ResponseError(
            "BUSYGROUP Consumer Group name already exists"
        )
        broker.redis_instance = mock_redis

        # Ensure group hasn't been tracked yet
        assert "test-group" not in broker._group_creation_times

        # Call create_group
        broker.create_group("test-stream", "test-group")

        # Should track the creation time even for existing group
        assert "test-group" in broker._group_creation_times
        assert broker._group_creation_times["test-group"] > 0
        assert "test-stream:test-group" in broker._created_groups_set

    def test_get_streams_to_check_with_no_separator(self, test_domain):
        """Test _get_streams_to_check skips entries without separator."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Add some entries to _created_groups, including invalid ones
        broker._created_groups_set.add("test-stream:test-group")  # Valid
        broker._created_groups_set.add("another-stream:another-group")  # Valid
        broker._created_groups_set.add(
            "invalid-entry"
        )  # No separator - should be skipped
        broker._created_groups_set.add(
            "also-invalid"
        )  # No separator - should be skipped

        streams = broker._get_streams_to_check()

        # Should only include valid streams
        assert "test-stream" in streams
        assert "another-stream" in streams
        assert "invalid-entry" not in streams
        assert "also-invalid" not in streams

    def test_get_streams_to_check_includes_published_streams(self, test_domain):
        """A stream published to but never read is checked for health."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
        broker.clear()

        broker.publish("published-only-stream", {"n": 1})

        assert broker._get_streams_to_check() == {"published-only-stream"}

        broker.clear()
        assert broker._get_streams_to_check() == set()

    def test_published_streams_keep_only_the_most_recent(self, test_domain):
        """The record keeps the last ``_PUBLISHED_STREAMS_LIMIT`` streams, so
        publishing to one stream per partition key does not grow it."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
        broker.clear()

        for index in range(_PUBLISHED_STREAMS_LIMIT + 2):
            broker._record_published_stream(f"order:key-{index}")
        # Publishing again moves a stream to the newest end
        broker._record_published_stream("order:key-2")
        broker._record_published_stream("order:new")

        streams = broker._get_streams_to_check()
        assert len(streams) == _PUBLISHED_STREAMS_LIMIT
        assert "order:key-2" in streams
        assert "order:new" in streams
        assert {"order:key-0", "order:key-1", "order:key-3"}.isdisjoint(streams)

        broker.clear()

    def test_extract_group_data_non_dict(self, test_domain):
        """Test _extract_group_data skips non-dict entries."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance
        mock_redis = MagicMock()
        # Return mixed types in groups info
        mock_redis.xinfo_groups.return_value = [
            {
                "name": b"group1",
                "pending": 5,
                "last-delivered-id": b"1-0",
            },  # Valid dict
            "not-a-dict",  # String - should be skipped
            None,  # None - should be skipped
            {
                "name": b"group2",
                "pending": 3,
                "last-delivered-id": b"2-0",
            },  # Another valid dict
        ]
        mock_redis.xinfo_consumers.return_value = []
        broker.redis_instance = mock_redis

        stream_info = broker._get_stream_info("test-stream")

        # Should only process dict entries
        assert stream_info is not None
        assert "group1" in stream_info
        assert "group2" in stream_info
        assert len(stream_info) == 2

    def test_get_field_value_conversion_failure(self, caplog):
        """Test get_field_value when int conversion fails."""
        # Test with non-numeric value
        info_dict = {"pending": "not-a-number"}

        with caplog.at_level(logging.WARNING):
            result = get_field_value(info_dict, "pending", convert_to_int=True)

        # Should return 0 and log warning
        assert result == 0
        assert "Failed to convert not-a-number to int" in caplog.text

    def test_calculate_message_counts_skips_keys_that_are_not_streams(
        self, test_domain
    ):
        """A missing key or a key of another type is not counted."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        mock_redis = MagicMock()
        types = {"stream-a": b"stream", "missing": b"none", "a-string": b"string"}
        mock_redis.type.side_effect = types.__getitem__
        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.return_value = [{"pending": 3}]
        broker.redis_instance = mock_redis

        for key in types:
            broker._created_groups_set.add(f"{key}:test-group")

        counts = broker._calculate_message_counts()

        assert counts["total_messages"] == 100
        assert counts["in_flight"] == 3
        mock_redis.xlen.assert_called_once_with("stream-a")
        mock_redis.xinfo_groups.assert_called_once_with("stream-a")

    def test_calculate_message_counts_logs_a_redis_error(self, test_domain, caplog):
        """A Redis error on a real stream is logged, not skipped."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        mock_redis = MagicMock()
        mock_redis.type.return_value = b"stream"
        mock_redis.xlen.return_value = 100
        mock_redis.xinfo_groups.side_effect = redis.ResponseError("NOPERM denied")
        broker.redis_instance = mock_redis
        broker._created_groups_set.add("test-stream:test-group")

        with caplog.at_level(logging.DEBUG, logger="protean.adapters.broker.redis"):
            counts = broker._calculate_message_counts()

        assert counts == {"total_messages": 0, "in_flight": 0, "failed": 0, "dlq": 0}
        assert "Error calculating message counts: NOPERM denied" in caplog.text

    def test_calculate_streams_info_stream_doesnt_exist(self, test_domain):
        """Test _calculate_streams_info leaves out streams that do not exist."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # TYPE answers "none" for a missing key
        mock_redis = MagicMock()
        types = {
            "existing-stream": b"stream",
            "non-existing-stream": b"none",
            "another-missing": b"none",
        }
        mock_redis.type.side_effect = types.__getitem__
        broker.redis_instance = mock_redis

        for key in types:
            broker._created_groups_set.add(f"{key}:test-group")

        streams_info = broker._calculate_streams_info()

        # Should only include existing stream
        assert streams_info["count"] == 1
        assert "existing-stream" in streams_info["names"]
        assert "non-existing-stream" not in streams_info["names"]
        assert "another-missing" not in streams_info["names"]

    def test_calculate_consumer_groups_info_no_separator(self, test_domain):
        """Test _calculate_consumer_groups_info skips entries without separator."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Add entries to _created_groups
        broker._created_groups_set.add("stream1:group1")  # Valid
        broker._created_groups_set.add("stream2:group2")  # Valid
        broker._created_groups_set.add("invalid-no-separator")  # Should be skipped
        broker._created_groups_set.add("stream3:group1")  # Same group name as first

        groups_info = broker._calculate_consumer_groups_info()

        # Should have 2 unique group names (group1 and group2)
        assert groups_info["count"] == 2
        assert "group1" in groups_info["names"]
        assert "group2" in groups_info["names"]
        assert len(groups_info["names"]) == 2

    def test_reconnect_failure(self, test_domain, caplog):
        """Test reconnect when reconnection fails."""
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        # Mock redis instance that always fails ping
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = redis.ConnectionError("Connection refused")
        broker.redis_instance = mock_redis

        # Mock Redis.from_url to also fail
        with (
            patch(
                "redis.Redis.from_url",
                side_effect=Exception("Cannot create connection"),
            ),
            caplog.at_level(logging.ERROR),
        ):
            result = broker.reconnect()

        # Should return False and log errors
        assert result is False
        assert "broker.redis.reconnect_failed" in caplog.text
        assert "Cannot create connection" in caplog.text
        assert "broker.redis.connection_exhausted" in caplog.text


@pytest.mark.redis
def test_read_blocking_connection_error_with_successful_retry(test_domain, caplog):
    """Test read_blocking connection error handling with successful retry."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish a test message
    broker = test_domain.brokers["default"]
    broker.publish(stream, {"test": "data", "id": 1})

    adapter = broker._adapter

    # Store original methods
    original_read_blocking = adapter.read_blocking

    # Track method calls
    read_blocking_calls = []
    reconnect_calls = []

    def mock_read_blocking(*args, **kwargs):
        read_blocking_calls.append((args, kwargs))
        if len(read_blocking_calls) == 1:
            # First call raises a connection error
            raise redis.ConnectionError("Connection lost to Redis server")
        else:
            # Second call succeeds after recovery
            return original_read_blocking(*args, **kwargs)

    def mock_reconnect():
        reconnect_calls.append(True)
        # Simulate successful reconnection
        return True

    # Replace the adapter's methods; the service retries around them
    adapter.read_blocking = mock_read_blocking
    adapter.reconnect = mock_reconnect

    try:
        with caplog.at_level("WARNING"):
            # This should trigger error, recovery, and retry
            result = broker.read_blocking(
                stream=stream,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
                timeout_ms=1000,
                count=1,
            )

            # Verify the sequence of calls
            assert len(read_blocking_calls) == 2, (
                "Should have called the adapter's read_blocking twice (initial + retry)"
            )
            assert len(reconnect_calls) == 1, "Should have called reconnect once"

            # Verify arguments were preserved on retry
            first_call_args = read_blocking_calls[0]
            second_call_args = read_blocking_calls[1]

            # Check that both calls have the same arguments
            assert first_call_args[0] == second_call_args[0], (
                "Args should be the same on retry"
            )
            assert first_call_args[1] == second_call_args[1], (
                "Kwargs should be the same on retry"
            )

            # Verify we got the message
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0][1]["test"] == "data"

            # Verify warning was logged
            assert "Connection error during read_blocking" in caplog.text
            assert "Connection lost to Redis server" in caplog.text

    finally:
        # Restore original methods
        del adapter.read_blocking
        del adapter.reconnect


@pytest.mark.redis
class TestRedisReconnectAfterClose:
    """Reviving a closed Redis connection against a live server.

    Engine shutdown closes the broker (``redis_instance`` becomes ``None``).
    A straggler poll read, a publish, or a test-teardown ``clear`` can
    reuse the broker afterwards. Each must reconnect instead of raising
    ``AttributeError: 'NoneType' object has no attribute ...``.
    """

    def test_publish_and_read_revive_after_close(self, test_domain):
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
        stream = "revive-stream"

        broker.publish(stream, {"first": "message"})

        # Simulate engine shutdown tearing down the connection.
        broker.close()
        assert broker.redis_instance is None

        # Reusing the broker must reconnect, not crash.
        broker.publish(stream, {"second": "message"})
        assert broker.redis_instance is not None

        messages = broker.read(stream, "revive-group", limit=10)
        assert len(messages) >= 1

    def test_clear_revives_after_close(self, test_domain):
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
        broker.publish("some-stream", {"payload": "x"})

        broker.close()
        assert broker.redis_instance is None

        # Teardown reset after the connection was closed must not raise.
        broker.clear()
        assert broker.redis_instance is not None

    def test_poll_loop_survives_midrun_close(self, test_domain):
        """Repeated reads keep working after the connection is closed mid-run.

        Mirrors the engine's poll loop: it reads in a loop; if the connection is
        torn down (as engine shutdown does) a subsequent read must reconnect and
        keep draining messages rather than dying with AttributeError.
        """
        broker = RedisBroker("test_redis", test_domain, {"URI": f"{REDIS_URI}/0"})
        stream, group = "survive-stream", "survive-group"
        broker.create_group(stream, group)

        for i in range(3):
            broker.publish(stream, {"n": i})

        broker.close()
        assert broker.redis_instance is None

        # Poll loop continues after the mid-run close: read and ACK each message.
        collected = []
        for _ in range(5):
            batch = broker.read(stream, group, limit=10)
            for identifier, payload in batch:
                collected.append(payload)
                broker.ack(stream, identifier, group)

        assert broker.redis_instance is not None
        assert sorted(m["n"] for m in collected) == [0, 1, 2]
