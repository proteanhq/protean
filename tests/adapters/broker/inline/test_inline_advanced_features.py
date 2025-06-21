import time


class TestInlineBrokerAdvancedFeatures:
    """Test advanced features specific to InlineBroker implementation"""

    def test_message_ownership_tracking(self, broker):
        """Test that message ownership is correctly tracked in InlineBroker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "ownership"}

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)

        assert retrieved_message is not None
        assert retrieved_message[0] == identifier

        # Check internal ownership tracking
        assert hasattr(broker, "_message_ownership")
        assert identifier in broker._message_ownership
        assert consumer_group in broker._message_ownership[identifier]
        assert broker._message_ownership[identifier][consumer_group] is True

    def test_retry_count_tracking(self, broker):
        """Test internal retry count tracking in InlineBroker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "retry_count"}

        broker._retry_delay = 0.01

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # First nack
        broker.nack(stream, identifier, consumer_group)
        assert broker._get_retry_count(stream, consumer_group, identifier) == 1

        # Wait and get message again
        time.sleep(0.02)
        retry_message = broker.get_next(stream, consumer_group)
        assert retry_message is not None

        # Second nack
        broker.nack(stream, identifier, consumer_group)
        assert broker._get_retry_count(stream, consumer_group, identifier) == 2

    def test_consumer_position_tracking(self, broker):
        """Test consumer position tracking in InlineBroker"""
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

        # Check position tracking
        assert broker._consumer_positions[consumer_group_1][stream] == 1
        assert broker._consumer_positions[consumer_group_2][stream] == 0

        # Group 2 gets first message (same message)
        msg2 = broker.get_next(stream, consumer_group_2)
        assert msg2 is not None
        assert msg2[0] == ids[0]  # Same message
        assert broker._consumer_positions[consumer_group_2][stream] == 1

    def test_failed_messages_structure(self, broker):
        """Test the failed messages data structure in InlineBroker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "failed_structure"}

        broker._retry_delay = 0.01

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # Nack the message
        broker.nack(stream, identifier, consumer_group)

        # Check failed messages structure
        failed_msgs = broker._failed_messages[consumer_group][stream]
        assert len(failed_msgs) == 1

        # Structure: (identifier, message, retry_count, next_retry_time)
        failed_entry = failed_msgs[0]
        assert failed_entry[0] == identifier
        assert failed_entry[1] == message
        assert failed_entry[2] == 1  # retry count
        assert isinstance(failed_entry[3], float)  # next retry time

    def test_dlq_structure(self, broker):
        """Test the DLQ data structure in InlineBroker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "dlq_structure"}

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

        # Check DLQ structure
        assert hasattr(broker, "_dead_letter_queue")
        dlq_msgs = broker._dead_letter_queue[consumer_group][stream]
        assert len(dlq_msgs) == 1

        # Structure: (identifier, message, failure_reason, timestamp)
        dlq_entry = dlq_msgs[0]
        assert dlq_entry[0] == identifier
        assert dlq_entry[1] == message
        assert dlq_entry[2] == "max_retries_exceeded"
        assert isinstance(dlq_entry[3], float)  # timestamp

    def test_stale_message_cleanup(self, broker):
        """Test stale message cleanup mechanism in InlineBroker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "stale_cleanup"}

        broker._message_timeout = 0.1  # 100ms
        broker._enable_dlq = True

        # Publish and get message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # Check message is in-flight
        assert identifier in broker._in_flight[consumer_group][stream]

        # Wait for timeout
        time.sleep(0.15)

        # Trigger cleanup by getting next message
        broker.get_next(stream, consumer_group)

        # Check message was moved to DLQ
        assert identifier not in broker._in_flight[consumer_group][stream]
        dlq_msgs = broker._dead_letter_queue[consumer_group][stream]
        assert len(dlq_msgs) == 1
        assert dlq_msgs[0][0] == identifier
        assert dlq_msgs[0][2] == "timeout"

    def test_requeue_failed_messages_logic(self, broker):
        """Test the requeue logic for failed messages in InlineBroker"""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "requeue_logic"}

        broker._retry_delay = 0.01

        # Publish and nack message
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker.nack(stream, identifier, consumer_group)

        # Check message is in failed queue
        failed_msgs = broker._failed_messages[consumer_group][stream]
        assert len(failed_msgs) == 1

        # Wait for retry time
        time.sleep(0.02)

        # Trigger requeue by getting next message
        retry_message = broker.get_next(stream, consumer_group)

        # Check message was requeued
        assert retry_message is not None
        assert retry_message[0] == identifier

        # Check failed queue is now empty
        failed_msgs = broker._failed_messages[consumer_group][stream]
        assert len(failed_msgs) == 0

    def test_multiple_consumer_group_position_adjustment(self, broker):
        """Test position adjustment when messages are requeued affects all consumer groups"""
        stream = "test_stream"
        consumer_group_1 = "group_1"
        consumer_group_2 = "group_2"

        broker._retry_delay = 0.01

        # Publish multiple messages
        ids = []
        for i in range(3):
            identifier = broker.publish(stream, {"id": i})
            ids.append(identifier)

        # Group 1 gets and nacks first message
        broker.get_next(stream, consumer_group_1)
        broker.nack(stream, ids[0], consumer_group_1)

        # Group 2 gets first and second messages
        broker.get_next(stream, consumer_group_2)
        broker.get_next(stream, consumer_group_2)

        # Check initial positions
        assert broker._consumer_positions[consumer_group_1][stream] == 1
        assert broker._consumer_positions[consumer_group_2][stream] == 2

        # Wait for retry and trigger requeue
        time.sleep(0.02)
        broker.get_next(stream, consumer_group_1)  # This triggers requeue

        # Check that group 2's position was adjusted for the requeued message
        assert (
            broker._consumer_positions[consumer_group_2][stream] == 3
        )  # Incremented by 1
