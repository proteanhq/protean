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
        failed_key = f"failed:{consumer_group}:{stream}"
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
        broker._ensure_group(group_name)
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
        broker._ensure_group(consumer_group1)
        broker._ensure_group(consumer_group2)

        # Publish some initial messages
        for i in range(3):
            broker.publish(stream, {"data": f"msg{i}"})

        # Set positions
        pos_key1 = f"position:{consumer_group1}:{stream}"
        pos_key2 = f"position:{consumer_group2}:{stream}"
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
    """Test Dead Letter Queue operations"""

    def test_dlq_message_storage_and_retrieval(self, broker):
        """Test storing and retrieving DLQ messages"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"
        message = {"data": "test"}
        failure_reason = "processing_error"

        # Store DLQ message
        broker._store_dlq_message(
            stream, consumer_group, identifier, message, failure_reason
        )

        # Retrieve DLQ messages for specific stream
        dlq_messages = broker._get_dlq_messages(consumer_group, stream)
        assert stream in dlq_messages
        assert len(dlq_messages[stream]) == 1

        # DLQ messages are returned as tuples: (identifier, message, failure_reason, timestamp)
        dlq_msg = dlq_messages[stream][0]
        assert dlq_msg[0] == identifier  # identifier
        assert dlq_msg[1] == message  # message
        assert dlq_msg[2] == failure_reason  # failure_reason
        assert isinstance(dlq_msg[3], float)  # timestamp

        # Retrieve all DLQ messages
        all_dlq_messages = broker._get_dlq_messages(consumer_group)
        assert stream in all_dlq_messages
        assert len(all_dlq_messages[stream]) == 1

    def test_dlq_message_reprocessing(self, broker):
        """Test reprocessing messages from DLQ"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        identifier = "test_id"
        message = {"data": "test"}

        # Store DLQ message
        broker._store_dlq_message(stream, consumer_group, identifier, message, "error")

        # Verify message is in DLQ
        dlq_messages_before = broker._get_dlq_messages(consumer_group, stream)
        assert stream in dlq_messages_before
        assert len(dlq_messages_before[stream]) == 1

        # Reprocess should succeed
        result = broker._reprocess_dlq_message(identifier, consumer_group, stream)
        assert result is True

        # Message should be removed from DLQ
        dlq_messages_after = broker._get_dlq_messages(consumer_group, stream)
        if stream in dlq_messages_after:
            assert len(dlq_messages_after[stream]) == 0

    def test_dlq_reprocess_nonexistent_message(self, broker):
        """Reprocessing non-existent DLQ message should return False"""

        result = broker._reprocess_dlq_message(
            "nonexistent", "test_group", "test_stream"
        )
        assert result is False


@pytest.mark.redis
class TestRedisInfoOperations:
    """Test Redis info and monitoring operations"""

    def test_info_provides_consumer_group_details(self, broker):
        """Info should provide detailed consumer group information"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Create consumer group and add data
        broker._ensure_group(consumer_group)
        broker.publish(stream, message)
        broker.get_next(stream, consumer_group)  # Creates in-flight message

        # Store failed and DLQ messages
        broker._store_failed_message(
            stream, consumer_group, "failed_id", message, 1, time.time() + 60
        )
        broker._store_dlq_message(stream, consumer_group, "dlq_id", message, "error")

        info = broker._info()

        assert "consumer_groups" in info
        assert consumer_group in info["consumer_groups"]

        group_info = info["consumer_groups"][consumer_group]
        assert "in_flight_messages" in group_info
        assert "failed_messages" in group_info
        assert "dlq_messages" in group_info
        assert stream in group_info["in_flight_messages"]
        assert stream in group_info["failed_messages"]
        assert stream in group_info["dlq_messages"]

    def test_consumer_groups_for_stream(self, broker):
        """Should return consumer groups that have positions for a stream"""
        stream = "test_stream"
        group1 = "group1"
        group2 = "group2"

        # Create groups
        broker._ensure_group(group1)
        broker._ensure_group(group2)

        # Only group1 has a position for the stream
        pos_key1 = f"position:{group1}:{stream}"
        broker.redis_instance.set(pos_key1, "0")

        groups = broker._get_consumer_groups_for_stream(stream)
        assert group1 in groups
        assert group2 not in groups


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
            in_flight_key = f"in_flight:{consumer_group}:{stream}"
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

        # Create ownership
        ownership_key = f"ownership:{identifier}"
        broker.redis_instance.sadd(ownership_key, consumer_group)

        # Cleanup should remove ownership
        broker._cleanup_message_ownership(identifier, consumer_group)

        # Key should be deleted when empty
        assert not broker.redis_instance.exists(ownership_key)

    def test_cleanup_message_ownership_preserves_other_owners(self, broker):
        """Cleanup should preserve ownership for other consumer groups"""
        identifier = "test_id"
        group1 = "group1"
        group2 = "group2"

        # Create ownership for both groups
        ownership_key = f"ownership:{identifier}"
        broker.redis_instance.sadd(ownership_key, group1)
        broker.redis_instance.sadd(ownership_key, group2)

        # Cleanup one group
        broker._cleanup_message_ownership(identifier, group1)

        # Other group should still have ownership
        assert broker.redis_instance.sismember(ownership_key, group2)
        assert not broker.redis_instance.sismember(ownership_key, group1)


@pytest.mark.redis
class TestRedisRetryLogic:
    """Test retry mechanism behavior"""

    def test_retry_ready_messages_filters_correctly(self, broker):
        """Should return only messages ready for retry"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        failed_key = f"failed:{consumer_group}:{stream}"
        current_time = time.time()

        # Add ready and not-ready messages
        ready_data = {
            "identifier": "ready_id",
            "message": json.dumps({"data": "ready"}),
            "retry_count": 1,
            "next_retry_time": str(current_time - 10),  # Past time
        }

        not_ready_data = {
            "identifier": "not_ready_id",
            "message": json.dumps({"data": "not_ready"}),
            "retry_count": 1,
            "next_retry_time": str(current_time + 60),  # Future time
        }

        broker.redis_instance.rpush(failed_key, json.dumps(ready_data))
        broker.redis_instance.rpush(failed_key, json.dumps(not_ready_data))

        # Get ready messages
        ready_messages = broker._get_retry_ready_messages(stream, consumer_group)

        assert len(ready_messages) == 1
        assert ready_messages[0][0] == "ready_id"

        # Not ready message should remain
        remaining = broker.redis_instance.lrange(failed_key, 0, -1)
        assert len(remaining) == 1
        remaining_data = json.loads(remaining[0])
        assert remaining_data["identifier"] == "not_ready_id"

    def test_remove_failed_message_finds_correct_message(self, broker):
        """Should remove only the specified failed message"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"

        failed_key = f"failed:{consumer_group}:{stream}"

        # Add multiple failed messages
        for i in range(3):
            failed_data = {
                "identifier": f"msg_{i}",
                "message": json.dumps({"data": f"test_{i}"}),
                "retry_count": 1,
                "next_retry_time": str(time.time()),
            }
            broker.redis_instance.rpush(failed_key, json.dumps(failed_data))

        # Remove middle message
        broker._remove_failed_message(stream, consumer_group, "msg_1")

        # Should have 2 messages left
        remaining = broker.redis_instance.lrange(failed_key, 0, -1)
        assert len(remaining) == 2

        # Check remaining messages
        remaining_ids = []
        for msg_json in remaining:
            msg_data = json.loads(msg_json)
            remaining_ids.append(msg_data["identifier"])

        assert "msg_0" in remaining_ids
        assert "msg_2" in remaining_ids
        assert "msg_1" not in remaining_ids


@pytest.mark.redis
class TestRedisUtilityMethods:
    """Test utility and helper methods"""

    def test_ensure_group_creates_group(self, broker):
        """_ensure_group should create consumer group if it doesn't exist"""
        group_name = "new_group"

        # Group shouldn't exist initially
        group_key = f"consumer_group:{group_name}"
        assert not broker.redis_instance.exists(group_key)

        # Create group
        broker._ensure_group(group_name)

        # Group should now exist
        assert broker.redis_instance.exists(group_key)
        group_info = broker.redis_instance.hgetall(group_key)
        assert b"created_at" in group_info or "created_at" in group_info

    def test_ensure_group_idempotent(self, broker):
        """_ensure_group should be idempotent (safe to call multiple times)"""
        group_name = "idempotent_group"

        # Create group twice
        broker._ensure_group(group_name)
        broker._ensure_group(group_name)

        # Should not cause errors and group should exist
        group_key = f"consumer_group:{group_name}"
        assert broker.redis_instance.exists(group_key)

    def test_data_reset_clears_all_data(self, broker):
        """_data_reset should clear all Redis data"""

        # Add some broker-related data
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"data": "test"}

        # Create typical broker data structures
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker._ensure_group(consumer_group)

        # Verify data exists
        assert broker.redis_instance.llen(stream) > 0
        position_key = f"position:{consumer_group}:{stream}"
        assert broker.redis_instance.exists(position_key)
        group_key = f"consumer_group:{consumer_group}"
        assert broker.redis_instance.exists(group_key)

        # Reset should clear everything
        broker._data_reset()

        # Verify all data is cleared
        assert broker.redis_instance.llen(stream) == 0
        assert not broker.redis_instance.exists(position_key)
        assert not broker.redis_instance.exists(group_key)

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
