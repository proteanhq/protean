"""Redis-specific tests focused on Redis PubSub broker behavior and edge cases"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
import redis

from protean.port.broker import OperationState


@pytest.mark.redis
class TestRedisWatchErrorHandling:
    """Test Redis transaction retry mechanisms"""

    def test_get_next_retries_on_watch_error(self, broker):
        """When Redis transaction fails due to position change, get_next should retry successfully"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Publish a message
        identifier = broker.publish(stream, message)

        # Mock pipeline to raise WatchError on first call, succeed on second
        original_pipeline = broker.redis_instance.pipeline
        call_count = 0

        def mock_pipeline(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            pipe = original_pipeline(*args, **kwargs)

            if call_count == 1:
                original_execute = pipe.execute

                def failing_execute():
                    raise redis.WatchError("Position changed")

                pipe.execute = failing_execute

            return pipe

        with patch.object(broker.redis_instance, "pipeline", side_effect=mock_pipeline):
            result = broker.get_next(stream, consumer_group)

            # Should successfully get message after retry
            assert result is not None
            assert result[0] == identifier
            assert result[1] == message
            assert call_count >= 2  # Should have retried

    def test_get_next_returns_none_on_general_exception(self, broker):
        """When Redis transaction fails with general exception, get_next should return None"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Publish a message first
        broker.publish(stream, message)

        # Mock pipeline to raise general exception
        with patch.object(broker.redis_instance, "pipeline") as mock_pipeline:
            mock_pipe = MagicMock()
            mock_pipeline.return_value = mock_pipe
            mock_pipe.execute.side_effect = Exception("Redis connection error")

            result = broker._get_next(stream, consumer_group)

            assert result is None


@pytest.mark.redis
class TestRedisDataHandling:
    """Test Redis-specific data type handling (bytes vs strings)"""

    def test_operation_state_handles_bytes_response(self, broker):
        """Operation state should handle both bytes and string responses from Redis"""
        consumer_group = "test_consumer_group"
        identifier = "test_id"

        # Test with bytes response
        with patch.object(broker.redis_instance, "get", return_value=b"acknowledged"):
            result = broker._get_operation_state(consumer_group, identifier)
            assert result == OperationState.ACKNOWLEDGED

        # Test with string response
        with patch.object(broker.redis_instance, "get", return_value="acknowledged"):
            result = broker._get_operation_state(consumer_group, identifier)
            assert result == OperationState.ACKNOWLEDGED

        # Test with None response
        with patch.object(broker.redis_instance, "get", return_value=None):
            result = broker._get_operation_state(consumer_group, identifier)
            assert result is None

        # Test with invalid state
        with patch.object(broker.redis_instance, "get", return_value="invalid_state"):
            result = broker._get_operation_state(consumer_group, identifier)
            assert result is None

    def test_failed_message_handling_with_bytes(self, broker):
        """Failed message retrieval should handle both bytes and string data"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Create a failed message
        failed_key = f"failed:{stream}:{consumer_group}"
        failed_data = {
            "identifier": "test_id",
            "message": json.dumps({"data": "test"}),
            "retry_count": 1,
            "next_retry_time": str(time.time() - 10),  # Ready for retry
        }
        broker.redis_instance.rpush(failed_key, json.dumps(failed_data))

        # Mock lrange to return bytes
        original_lrange = broker.redis_instance.lrange

        def mock_lrange(*args, **kwargs):
            results = original_lrange(*args, **kwargs)
            return [r.encode() if isinstance(r, str) else r for r in results]

        with patch.object(broker.redis_instance, "lrange", side_effect=mock_lrange):
            result = broker._get_retry_ready_messages(stream, consumer_group)

            assert len(result) == 1
            assert result[0][0] == "test_id"
            assert result[0][1] == {"data": "test"}


@pytest.mark.redis
class TestRedisMessageFlowBehavior:
    """Test complete message flow behaviors"""

    def test_get_next_returns_none_for_empty_stream(self, broker):
        """get_next should return None when stream has no messages"""
        stream = "empty_stream"
        consumer_group = "test_consumer_group"

        result = broker._get_next(stream, consumer_group)
        assert result is None

    def test_read_method_stops_when_no_more_messages(self, broker):
        """read() should stop and return fewer messages when stream is exhausted"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Publish only 2 messages
        msg1 = {"data": "message1"}
        msg2 = {"data": "message2"}
        broker.publish(stream, msg1)
        broker.publish(stream, msg2)

        # Request 5 messages but should only get 2
        messages = broker.read(stream, consumer_group, 5)

        assert len(messages) == 2
        assert messages[0][1] == msg1
        assert messages[1][1] == msg2

    def test_in_flight_message_operations(self, broker):
        """Test complete in-flight message lifecycle"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Publish and get a message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        assert retrieved_message is not None
        assert retrieved_message[0] == identifier

        # Verify message is in-flight
        assert broker._is_in_flight_message(stream, consumer_group, identifier)

        # Get in-flight message
        in_flight_msg = broker._get_in_flight_message(
            stream, consumer_group, identifier
        )
        assert in_flight_msg is not None
        assert in_flight_msg[0] == identifier
        assert in_flight_msg[1] == message

        # Remove from in-flight
        broker._remove_in_flight_message(stream, consumer_group, identifier)
        assert not broker._is_in_flight_message(stream, consumer_group, identifier)

    def test_consumer_group_validation(self, broker):
        """Test consumer group validation behavior"""

        # Non-existent group should be invalid
        assert broker._validate_consumer_group("nonexistent_group") is False

        # Created group should be valid
        group_name = "test_group"
        stream = "test_stream"
        broker._ensure_group(group_name, stream)
        assert broker._validate_consumer_group(group_name) is True

    def test_message_ownership_validation(self, broker):
        """Test message ownership validation"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Get a message to establish ownership
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        # Verify message was retrieved successfully
        assert retrieved_message is not None
        assert retrieved_message[0] == identifier

        # Should validate ownership for correct consumer group
        ownership_result = broker._validate_message_ownership(
            identifier, consumer_group
        )
        assert ownership_result == 1

        # Should not validate for different consumer group
        no_ownership_result = broker._validate_message_ownership(
            identifier, "different_group"
        )
        assert no_ownership_result == 0

        # Should not validate for non-existent message
        nonexistent_result = broker._validate_message_ownership(
            "nonexistent_id", consumer_group
        )
        assert nonexistent_result == 0


@pytest.mark.redis
class TestRedisErrorHandling:
    """Test error handling in Redis operations"""

    def test_failed_message_removal_handles_exceptions(self, broker):
        """_remove_failed_message should handle Redis exceptions gracefully"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"

        with patch.object(
            broker.redis_instance, "lrange", side_effect=Exception("Redis error")
        ):
            # Should not raise exception
            broker._remove_failed_message(stream, consumer_group, identifier)

    def test_retry_ready_messages_handles_exceptions(self, broker):
        """_get_retry_ready_messages should return empty list on Redis exceptions"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        with patch.object(
            broker.redis_instance, "lrange", side_effect=Exception("Redis error")
        ):
            result = broker._get_retry_ready_messages(stream, consumer_group)
            assert result == []

    def test_dlq_messages_handles_exceptions(self, broker):
        """_get_dlq_messages should return empty dict on Redis exceptions"""
        consumer_group = "test_consumer_group"

        with patch.object(
            broker.redis_instance, "lrange", side_effect=Exception("Redis error")
        ):
            result = broker._get_dlq_messages(consumer_group, "test_stream")
            assert result == {}

        with patch.object(
            broker.redis_instance, "keys", side_effect=Exception("Redis error")
        ):
            result = broker._get_dlq_messages(consumer_group, None)
            assert result == {}

    def test_cleanup_operations_handle_exceptions(self, test_domain):
        """Cleanup operations should handle Redis exceptions gracefully"""
        broker = test_domain.brokers["default"]

        # These should not raise exceptions - testing graceful degradation
        with patch.object(
            broker.redis_instance, "keys", side_effect=Exception("Redis error")
        ):
            # Should complete without raising exception
            try:
                broker._cleanup_stale_messages("test_group", 10.0)
            except Exception as e:
                pytest.fail(
                    f"_cleanup_stale_messages should handle exceptions gracefully, but raised: {e}"
                )

        with patch.object(
            broker.redis_instance, "sismember", side_effect=Exception("Redis error")
        ):
            result = broker._validate_message_ownership("test_id", "test_group")
            assert result is False

        with patch.object(
            broker.redis_instance, "pipeline", side_effect=Exception("Redis error")
        ):
            # Should complete without raising exception
            try:
                broker._cleanup_message_ownership("test_id", "test_group")
            except Exception as e:
                pytest.fail(
                    f"_cleanup_message_ownership should handle exceptions gracefully, but raised: {e}"
                )


@pytest.mark.redis
class TestRedisMessageRequeue:
    """Test message requeue behavior"""

    def test_requeue_messages_with_empty_stream(self, test_domain):
        """Requeue should work even when target stream is empty"""
        broker = test_domain.brokers["default"]
        stream = "empty_stream"
        consumer_group = "test_consumer_group"

        # Set position > 0 for an empty stream
        position_key = f"position:{consumer_group}:{stream}"
        broker.redis_instance.set(position_key, "2")

        # Requeue should work without error
        messages = [("test_id", {"data": "requeued"})]
        broker._requeue_messages(stream, consumer_group, messages)

        # Message should be in the stream
        stream_contents = broker.redis_instance.lrange(stream, 0, -1)
        assert len(stream_contents) >= 1

    def test_requeue_updates_other_consumer_positions(self, broker):
        """Requeue should update positions for other consumer groups"""
        stream = "test_stream"
        consumer_group1 = "group1"
        consumer_group2 = "group2"

        # Create both groups and set positions
        broker._ensure_group(consumer_group1, stream)
        broker._ensure_group(consumer_group2, stream)

        # Publish some initial messages
        for i in range(3):
            broker.publish(stream, {"data": f"msg{i}"})

        # Set positions
        pos_key1 = f"position:{stream}:{consumer_group1}"
        pos_key2 = f"position:{stream}:{consumer_group2}"
        broker.redis_instance.set(pos_key1, "1")
        broker.redis_instance.set(pos_key2, "2")

        # Requeue for group1
        messages = [("requeue_id", {"data": "requeued"})]
        broker._requeue_messages(stream, consumer_group1, messages)

        # Group2's position should be incremented
        updated_pos = int(broker.redis_instance.get(pos_key2) or 0)
        assert updated_pos > 2

    def test_requeue_with_empty_messages_list(self, broker):
        """Requeue with empty messages list should return early"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Should not cause any errors
        broker._requeue_messages(stream, consumer_group, [])


@pytest.mark.redis
class TestRedisDLQOperations:
    """Test DLQ operations"""

    def test_dlq_message_storage_and_retrieval(self, broker):
        """Test DLQ message storage and retrieval"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"
        message = {"data": "test"}
        failure_reason = "test_failure"

        # Store message in DLQ
        broker._store_dlq_message(
            stream, consumer_group, identifier, message, failure_reason
        )

        # Retrieve DLQ messages for specific stream
        dlq_messages = broker._get_dlq_messages(consumer_group, stream)
        assert stream in dlq_messages
        assert len(dlq_messages[stream]) == 1

        dlq_entry = dlq_messages[stream][0]
        assert dlq_entry[0] == identifier
        assert dlq_entry[1] == message
        assert dlq_entry[2] == failure_reason

        # Retrieve all DLQ messages for consumer group
        all_dlq_messages = broker._get_dlq_messages(consumer_group)
        assert stream in all_dlq_messages
        assert len(all_dlq_messages[stream]) == 1

    def test_dlq_message_reprocessing(self, broker):
        """Test DLQ message reprocessing"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"
        message = {"data": "reprocess_test"}

        # Store message in DLQ
        broker._store_dlq_message(
            stream, consumer_group, identifier, message, "test_failure"
        )

        # Reprocess the message
        result = broker._reprocess_dlq_message(identifier, consumer_group, stream)
        assert result is True

        # Verify message was removed from DLQ
        dlq_messages = broker._get_dlq_messages(consumer_group, stream)
        if stream in dlq_messages:
            assert len(dlq_messages[stream]) == 0

        # Verify message is back in main queue
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None
        assert retrieved_message[0] == identifier
        assert retrieved_message[1] == message

    def test_dlq_reprocess_nonexistent_message(self, broker):
        """Test reprocessing a non-existent DLQ message"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        non_existent_id = "non_existent_id"

        # Try to reprocess non-existent message
        result = broker._reprocess_dlq_message(non_existent_id, consumer_group, stream)
        assert result is False


@pytest.mark.redis
class TestRedisInfoOperations:
    """Test info operations"""

    def test_info_provides_consumer_group_details(self, broker):
        """Test that info provides comprehensive consumer group information"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "info_test"}

        # Create consumer group and process some messages
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)

        # Get info
        info = broker._info()

        assert "consumer_groups" in info
        assert consumer_group in info["consumer_groups"]

        group_info = info["consumer_groups"][consumer_group]
        assert "consumers" in group_info
        assert "created_at" in group_info
        assert "consumer_count" in group_info
        assert "in_flight_count" in group_info
        assert "in_flight_messages" in group_info
        assert "failed_count" in group_info
        assert "failed_messages" in group_info
        assert "dlq_count" in group_info
        assert "dlq_messages" in group_info

        # Verify stream-specific breakdowns
        assert stream in group_info["in_flight_messages"]
        assert stream in group_info["failed_messages"]
        assert stream in group_info["dlq_messages"]

    def test_consumer_groups_for_stream(self, broker):
        """Test getting consumer groups for a specific stream"""
        stream = "test_stream"
        consumer_group1 = "group1"
        consumer_group2 = "group2"
        message = {"data": "test"}

        # Create consumer groups
        broker._ensure_group(consumer_group1, stream)
        broker._ensure_group(consumer_group2, stream)

        # Publish messages for both groups to consume
        broker.publish(stream, message)
        broker.publish(stream, message)

        # Have both groups consume to create position keys
        broker.get_next(stream, consumer_group1)
        broker.get_next(stream, consumer_group2)

        # Get consumer groups for stream
        groups = broker._get_consumer_groups_for_stream(stream)

        assert consumer_group1 in groups
        assert consumer_group2 in groups

    def test_info_handles_legacy_keys_without_separator(self, broker):
        """Test info method handles legacy keys that might not have separator"""
        # Create a legacy key format without separator for testing
        legacy_key = "consumer_group:legacy_format_without_separator"
        broker.redis_instance.hset(
            legacy_key, mapping={"created_at": str(time.time()), "consumer_count": "1"}
        )

        # Info should handle this gracefully and continue processing
        info = broker._info()
        assert "consumer_groups" in info
        # The legacy key should be skipped but not cause errors

    def test_get_consumer_groups_for_stream_error_handling(self, broker):
        """Test error handling in _get_consumer_groups_for_stream"""
        stream = "test_stream"

        # Mock keys() to raise exception
        with patch.object(
            broker.redis_instance, "keys", side_effect=Exception("Redis error")
        ):
            result = broker._get_consumer_groups_for_stream(stream)
            assert result == []  # Should return empty list on error


@pytest.mark.redis
class TestRedisCleanupOperations:
    """Test cleanup and maintenance operations"""

    def test_cleanup_stale_messages_without_dlq(self, broker):
        """Cleanup should work when DLQ is disabled"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Disable DLQ temporarily
        original_enable_dlq = broker._enable_dlq
        try:
            broker._enable_dlq = False

            # Create stale in-flight message
            identifier = broker.publish(stream, message)
            broker.get_next(stream, consumer_group)

            # Make message stale by setting old timestamp
            in_flight_key = f"in_flight:{stream}:{consumer_group}"
            old_timestamp = time.time() - 1000
            message_info = {
                "identifier": identifier,
                "message": json.dumps(message),
                "timestamp": str(old_timestamp),
            }
            broker.redis_instance.hset(
                in_flight_key, identifier, json.dumps(message_info)
            )

            # Cleanup should remove the message
            broker._cleanup_stale_messages(consumer_group, 10.0)
            assert not broker._is_in_flight_message(stream, consumer_group, identifier)

        finally:
            broker._enable_dlq = original_enable_dlq

    def test_cleanup_message_ownership(self, broker):
        """Test message ownership cleanup"""
        identifier = "test_id"
        consumer_group = "test_consumer_group"
        stream = "test_stream"

        # Set up message ownership
        ownership_key = f"ownership:{identifier}"
        broker.redis_instance.sadd(ownership_key, f"{stream}:{consumer_group}")

        # Cleanup
        broker._cleanup_message_ownership(identifier, consumer_group)

        # Verify cleanup
        members = broker.redis_instance.smembers(ownership_key)
        assert len(members) == 0

    def test_cleanup_message_ownership_preserves_other_owners(self, broker):
        """Test that ownership cleanup only removes specific consumer group"""
        identifier = "test_id"
        consumer_group1 = "group1"
        consumer_group2 = "group2"
        stream = "test_stream"

        # Set up message ownership for multiple groups
        ownership_key = f"ownership:{identifier}"
        broker.redis_instance.sadd(ownership_key, f"{stream}:{consumer_group1}")
        broker.redis_instance.sadd(ownership_key, f"{stream}:{consumer_group2}")

        # Cleanup only group1
        broker._cleanup_message_ownership(identifier, consumer_group1)

        # Verify group2 ownership is preserved
        members = broker.redis_instance.smembers(ownership_key)
        assert len(members) == 1
        remaining_member = list(members)[0]
        if isinstance(remaining_member, bytes):
            remaining_member = remaining_member.decode()
        assert remaining_member == f"{stream}:{consumer_group2}"

    def test_cleanup_message_ownership_with_empty_result(self, broker):
        """Test cleanup when ownership set becomes empty"""
        identifier = "test_id"
        consumer_group = "test_consumer_group"
        stream = "test_stream"

        # Set up single ownership
        ownership_key = f"ownership:{identifier}"
        broker.redis_instance.sadd(ownership_key, f"{stream}:{consumer_group}")

        # Cleanup - should delete the key when empty
        broker._cleanup_message_ownership(identifier, consumer_group)

        # Verify key is deleted
        assert not broker.redis_instance.exists(ownership_key)

    def test_cleanup_message_ownership_exception_handling(self, broker):
        """Test cleanup handles exceptions gracefully"""
        identifier = "test_id"
        consumer_group = "test_consumer_group"

        # Mock smembers to raise exception
        with patch.object(
            broker.redis_instance, "smembers", side_effect=Exception("Redis error")
        ):
            # Should not raise exception
            try:
                broker._cleanup_message_ownership(identifier, consumer_group)
            except Exception as e:
                pytest.fail(f"Cleanup should handle exceptions gracefully: {e}")


@pytest.mark.redis
class TestRedisRetryLogic:
    """Test retry logic and failed message handling"""

    def test_retry_ready_messages_filters_correctly(self, broker):
        """Test that retry ready messages are filtered by time correctly"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        current_time = time.time()

        # Store failed messages with different retry times
        failed_key = f"failed:{stream}:{consumer_group}"

        # Message ready for retry (past time)
        ready_message = {
            "identifier": "ready_id",
            "message": json.dumps({"data": "ready"}),
            "retry_count": 1,
            "next_retry_time": str(current_time - 10),
        }

        # Message not ready (future time)
        not_ready_message = {
            "identifier": "not_ready_id",
            "message": json.dumps({"data": "not_ready"}),
            "retry_count": 1,
            "next_retry_time": str(current_time + 100),
        }

        broker.redis_instance.rpush(failed_key, json.dumps(ready_message))
        broker.redis_instance.rpush(failed_key, json.dumps(not_ready_message))

        # Get retry ready messages
        ready_messages = broker._get_retry_ready_messages(stream, consumer_group)

        # Should only get the ready message
        assert len(ready_messages) == 1
        assert ready_messages[0][0] == "ready_id"
        assert ready_messages[0][1] == {"data": "ready"}

        # Verify not ready message is still in failed queue
        remaining = broker.redis_instance.lrange(failed_key, 0, -1)
        assert len(remaining) == 1
        remaining_data = json.loads(remaining[0])
        assert remaining_data["identifier"] == "not_ready_id"

    def test_get_retry_ready_messages_exception_handling(self, broker):
        """Test exception handling in _get_retry_ready_messages"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Mock lrange to raise exception
        with patch.object(
            broker.redis_instance, "lrange", side_effect=Exception("Redis error")
        ):
            result = broker._get_retry_ready_messages(stream, consumer_group)
            assert result == []  # Should return empty list on error

    def test_remove_failed_message_finds_correct_message(self, broker):
        """Test that _remove_failed_message finds and removes the correct message"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        failed_key = f"failed:{stream}:{consumer_group}"

        # Store multiple failed messages
        messages = [
            {
                "identifier": "msg1",
                "message": json.dumps({"data": "message1"}),
                "retry_count": 1,
                "next_retry_time": str(time.time()),
            },
            {
                "identifier": "target_msg",
                "message": json.dumps({"data": "target"}),
                "retry_count": 2,
                "next_retry_time": str(time.time()),
            },
            {
                "identifier": "msg3",
                "message": json.dumps({"data": "message3"}),
                "retry_count": 1,
                "next_retry_time": str(time.time()),
            },
        ]

        for msg in messages:
            broker.redis_instance.rpush(failed_key, json.dumps(msg))

        # Remove target message
        broker._remove_failed_message(stream, consumer_group, "target_msg")

        # Verify correct message was removed
        remaining = broker.redis_instance.lrange(failed_key, 0, -1)
        assert len(remaining) == 2

        remaining_ids = []
        for msg_bytes in remaining:
            msg_data = json.loads(msg_bytes)
            remaining_ids.append(msg_data["identifier"])

        assert "msg1" in remaining_ids
        assert "msg3" in remaining_ids
        assert "target_msg" not in remaining_ids

    def test_remove_failed_message_nonexistent(self, broker):
        """Test removing a non-existent failed message"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Should not cause any errors
        broker._remove_failed_message(stream, consumer_group, "non_existent_id")


@pytest.mark.redis
class TestRedisUtilityMethods:
    """Test utility methods"""

    def test_ensure_group_creates_group(self, broker):
        """Test that _ensure_group creates a new consumer group"""
        stream = "test_stream"
        consumer_group = "new_consumer_group"

        # Verify group doesn't exist
        assert not broker._validate_consumer_group(consumer_group)

        # Create group
        broker._ensure_group(consumer_group, stream)

        # Verify group now exists
        assert broker._validate_consumer_group(consumer_group)

        # Verify group data was stored
        group_key = f"consumer_group:{stream}:{consumer_group}"
        group_data = broker.redis_instance.hgetall(group_key)
        assert group_data
        assert b"created_at" in group_data or "created_at" in group_data

    def test_ensure_group_idempotent(self, broker):
        """Test that _ensure_group is idempotent"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Create group twice
        broker._ensure_group(consumer_group, stream)
        group_key = f"consumer_group:{stream}:{consumer_group}"
        first_data = dict(broker.redis_instance.hgetall(group_key))

        broker._ensure_group(consumer_group, stream)
        second_data = dict(broker.redis_instance.hgetall(group_key))

        # Data should be the same (no duplicate creation)
        assert first_data == second_data

    def test_data_reset_clears_all_data(self, broker):
        """Test that _data_reset clears all Redis data"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Create some data
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker._store_dlq_message(
            stream, consumer_group, "dlq_id", message, "test_failure"
        )

        # Verify data exists
        assert broker.redis_instance.exists(stream)
        dlq_key = f"dlq:{stream}:{consumer_group}"
        assert broker.redis_instance.exists(dlq_key)

        # Reset data
        broker._data_reset()

        # Verify all data is cleared
        assert not broker.redis_instance.exists(stream)
        assert not broker.redis_instance.exists(dlq_key)

        # Verify we can still use the broker after reset
        new_identifier = broker.publish(stream, message)
        new_message = broker.get_next(stream, consumer_group)
        assert new_message is not None
        assert new_message[0] == new_identifier

    def test_cleanup_expired_operation_states_noop(self, broker):
        """_cleanup_expired_operation_states should be a no-op (Redis handles TTL)"""

        # Create some test data to verify the method doesn't affect anything
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Create some operation states
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)

        # Store operation state
        from protean.port.broker import OperationState

        broker._store_operation_state(
            consumer_group, identifier, OperationState.PENDING
        )

        # Capture state before cleanup
        operation_state_before = broker._get_operation_state(consumer_group, identifier)

        # Verify the operation state exists
        assert operation_state_before == OperationState.PENDING

        # Call cleanup - should be a no-op for Redis
        broker._cleanup_expired_operation_states()

        # Verify operation state is unchanged (Redis handles TTL automatically)
        operation_state_after = broker._get_operation_state(consumer_group, identifier)
        assert operation_state_after == operation_state_before

        # Verify other data structures are also unchanged
        assert broker._is_in_flight_message(stream, consumer_group, identifier)

        # Verify the method completes without raising errors
        broker._cleanup_expired_operation_states()
        broker._cleanup_expired_operation_states()  # Multiple calls should be safe


@pytest.mark.redis
class TestRedisBytesHandling:
    """Test Redis bytes vs strings handling"""

    def test_get_dlq_messages_handles_bytes_keys(self, broker):
        """Test DLQ retrieval handles both bytes and string keys"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"
        message = {"data": "test"}

        # Store message in DLQ
        broker._store_dlq_message(
            stream, consumer_group, identifier, message, "test_failure"
        )

        # Mock keys() to return bytes
        original_keys = broker.redis_instance.keys

        def mock_keys(pattern):
            results = original_keys(pattern)
            return [key.encode() if isinstance(key, str) else key for key in results]

        with patch.object(broker.redis_instance, "keys", side_effect=mock_keys):
            # Should handle bytes keys correctly
            dlq_messages = broker._get_dlq_messages(consumer_group)
            assert stream in dlq_messages

    def test_cleanup_stale_messages_handles_bytes_keys(self, broker):
        """Test stale message cleanup handles bytes keys correctly"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Create in-flight message
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)

        # Mock keys() to return bytes for in-flight keys
        original_keys = broker.redis_instance.keys

        def mock_keys(pattern):
            results = original_keys(pattern)
            return [key.encode() if isinstance(key, str) else key for key in results]

        with patch.object(broker.redis_instance, "keys", side_effect=mock_keys):
            # Should handle bytes keys without error
            try:
                broker._cleanup_stale_messages(consumer_group, 10.0)
            except Exception as e:
                pytest.fail(f"Should handle bytes keys gracefully: {e}")

    def test_requeue_position_key_bytes_handling(self, broker):
        """Test requeue handles position keys as bytes"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        messages = [("test_id", {"data": "test"})]

        # Mock keys() to return bytes
        original_keys = broker.redis_instance.keys

        def mock_keys(pattern):
            results = original_keys(pattern)
            return [key.encode() if isinstance(key, str) else key for key in results]

        with patch.object(broker.redis_instance, "keys", side_effect=mock_keys):
            # Should handle bytes position keys without error
            try:
                broker._requeue_messages(stream, consumer_group, messages)
            except Exception as e:
                pytest.fail(f"Should handle bytes position keys gracefully: {e}")

    def test_reprocess_dlq_position_key_bytes_handling(self, broker):
        """Test DLQ reprocessing handles position keys as bytes"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"
        message = {"data": "test"}

        # Store in DLQ
        broker._store_dlq_message(
            stream, consumer_group, identifier, message, "test_failure"
        )

        # Mock keys() to return bytes
        original_keys = broker.redis_instance.keys

        def mock_keys(pattern):
            results = original_keys(pattern)
            return [key.encode() if isinstance(key, str) else key for key in results]

        with patch.object(broker.redis_instance, "keys", side_effect=mock_keys):
            # Should handle bytes position keys during reprocessing
            result = broker._reprocess_dlq_message(identifier, consumer_group, stream)
            assert result is True


@pytest.mark.redis
class TestRedisMessageRequeueComplexScenarios:
    """Test complex requeue scenarios specific to Redis"""

    def test_requeue_with_position_greater_than_zero_rebuild_list(self, broker):
        """Test requeue when current position > 0 requires list rebuild"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Publish initial messages
        for i in range(5):
            broker.publish(stream, {"data": f"initial_{i}"})

        # Advance consumer position
        for _ in range(3):
            broker.get_next(stream, consumer_group)

        # Current position should be 3, now requeue a message
        messages = [("requeue_id", {"data": "requeued"})]
        broker._requeue_messages(stream, consumer_group, messages)

        # Verify message was inserted at correct position
        all_messages = broker.redis_instance.lrange(stream, 0, -1)
        assert len(all_messages) == 6  # 5 initial + 1 requeued

        # The requeued message should be at position 3
        requeued_msg = json.loads(all_messages[3])
        assert requeued_msg[0] == "requeue_id"
        assert requeued_msg[1] == {"data": "requeued"}

    def test_requeue_with_position_zero_uses_lpush(self, broker):
        """Test requeue when position is 0 uses lpush optimization"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        # Ensure consumer group exists and position is 0
        broker._ensure_group(consumer_group, stream)
        position_key = f"position:{stream}:{consumer_group}"
        broker.redis_instance.set(position_key, "0")

        # Requeue messages
        messages = [("requeue_id", {"data": "requeued"})]

        # Mock lpush to verify it's called
        with patch.object(broker.redis_instance, "lpush") as mock_lpush:
            broker._requeue_messages(stream, consumer_group, messages)
            mock_lpush.assert_called_once()

    def test_requeue_updates_consumer_positions_correctly(self, broker):
        """Test that requeue correctly updates other consumer group positions"""
        stream = "test_stream"
        consumer_group1 = "group1"
        consumer_group2 = "group2"
        consumer_group3 = "group3"

        # Set up consumer groups with different positions
        broker._ensure_group(consumer_group1, stream)
        broker._ensure_group(consumer_group2, stream)
        broker._ensure_group(consumer_group3, stream)

        pos_key1 = f"position:{stream}:{consumer_group1}"
        pos_key2 = f"position:{stream}:{consumer_group2}"
        pos_key3 = f"position:{stream}:{consumer_group3}"

        # Set positions: group1=2, group2=1, group3=3
        broker.redis_instance.set(pos_key1, "2")  # Will be requeuing for this group
        broker.redis_instance.set(
            pos_key2, "1"
        )  # Before requeue position, should not change
        broker.redis_instance.set(
            pos_key3, "3"
        )  # At/after requeue position, should increment

        # Requeue for group1 (position 2)
        messages = [("requeue_id", {"data": "requeued"})]
        broker._requeue_messages(stream, consumer_group1, messages)

        # Check final positions
        final_pos1 = int(broker.redis_instance.get(pos_key1) or 0)
        final_pos2 = int(broker.redis_instance.get(pos_key2) or 0)
        final_pos3 = int(broker.redis_instance.get(pos_key3) or 0)

        assert final_pos1 == 2  # Unchanged (own position)
        assert final_pos2 == 1  # Unchanged (before requeue position)
        assert final_pos3 == 4  # Incremented (was at/after requeue position)
