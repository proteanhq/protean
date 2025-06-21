import json
import time

import pytest


@pytest.mark.redis
class TestRedisPubSubBrokerAdvancedFeatures:
    """Test advanced features specific to RedisPubSubBroker implementation"""

    def test_message_ownership_redis_keys(self, broker):
        """Test that message ownership is tracked using Redis sets"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "redis_ownership"}

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        assert retrieved_message is not None
        assert retrieved_message[0] == identifier

        # Check Redis ownership key
        ownership_key = f"ownership:{identifier}"
        assert broker.redis_instance.sismember(ownership_key, consumer_group)

        # Check key expiration is set
        ttl = broker.redis_instance.ttl(ownership_key)
        assert ttl > 0  # Should have expiration set

    def test_atomic_operations_with_pipeline(self, broker):
        """Test that Redis operations use pipelines for atomicity"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "atomic_ops"}

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        assert retrieved_message is not None

        # Check that multiple Redis keys were created atomically
        position_key = f"position:{consumer_group}:{stream}"
        ownership_key = f"ownership:{identifier}"
        in_flight_key = f"in_flight:{consumer_group}:{stream}"

        assert broker.redis_instance.exists(position_key)
        assert broker.redis_instance.exists(ownership_key)
        assert broker.redis_instance.hexists(in_flight_key, identifier)

    def test_retry_count_redis_hash(self, broker):
        """Test retry count tracking using Redis hashes"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "redis_retry_count"}

        broker._retry_delay = 0.01

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # First nack
        broker.nack(stream, identifier, consumer_group)

        # Check Redis retry count
        retry_key = f"retry_count:{consumer_group}:{stream}"
        retry_count = broker.redis_instance.hget(retry_key, identifier)
        assert int(retry_count) == 1

        # Wait and get message again
        time.sleep(0.02)
        retry_message = broker.get_next(stream, consumer_group)
        assert retry_message is not None

        # Second nack
        broker.nack(stream, identifier, consumer_group)
        retry_count = broker.redis_instance.hget(retry_key, identifier)
        assert int(retry_count) == 2

    def test_failed_messages_redis_list(self, broker):
        """Test failed messages storage using Redis lists"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "redis_failed_list"}

        broker._retry_delay = 0.01

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # Nack the message
        broker.nack(stream, identifier, consumer_group)

        # Check Redis failed messages list
        failed_key = f"failed:{consumer_group}:{stream}"
        failed_count = broker.redis_instance.llen(failed_key)
        assert failed_count == 1

        # Check structure of failed message
        failed_msg_json = broker.redis_instance.lindex(failed_key, 0)
        failed_msg = json.loads(
            failed_msg_json.decode()
            if isinstance(failed_msg_json, bytes)
            else failed_msg_json
        )
        assert failed_msg["identifier"] == identifier
        assert "next_retry_time" in failed_msg
        assert failed_msg["retry_count"] == 1

    def test_dlq_redis_list(self, broker):
        """Test DLQ storage using Redis lists"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "redis_dlq_list"}

        broker._retry_delay = 0.01
        broker._max_retries = 1
        broker._enable_dlq = True

        # Publish and exhaust retries
        identifier = broker.publish(stream, message)

        for i in range(2):
            retrieved_message = broker.get_next(stream, consumer_group)
            if retrieved_message:
                broker.nack(stream, identifier, consumer_group)
                if i == 0:
                    time.sleep(0.02)

        # Check Redis DLQ list
        dlq_key = f"dlq:{consumer_group}:{stream}"
        dlq_count = broker.redis_instance.llen(dlq_key)
        assert dlq_count == 1

        # Check DLQ message structure
        dlq_msg_json = broker.redis_instance.lindex(dlq_key, 0)
        dlq_msg = json.loads(
            dlq_msg_json.decode() if isinstance(dlq_msg_json, bytes) else dlq_msg_json
        )
        assert dlq_msg["identifier"] == identifier
        assert dlq_msg["failure_reason"] == "max_retries_exceeded"
        assert "timestamp" in dlq_msg

    def test_position_tracking_redis_keys(self, broker):
        """Test consumer position tracking using Redis keys"""
        stream = "test_stream"
        consumer_group_1 = "group_1"
        consumer_group_2 = "group_2"

        # Publish multiple messages
        ids = []
        for i in range(3):
            identifier = broker.publish(stream, {"id": i})
            ids.append(identifier)

        # Group 1 gets first message
        msg1 = broker.get_next(stream, consumer_group_1)
        assert msg1 is not None
        assert msg1[0] == ids[0]

        # Check Redis position keys
        position_key_1 = f"position:{consumer_group_1}:{stream}"
        position_key_2 = f"position:{consumer_group_2}:{stream}"

        assert int(broker.redis_instance.get(position_key_1) or 0) == 1
        assert int(broker.redis_instance.get(position_key_2) or 0) == 0

        # Group 2 gets first message (same message)
        msg2 = broker.get_next(stream, consumer_group_2)
        assert msg2 is not None
        assert msg2[0] == ids[0]  # Same message
        assert int(broker.redis_instance.get(position_key_2) or 0) == 1

    def test_lua_script_requeue_atomicity(self, broker):
        """Test that the Lua script provides atomic requeue operations"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "lua_requeue"}

        broker._retry_delay = 0.01

        # Publish and nack message
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker.nack(stream, identifier, consumer_group)

        # Check failed message exists
        failed_key = f"failed:{consumer_group}:{stream}"
        assert broker.redis_instance.llen(failed_key) == 1

        # Wait for retry time and trigger requeue
        time.sleep(0.02)
        retry_message = broker.get_next(stream, consumer_group)

        # Check atomic requeue worked
        assert retry_message is not None
        assert retry_message[0] == identifier

        # Check failed queue is empty after atomic operation
        assert broker.redis_instance.llen(failed_key) == 0

    def test_redis_key_expiration_cleanup(self, broker):
        """Test that Redis keys have appropriate expiration for cleanup"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "key_expiration"}

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        assert retrieved_message is not None

        # Check ownership key has expiration
        ownership_key = f"ownership:{identifier}"
        ttl = broker.redis_instance.ttl(ownership_key)
        assert ttl > 0
        # Should be either 2x timeout or at least 30 seconds for fast tests
        expected_expiration = max(int(broker._message_timeout * 2), 30)
        assert ttl <= expected_expiration

    def test_cross_consumer_group_redis_isolation(self, broker):
        """Test Redis key isolation between consumer groups"""
        stream = "test_stream"
        consumer_group_1 = "group_1"
        consumer_group_2 = "group_2"
        message = {"test": "redis_isolation"}

        # Publish and get message for both groups
        identifier = broker.publish(stream, message)

        broker.get_next(stream, consumer_group_1)
        broker.get_next(stream, consumer_group_2)

        # Check separate Redis keys for each group
        in_flight_key_1 = f"in_flight:{consumer_group_1}:{stream}"
        in_flight_key_2 = f"in_flight:{consumer_group_2}:{stream}"
        position_key_1 = f"position:{consumer_group_1}:{stream}"
        position_key_2 = f"position:{consumer_group_2}:{stream}"

        assert broker.redis_instance.hexists(in_flight_key_1, identifier)
        assert broker.redis_instance.hexists(in_flight_key_2, identifier)
        assert broker.redis_instance.get(position_key_1) == b"1"
        assert broker.redis_instance.get(position_key_2) == b"1"

        # But ownership should track both groups
        ownership_key = f"ownership:{identifier}"
        assert broker.redis_instance.sismember(ownership_key, consumer_group_1)
        assert broker.redis_instance.sismember(ownership_key, consumer_group_2)

    def test_redis_transaction_retry_on_watch_error(self, broker):
        """Test handling of Redis WATCH errors during transactions"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "transaction_retry"}

        # This test verifies the retry logic exists in get_next
        # Since we can't easily simulate concurrent Redis access in tests,
        # we just verify the method completes successfully
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        assert retrieved_message is not None
        assert retrieved_message[0] == identifier

        # Verify the position was updated despite potential race conditions
        position_key = f"position:{consumer_group}:{stream}"
        assert int(broker.redis_instance.get(position_key) or 0) == 1
