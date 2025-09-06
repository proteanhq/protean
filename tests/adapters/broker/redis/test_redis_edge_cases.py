"""Tests for Redis broker edge cases and error scenarios."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker


@pytest.mark.redis
class TestRedisEdgeCases:
    """Test edge cases and error scenarios for Redis broker."""

    def test_get_next_handle_redis_error_other_than_nogroup(self, test_domain):
        """Test _get_next handling of non-NOGROUP Redis errors (line 90, 117-118)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Mock redis instance to raise a non-NOGROUP error
        mock_redis = MagicMock()
        mock_redis.xreadgroup.side_effect = redis.ResponseError(
            "WRONGTYPE Operation against a key holding the wrong kind of value"
        )
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        result = broker._get_next("test-stream", "test-group")

        # Should return None and not retry
        assert result is None
        # Should have been called only once (no retry)
        mock_redis.xreadgroup.assert_called_once()

    def test_get_next_response_with_empty_inner_messages(self, test_domain):
        """Test _get_next when response has empty inner messages (line 102)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Mock redis instance to return response with empty messages
        mock_redis = MagicMock()
        # Response format: [(stream_name, [])]  - empty messages list
        mock_redis.xreadgroup.return_value = [("test-stream", [])]
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        result = broker._get_next("test-stream", "test-group")

        # Should return None when messages list is empty
        assert result is None

    def test_read_with_fields_none(self, test_domain):
        """Test _read when response contains None fields (line 166->165)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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

        messages = broker._read("test-stream", "test-group", 3)

        # Should only return messages with valid fields
        assert len(messages) == 2
        assert messages[0][1]["test"] == "data1"
        assert messages[1][1]["test"] == "data2"

    def test_read_pending_with_none_fields(self, test_domain):
        """Test _read with pending messages having None fields (line 181->180)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker._read("test-stream", "test-group", 3)

        # Should return 2 valid messages (1 new + 1 pending)
        assert len(messages) == 2
        assert messages[0][1]["test"] == "data1"
        assert messages[1][1]["test"] == "data2"

    def test_read_respects_message_limit(self, test_domain):
        """Test _read stops when reaching message limit (lines 184-191)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        # Request only 3 messages
        messages = broker._read("test-stream", "test-group", 3)

        # Should return exactly 3 messages and stop
        assert len(messages) == 3
        assert messages[0][1]["test"] == "data1"
        assert messages[1][1]["test"] == "data2"
        assert messages[2][1]["test"] == "data3"

    def test_read_avoids_duplicates(self, test_domain):
        """Test _read avoids duplicate message IDs (lines 183-186)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        broker.redis_instance = mock_redis

        # Ensure group is mocked
        broker._created_groups_set.add("test-stream:test-group")

        messages = broker._read("test-stream", "test-group", 4)

        # Should return 3 unique messages (duplicate skipped)
        assert len(messages) == 3
        message_ids = [msg[0] for msg in messages]
        assert message_ids == ["1-0", "1-1", "1-2"]
        # Verify the duplicate was skipped (data2, not duplicate)
        assert messages[1][1]["test"] == "data2"

    def test_read_blocking_with_pending_messages(self, test_domain):
        """Test _read_blocking returns pending messages first (line 233->245)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        """Test _read_blocking skips pending messages with None fields (line 237->236)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        """Test _read_blocking handling NOGROUP error (lines 267-278)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        # _read_blocking makes 2 calls initially (pending + new), gets error, creates group, then retries with 2 more calls
        assert call_count[0] >= 3  # At least 3 calls total
        mock_redis.xgroup_create.assert_called_once()

    def test_read_blocking_other_response_error(self, test_domain, caplog):
        """Test _read_blocking handling non-NOGROUP ResponseError (line 274)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        assert "Redis error in _read_blocking" in caplog.text

    def test_read_blocking_unexpected_error(self, test_domain, caplog):
        """Test _read_blocking handling unexpected exceptions (lines 276-278)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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
        assert "Unexpected error in _read_blocking" in caplog.text

    def test_ensure_group_existing_group_tracking(self, test_domain):
        """Test _ensure_group tracks creation time for existing groups (lines 374->exit)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Mock redis instance
        mock_redis = MagicMock()
        # Simulate BUSYGROUP error (group already exists)
        mock_redis.xgroup_create.side_effect = redis.ResponseError(
            "BUSYGROUP Consumer Group name already exists"
        )
        broker.redis_instance = mock_redis

        # Ensure group hasn't been tracked yet
        assert "test-group" not in broker._group_creation_times

        # Call ensure_group
        broker._ensure_group("test-group", "test-stream")

        # Should track the creation time even for existing group
        assert "test-group" in broker._group_creation_times
        assert broker._group_creation_times["test-group"] > 0
        assert "test-stream:test-group" in broker._created_groups_set

    def test_get_streams_to_check_with_no_separator(self, test_domain):
        """Test _get_streams_to_check skips entries without separator (line 424->423)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Add some entries to _created_groups, including invalid ones
        broker._created_groups_set.add("test-stream:test-group")  # Valid
        broker._created_groups_set.add("another-stream:another-group")  # Valid
        broker._created_groups_set.add(
            "invalid-entry"
        )  # No separator - should be skipped
        broker._created_groups_set.add(
            "also-invalid"
        )  # No separator - should be skipped

        # Add a subscriber
        broker._subscribers["subscriber-stream"] = set()

        streams = broker._get_streams_to_check()

        # Should only include valid streams
        assert "test-stream" in streams
        assert "another-stream" in streams
        assert "subscriber-stream" in streams
        assert "invalid-entry" not in streams
        assert "also-invalid" not in streams

    def test_extract_group_data_non_dict(self, test_domain):
        """Test _extract_group_data skips non-dict entries (line 441->436)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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

    def test_get_field_value_conversion_failure(self, test_domain, caplog):
        """Test _get_field_value when int conversion fails (lines 511-515)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Test with non-numeric value
        info_dict = {"pending": "not-a-number"}

        with caplog.at_level(logging.WARNING):
            result = broker._get_field_value(info_dict, "pending", convert_to_int=True)

        # Should return 0 and log warning
        assert result == 0
        assert "Failed to convert not-a-number to int" in caplog.text

    def test_calculate_message_counts_xinfo_groups_error(self, test_domain):
        """Test _calculate_message_counts when xinfo_groups fails (lines 545->544, 550-552)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Mock redis instance
        mock_redis = MagicMock()
        mock_redis.xlen.return_value = 100  # Stream has 100 messages
        # xinfo_groups raises error (stream has no consumer groups)
        mock_redis.xinfo_groups.side_effect = redis.ResponseError("ERR no such key")
        broker.redis_instance = mock_redis

        # Add a stream to check
        broker._subscribers["test-stream"] = set()

        counts = broker._calculate_message_counts()

        # Should still return total messages, with 0 pending
        assert counts["total_messages"] == 100
        assert counts["in_flight"] == 0  # No pending since groups info failed

    def test_calculate_streams_info_stream_doesnt_exist(self, test_domain):
        """Test _calculate_streams_info when xlen fails for non-existent stream (lines 581->579, 583-585)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Mock redis instance
        mock_redis = MagicMock()

        def xlen_side_effect(stream):
            if stream == "existing-stream":
                return 10
            else:
                # Non-existent streams raise ResponseError
                raise redis.ResponseError("ERR no such key")

        mock_redis.xlen.side_effect = xlen_side_effect
        broker.redis_instance = mock_redis

        # Add both existing and non-existing streams
        broker._subscribers["existing-stream"] = set()
        broker._subscribers["non-existing-stream"] = set()
        broker._subscribers["another-missing"] = set()

        streams_info = broker._calculate_streams_info()

        # Should only include existing stream
        assert streams_info["count"] == 1
        assert "existing-stream" in streams_info["names"]
        assert "non-existing-stream" not in streams_info["names"]
        assert "another-missing" not in streams_info["names"]

    def test_calculate_consumer_groups_info_no_separator(self, test_domain):
        """Test _calculate_consumer_groups_info skips entries without separator (line 602->601)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

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

    def test_ensure_connection_reconnect_failure(self, test_domain, caplog):
        """Test _ensure_connection when reconnection fails (lines 734-737)."""
        broker = RedisBroker(
            "test_redis", test_domain, {"URI": "redis://localhost:6379/0"}
        )

        # Mock redis instance that always fails ping
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = Exception("Connection refused")
        broker.redis_instance = mock_redis

        # Mock Redis.from_url to also fail
        with patch(
            "redis.Redis.from_url", side_effect=Exception("Cannot create connection")
        ):
            with caplog.at_level(logging.ERROR):
                result = broker._ensure_connection()

        # Should return False and log errors
        assert result is False
        assert "Failed to create new Redis connection" in caplog.text
        assert "Cannot create connection" in caplog.text
        assert "Failed to ensure Redis connection after 3 attempts" in caplog.text
