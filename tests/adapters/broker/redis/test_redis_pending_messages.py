"""Tests for Redis Streams pending message handling and retry mechanisms."""

import pytest
import time
from uuid import uuid4

from protean.adapters.broker.redis import RedisBroker


@pytest.fixture
def redis_broker(test_domain):
    """Get the default Redis broker from test domain."""
    broker = test_domain.brokers["default"]
    # Ensure it's a Redis broker
    assert isinstance(broker, RedisBroker)
    return broker


@pytest.mark.redis
class TestRedisPendingMessages:
    """Test suite for Redis Streams pending message handling"""

    def test_read_returns_pending_before_new_messages(self, redis_broker):
        """Test that new messages are prioritized over pending messages"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"

        # Publish first message
        msg1 = {"data": "message_1", "order": 1}
        id1 = redis_broker.publish(stream, msg1)

        # Read but don't ACK (makes it pending)
        result1 = redis_broker.get_next(stream, consumer_group)
        assert result1 is not None
        assert result1[1] == msg1

        # Publish second message
        msg2 = {"data": "message_2", "order": 2}
        id2 = redis_broker.publish(stream, msg2)

        # Next read should return the NEW message (msg2) not the pending one (msg1)
        # This is the new behavior to avoid duplicate delivery
        result_next = redis_broker.get_next(stream, consumer_group)
        assert result_next is not None
        assert result_next[0] == id2  # Should be the second message
        assert result_next[1] == msg2

        # ACK both messages to clean up
        redis_broker.ack(stream, id1, consumer_group)
        redis_broker.ack(stream, id2, consumer_group)

        # Verify no more messages
        result_final = redis_broker.get_next(stream, consumer_group)
        assert result_final is None

    def test_read_blocking_returns_pending_before_new(self, redis_broker):
        """Test that read_blocking returns pending messages before new messages"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"
        consumer_name = f"consumer_{uuid4().hex[:8]}"

        # Publish first message
        msg1 = {"data": "blocking_message_1"}
        id1 = redis_broker.publish(stream, msg1)

        # Read with specific consumer but don't ACK
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert len(messages) == 1
        assert messages[0][1] == msg1

        # Publish second message
        msg2 = {"data": "blocking_message_2"}
        id2 = redis_broker.publish(stream, msg2)

        # Read again with same consumer - should get pending msg1 first
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert len(messages) == 1
        assert messages[0][0] == id1  # Should be first message
        assert messages[0][1] == msg1

        # ACK the first message
        redis_broker.ack(stream, id1, consumer_group)

        # Now should get the second message
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert len(messages) == 1
        assert messages[0][0] == id2
        assert messages[0][1] == msg2

    def test_multiple_pending_messages_returned(self, redis_broker):
        """Test that new messages are prioritized over pending ones"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"

        # Publish multiple messages
        messages = []
        ids = []
        for i in range(5):
            msg = {"data": f"message_{i}", "index": i}
            msg_id = redis_broker.publish(stream, msg)
            messages.append(msg)
            ids.append(msg_id)

        # Read all but don't ACK any
        read_messages = redis_broker.read(stream, consumer_group, 5)
        assert len(read_messages) == 5

        # All messages are now pending, but _get_next won't return them
        # because it prioritizes new messages to avoid duplicates
        pending_result = redis_broker.get_next(stream, consumer_group)
        # Should return None since there are no new messages
        assert pending_result is None

        # Publish a new message
        new_msg = {"data": "new_message", "index": 99}
        new_id = redis_broker.publish(stream, new_msg)

        # Now get_next should return the new message, not the pending ones
        result = redis_broker.get_next(stream, consumer_group)
        assert result is not None
        assert result[0] == new_id
        assert result[1] == new_msg

    def test_nack_keeps_message_pending(self, redis_broker):
        """Test that NACK keeps message in pending state for retry"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"

        # Publish message
        msg = {"data": "nack_test"}
        msg_id = redis_broker.publish(stream, msg)

        # Read message
        result = redis_broker.get_next(stream, consumer_group)
        assert result is not None

        # NACK the message
        nack_success = redis_broker.nack(stream, msg_id, consumer_group)
        assert nack_success is True

        # Message is still pending but won't be returned by get_next
        # because get_next prioritizes new messages
        result2 = redis_broker.get_next(stream, consumer_group)
        assert result2 is None  # No new messages

        # Verify it's still in pending list via info
        info = redis_broker.info()
        assert stream in info["consumer_groups"]
        assert consumer_group in info["consumer_groups"][stream]
        assert info["consumer_groups"][stream][consumer_group]["pending"] > 0

    def test_ack_removes_from_pending(self, redis_broker):
        """Test that ACK removes message from pending list"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"

        # Publish message
        msg = {"data": "ack_test"}
        msg_id = redis_broker.publish(stream, msg)

        # Read message
        result = redis_broker.get_next(stream, consumer_group)
        assert result is not None

        # Check pending count before ACK
        info = redis_broker.info()
        pending_before = info["consumer_groups"][stream][consumer_group]["pending"]
        assert pending_before > 0

        # ACK the message
        ack_success = redis_broker.ack(stream, msg_id, consumer_group)
        assert ack_success is True

        # Check pending count after ACK
        info = redis_broker.info()
        pending_after = info["consumer_groups"][stream][consumer_group]["pending"]
        assert pending_after == 0

        # Reading again should return None (no messages)
        result2 = redis_broker.get_next(stream, consumer_group)
        assert result2 is None

    def test_read_blocking_with_timeout_and_pending(self, redis_broker):
        """Test read_blocking timeout behavior with pending messages"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"
        consumer_name = f"consumer_{uuid4().hex[:8]}"

        # Ensure stream is empty initially
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert messages == []  # Should timeout with no messages

        # Publish and read without ACK
        msg = {"data": "timeout_test"}
        msg_id = redis_broker.publish(stream, msg)

        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert len(messages) == 1

        # Now message is pending, read_blocking should return it immediately
        start_time = time.time()
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=5000, count=1
        )
        elapsed = time.time() - start_time

        # Should return immediately without waiting for timeout
        assert elapsed < 1.0  # Much less than 5 second timeout
        assert len(messages) == 1
        assert messages[0][0] == msg_id

    def test_consumer_isolation_with_pending(self, redis_broker):
        """Test that pending messages are isolated per consumer"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"
        consumer1 = f"consumer1_{uuid4().hex[:8]}"
        consumer2 = f"consumer2_{uuid4().hex[:8]}"

        # Publish two messages
        msg1 = {"data": "msg_for_consumer1"}
        msg2 = {"data": "msg_for_consumer2"}
        id1 = redis_broker.publish(stream, msg1)
        id2 = redis_broker.publish(stream, msg2)

        # Consumer1 reads first message
        messages1 = redis_broker.read_blocking(
            stream, consumer_group, consumer1, timeout_ms=100, count=1
        )
        assert len(messages1) == 1
        assert messages1[0][0] == id1

        # Consumer2 reads second message
        messages2 = redis_broker.read_blocking(
            stream, consumer_group, consumer2, timeout_ms=100, count=1
        )
        assert len(messages2) == 1
        assert messages2[0][0] == id2

        # Each consumer re-reading should get their own pending message
        messages1_retry = redis_broker.read_blocking(
            stream, consumer_group, consumer1, timeout_ms=100, count=1
        )
        assert len(messages1_retry) == 1
        assert messages1_retry[0][0] == id1  # Consumer1 gets msg1 again

        messages2_retry = redis_broker.read_blocking(
            stream, consumer_group, consumer2, timeout_ms=100, count=1
        )
        assert len(messages2_retry) == 1
        assert messages2_retry[0][0] == id2  # Consumer2 gets msg2 again

    def test_pending_messages_with_read_multiple(self, redis_broker):
        """Test read() method with multiple pending messages"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"

        # Publish 10 messages
        published_msgs = []
        published_ids = []
        for i in range(10):
            msg = {"data": f"batch_{i}", "index": i}
            msg_id = redis_broker.publish(stream, msg)
            published_msgs.append(msg)
            published_ids.append(msg_id)

        # Read first 5 but don't ACK
        batch1 = redis_broker.read(stream, consumer_group, 5)
        assert len(batch1) == 5
        batch1_ids = {msg[0] for msg in batch1}

        # Read again with count=3 - will get new messages first, not pending
        batch2 = redis_broker.read(stream, consumer_group, 3)
        # With the updated _read implementation, new messages are prioritized
        # So batch2 should contain new messages (indices 5, 6, 7)
        if len(batch2) > 0:
            batch2_ids = {msg[0] for msg in batch2}
            # Should NOT overlap with batch1 since we read new messages first
            assert len(batch2_ids.intersection(batch1_ids)) == 0
            # Should be the next messages in sequence
            assert all(msg[1]["index"] >= 5 for msg in batch2)

        # ACK all read messages to clear pending
        for msg_id, _ in batch1:
            redis_broker.ack(stream, msg_id, consumer_group)
        for msg_id, _ in batch2:
            redis_broker.ack(stream, msg_id, consumer_group)

        # Read again - should get remaining new messages
        batch3 = redis_broker.read(stream, consumer_group, 3)
        # We've read 8 messages (5 + 3), so only 2 remain from the 10 total
        assert len(batch3) == 2  # Only 2 messages left (indices 8, 9)
        batch3_ids = {msg[0] for msg in batch3}
        # These should be different from what we already ACKed
        acked_ids = batch1_ids.union({msg[0] for msg in batch2})
        assert len(batch3_ids.intersection(acked_ids)) == 0
        # Should be the last messages
        assert all(msg[1]["index"] >= 8 for msg in batch3)

    def test_pending_message_with_specific_consumer(self, redis_broker, test_domain):
        """Test that pending messages are tied to specific consumers"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"
        consumer_name = f"specific_consumer_{uuid4().hex[:8]}"

        # Publish and read with a specific consumer without ACK
        msg = {"data": "persistent_pending"}
        msg_id = redis_broker.publish(stream, msg)

        # Read with specific consumer name
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert len(messages) == 1

        # Create a new broker instance
        new_broker = RedisBroker("test_new", test_domain, redis_broker.conn_info)

        # The pending message should be available to the same consumer
        messages2 = new_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert len(messages2) == 1
        assert messages2[0][0] == msg_id
        assert messages2[0][1] == msg

        # But not available to a different consumer
        different_consumer = f"different_{uuid4().hex[:8]}"
        messages3 = new_broker.read_blocking(
            stream, consumer_group, different_consumer, timeout_ms=100, count=1
        )
        assert len(messages3) == 0  # No messages for different consumer

    def test_empty_pending_messages(self, redis_broker):
        """Test behavior when there are no pending messages"""
        stream = f"test_stream_{uuid4().hex[:8]}"
        consumer_group = f"test_group_{uuid4().hex[:8]}"
        consumer_name = f"consumer_{uuid4().hex[:8]}"

        # Try to read with no messages at all
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert messages == []

        # Publish and ACK a message
        msg = {"data": "acked_message"}
        msg_id = redis_broker.publish(stream, msg)
        result = redis_broker.get_next(stream, consumer_group)
        assert result is not None
        redis_broker.ack(stream, msg_id, consumer_group)

        # No pending messages, no new messages
        messages = redis_broker.read_blocking(
            stream, consumer_group, consumer_name, timeout_ms=100, count=1
        )
        assert messages == []
