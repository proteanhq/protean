from protean.port.broker import BrokerCapabilities


class TestBrokerCapabilities:
    """Test suite for BrokerCapabilities flag operations"""

    def test_individual_capabilities(self):
        """Test individual capability flags"""
        assert BrokerCapabilities.PUBLISH
        assert BrokerCapabilities.SUBSCRIBE
        assert BrokerCapabilities.CONSUMER_GROUPS
        assert BrokerCapabilities.ACK_NACK
        assert BrokerCapabilities.DELIVERY_GUARANTEES
        assert BrokerCapabilities.MESSAGE_ORDERING
        assert BrokerCapabilities.BLOCKING_READ
        assert BrokerCapabilities.DEAD_LETTER_QUEUE
        assert BrokerCapabilities.REPLAY
        assert BrokerCapabilities.STREAM_PARTITIONING
        assert BrokerCapabilities.STREAM_RETENTION

    def test_capability_combination(self):
        """Test combining capabilities using bitwise operations"""
        basic_capabilities = BrokerCapabilities.PUBLISH | BrokerCapabilities.SUBSCRIBE
        assert BrokerCapabilities.PUBLISH in basic_capabilities
        assert BrokerCapabilities.SUBSCRIBE in basic_capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS not in basic_capabilities

    def test_basic_pubsub_capability_set(self):
        """Test BASIC_PUBSUB capability set"""
        capabilities = BrokerCapabilities.BASIC_PUBSUB
        assert BrokerCapabilities.PUBLISH in capabilities
        assert BrokerCapabilities.SUBSCRIBE in capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS not in capabilities

    def test_simple_queuing_capability_set(self):
        """Test SIMPLE_QUEUING capability set"""
        capabilities = BrokerCapabilities.SIMPLE_QUEUING
        assert BrokerCapabilities.PUBLISH in capabilities
        assert BrokerCapabilities.SUBSCRIBE in capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS in capabilities
        assert BrokerCapabilities.ACK_NACK not in capabilities

    def test_reliable_messaging_capability_set(self):
        """Test RELIABLE_MESSAGING capability set"""
        capabilities = BrokerCapabilities.RELIABLE_MESSAGING
        assert BrokerCapabilities.PUBLISH in capabilities
        assert BrokerCapabilities.SUBSCRIBE in capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS in capabilities
        assert BrokerCapabilities.ACK_NACK in capabilities
        assert BrokerCapabilities.DELIVERY_GUARANTEES in capabilities
        assert BrokerCapabilities.MESSAGE_ORDERING not in capabilities

    def test_ordered_messaging_capability_set(self):
        """Test ORDERED_MESSAGING capability set"""
        capabilities = BrokerCapabilities.ORDERED_MESSAGING
        assert BrokerCapabilities.PUBLISH in capabilities
        assert BrokerCapabilities.SUBSCRIBE in capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS in capabilities
        assert BrokerCapabilities.ACK_NACK in capabilities
        assert BrokerCapabilities.DELIVERY_GUARANTEES in capabilities
        assert BrokerCapabilities.MESSAGE_ORDERING in capabilities
        assert BrokerCapabilities.DEAD_LETTER_QUEUE not in capabilities

    def test_enterprise_streaming_capability_set(self):
        """Test ENTERPRISE_STREAMING capability set"""
        capabilities = BrokerCapabilities.ENTERPRISE_STREAMING
        assert BrokerCapabilities.PUBLISH in capabilities
        assert BrokerCapabilities.SUBSCRIBE in capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS in capabilities
        assert BrokerCapabilities.ACK_NACK in capabilities
        assert BrokerCapabilities.DELIVERY_GUARANTEES in capabilities
        assert BrokerCapabilities.MESSAGE_ORDERING in capabilities
        assert BrokerCapabilities.BLOCKING_READ in capabilities
        assert BrokerCapabilities.DEAD_LETTER_QUEUE in capabilities
        assert BrokerCapabilities.REPLAY in capabilities
        assert BrokerCapabilities.STREAM_PARTITIONING in capabilities
        assert BrokerCapabilities.STREAM_RETENTION in capabilities

    def test_capability_hierarchy(self):
        """Test that higher capability sets include lower ones"""
        # SIMPLE_QUEUING should include BASIC_PUBSUB
        simple = BrokerCapabilities.SIMPLE_QUEUING
        basic_pubsub = BrokerCapabilities.BASIC_PUBSUB
        assert (simple & basic_pubsub) == basic_pubsub

        # RELIABLE_MESSAGING should include SIMPLE_QUEUING
        reliable = BrokerCapabilities.RELIABLE_MESSAGING
        assert (reliable & simple) == simple

        # ORDERED_MESSAGING should include RELIABLE_MESSAGING
        ordered = BrokerCapabilities.ORDERED_MESSAGING
        assert (ordered & reliable) == reliable

        # ENTERPRISE_STREAMING should include ORDERED_MESSAGING
        enterprise = BrokerCapabilities.ENTERPRISE_STREAMING
        assert (enterprise & ordered) == ordered

    def test_capability_subtraction(self):
        """Test removing capabilities from a set"""
        full_capabilities = BrokerCapabilities.ENTERPRISE_STREAMING
        without_dlq = full_capabilities & ~BrokerCapabilities.DEAD_LETTER_QUEUE

        assert BrokerCapabilities.PUBLISH in without_dlq
        assert BrokerCapabilities.DEAD_LETTER_QUEUE not in without_dlq
        assert BrokerCapabilities.REPLAY in without_dlq

    def test_capability_checks_with_flag_operators(self):
        """`in` checks every flag of a set, and `&` finds a shared flag."""
        reliable = BrokerCapabilities.RELIABLE_MESSAGING

        # Should have individual capabilities
        assert BrokerCapabilities.PUBLISH in reliable
        assert BrokerCapabilities.ACK_NACK in reliable
        assert BrokerCapabilities.REPLAY not in reliable

        # Should have all basic capabilities
        basic = BrokerCapabilities.PUBLISH | BrokerCapabilities.SUBSCRIBE
        assert basic in reliable

        # Should have some advanced capabilities
        advanced = BrokerCapabilities.REPLAY | BrokerCapabilities.ACK_NACK
        assert (reliable & advanced) == BrokerCapabilities.ACK_NACK

        # Should not have all advanced capabilities
        assert advanced not in reliable

        # Shares no flag with a set it lacks entirely
        assert not reliable & (
            BrokerCapabilities.REPLAY | BrokerCapabilities.STREAM_PARTITIONING
        )

        # The empty set is in every set and shares no flag with any
        assert BrokerCapabilities(0) in reliable
        assert not reliable & BrokerCapabilities(0)

    def test_capability_set_completeness(self):
        """Test that predefined capability sets are complete"""
        # Test that BASIC_PUBSUB is complete
        basic_pubsub = BrokerCapabilities.BASIC_PUBSUB
        expected = BrokerCapabilities.PUBLISH | BrokerCapabilities.SUBSCRIBE
        assert basic_pubsub == expected

        # Test that SIMPLE_QUEUING is complete
        simple = BrokerCapabilities.SIMPLE_QUEUING
        expected = BrokerCapabilities.BASIC_PUBSUB | BrokerCapabilities.CONSUMER_GROUPS
        assert simple == expected

        # Test that RELIABLE_MESSAGING is complete
        reliable = BrokerCapabilities.RELIABLE_MESSAGING
        expected = (
            BrokerCapabilities.SIMPLE_QUEUING
            | BrokerCapabilities.ACK_NACK
            | BrokerCapabilities.DELIVERY_GUARANTEES
        )
        assert reliable == expected
