import pytest

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

    def test_capability_checking_methods(self):
        """Test methods for checking if capabilities are present"""

        def has_capability(broker_caps, required_cap):
            return required_cap in broker_caps

        def has_all_capabilities(broker_caps, required_caps):
            return (broker_caps & required_caps) == required_caps

        def has_any_capability(broker_caps, required_caps):
            return bool(broker_caps & required_caps)

        # Test with reliable messaging
        reliable = BrokerCapabilities.RELIABLE_MESSAGING

        # Should have individual capabilities
        assert has_capability(reliable, BrokerCapabilities.PUBLISH)
        assert has_capability(reliable, BrokerCapabilities.ACK_NACK)
        assert not has_capability(reliable, BrokerCapabilities.REPLAY)

        # Should have all basic capabilities
        basic = BrokerCapabilities.PUBLISH | BrokerCapabilities.SUBSCRIBE
        assert has_all_capabilities(reliable, basic)

        # Should have some advanced capabilities
        advanced = BrokerCapabilities.REPLAY | BrokerCapabilities.ACK_NACK
        assert has_any_capability(reliable, advanced)

        # Should not have all advanced capabilities
        assert not has_all_capabilities(reliable, advanced)

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


class TestBrokerCapabilityMethods:
    """Test suite for broker capability checking methods on actual broker instances"""

    def test_has_all_capabilities(self, broker):
        """Test has_all_capabilities method with various capability combinations."""
        broker_caps = broker.capabilities

        # Test with capabilities the broker has
        if (
            BrokerCapabilities.PUBLISH in broker_caps
            and BrokerCapabilities.SUBSCRIBE in broker_caps
        ):
            assert broker.has_all_capabilities(
                BrokerCapabilities.PUBLISH | BrokerCapabilities.SUBSCRIBE
            )
            assert broker.has_all_capabilities(BrokerCapabilities.BASIC_PUBSUB)

        # Test with single capability
        if BrokerCapabilities.PUBLISH in broker_caps:
            assert broker.has_all_capabilities(BrokerCapabilities.PUBLISH)

        # Test with capabilities the broker doesn't have
        if BrokerCapabilities.REPLAY not in broker_caps:
            assert not broker.has_all_capabilities(BrokerCapabilities.REPLAY)
            assert not broker.has_all_capabilities(
                BrokerCapabilities.PUBLISH | BrokerCapabilities.REPLAY
            )

        # Test with empty capabilities (should always return True)
        assert broker.has_all_capabilities(BrokerCapabilities(0))

        # Test with all broker's capabilities
        assert broker.has_all_capabilities(broker_caps)

        # Test with more capabilities than broker has
        all_caps = BrokerCapabilities.ENTERPRISE_STREAMING
        if broker_caps != all_caps:
            assert not broker.has_all_capabilities(all_caps)

    def test_has_any_capability(self, broker):
        """Test has_any_capability method with various capability combinations."""
        broker_caps = broker.capabilities

        # Test with capabilities the broker has
        if BrokerCapabilities.PUBLISH in broker_caps:
            assert broker.has_any_capability(BrokerCapabilities.PUBLISH)
            assert broker.has_any_capability(
                BrokerCapabilities.PUBLISH | BrokerCapabilities.REPLAY
            )

        # Test with multiple capabilities where at least one matches
        if BrokerCapabilities.SUBSCRIBE in broker_caps:
            assert broker.has_any_capability(
                BrokerCapabilities.SUBSCRIBE
                | BrokerCapabilities.REPLAY
                | BrokerCapabilities.STREAM_PARTITIONING
            )

        # Test with capabilities the broker doesn't have
        caps_to_test = BrokerCapabilities(0)
        if BrokerCapabilities.REPLAY not in broker_caps:
            caps_to_test |= BrokerCapabilities.REPLAY
        if BrokerCapabilities.STREAM_PARTITIONING not in broker_caps:
            caps_to_test |= BrokerCapabilities.STREAM_PARTITIONING

        if caps_to_test:
            assert not broker.has_any_capability(caps_to_test)

        # Test with empty capabilities (should return False)
        assert not broker.has_any_capability(BrokerCapabilities(0))

        # Test with all capabilities - should return True for any broker
        assert broker.has_any_capability(BrokerCapabilities.ENTERPRISE_STREAMING)

    def test_capability_methods_with_inline_broker(self, broker):
        """Test capability methods specifically with inline broker."""
        if broker.__class__.__name__ != "InlineBroker":
            pytest.skip("Test specific to InlineBroker")

        # InlineBroker has RELIABLE_MESSAGING capabilities
        expected_caps = BrokerCapabilities.RELIABLE_MESSAGING

        # Test has_all_capabilities
        assert broker.has_all_capabilities(BrokerCapabilities.PUBLISH)
        assert broker.has_all_capabilities(BrokerCapabilities.SUBSCRIBE)
        assert broker.has_all_capabilities(BrokerCapabilities.CONSUMER_GROUPS)
        assert broker.has_all_capabilities(BrokerCapabilities.ACK_NACK)
        assert broker.has_all_capabilities(BrokerCapabilities.DELIVERY_GUARANTEES)
        assert broker.has_all_capabilities(expected_caps)

        # Should not have advanced capabilities
        assert not broker.has_all_capabilities(BrokerCapabilities.MESSAGE_ORDERING)
        assert not broker.has_all_capabilities(BrokerCapabilities.REPLAY)
        assert not broker.has_all_capabilities(BrokerCapabilities.ENTERPRISE_STREAMING)

        # Test has_any_capability
        assert broker.has_any_capability(BrokerCapabilities.PUBLISH)
        assert broker.has_any_capability(
            BrokerCapabilities.ACK_NACK | BrokerCapabilities.REPLAY
        )
        assert not broker.has_any_capability(
            BrokerCapabilities.REPLAY | BrokerCapabilities.STREAM_PARTITIONING
        )

    def test_capability_methods_with_redis_broker(self, broker):
        """Test capability methods specifically with Redis broker."""
        if broker.__class__.__name__ != "RedisBroker":
            pytest.skip("Test specific to RedisBroker")

        # RedisBroker has ORDERED_MESSAGING | BLOCKING_READ capabilities
        expected_caps = (
            BrokerCapabilities.ORDERED_MESSAGING | BrokerCapabilities.BLOCKING_READ
        )

        # Test has_all_capabilities
        assert broker.has_all_capabilities(BrokerCapabilities.PUBLISH)
        assert broker.has_all_capabilities(BrokerCapabilities.SUBSCRIBE)
        assert broker.has_all_capabilities(BrokerCapabilities.CONSUMER_GROUPS)
        assert broker.has_all_capabilities(BrokerCapabilities.ACK_NACK)
        assert broker.has_all_capabilities(BrokerCapabilities.DELIVERY_GUARANTEES)
        assert broker.has_all_capabilities(BrokerCapabilities.MESSAGE_ORDERING)
        assert broker.has_all_capabilities(BrokerCapabilities.BLOCKING_READ)
        assert broker.has_all_capabilities(expected_caps)

        # Should not have some advanced capabilities
        assert not broker.has_all_capabilities(BrokerCapabilities.REPLAY)
        assert not broker.has_all_capabilities(BrokerCapabilities.DEAD_LETTER_QUEUE)
        assert not broker.has_all_capabilities(BrokerCapabilities.ENTERPRISE_STREAMING)

        # Test has_any_capability
        assert broker.has_any_capability(BrokerCapabilities.MESSAGE_ORDERING)
        assert broker.has_any_capability(
            BrokerCapabilities.BLOCKING_READ | BrokerCapabilities.REPLAY
        )
        assert not broker.has_any_capability(
            BrokerCapabilities.REPLAY
            | BrokerCapabilities.DEAD_LETTER_QUEUE
            | BrokerCapabilities.STREAM_PARTITIONING
        )

    def test_capability_methods_with_redis_pubsub_broker(self, broker):
        """Test capability methods specifically with Redis PubSub broker."""
        if broker.__class__.__name__ != "RedisPubSubBroker":
            pytest.skip("Test specific to RedisPubSubBroker")

        # RedisPubSubBroker has SIMPLE_QUEUING capabilities
        expected_caps = BrokerCapabilities.SIMPLE_QUEUING

        # Test has_all_capabilities
        assert broker.has_all_capabilities(BrokerCapabilities.PUBLISH)
        assert broker.has_all_capabilities(BrokerCapabilities.SUBSCRIBE)
        assert broker.has_all_capabilities(BrokerCapabilities.CONSUMER_GROUPS)
        assert broker.has_all_capabilities(expected_caps)

        # Should not have advanced capabilities
        assert not broker.has_all_capabilities(BrokerCapabilities.ACK_NACK)
        assert not broker.has_all_capabilities(BrokerCapabilities.MESSAGE_ORDERING)
        assert not broker.has_all_capabilities(BrokerCapabilities.BLOCKING_READ)
        assert not broker.has_all_capabilities(BrokerCapabilities.RELIABLE_MESSAGING)

        # Test has_any_capability
        assert broker.has_any_capability(BrokerCapabilities.CONSUMER_GROUPS)
        assert broker.has_any_capability(
            BrokerCapabilities.CONSUMER_GROUPS | BrokerCapabilities.ACK_NACK
        )
        assert not broker.has_any_capability(
            BrokerCapabilities.ACK_NACK
            | BrokerCapabilities.MESSAGE_ORDERING
            | BrokerCapabilities.REPLAY
        )

    def test_combined_capability_checks(self, broker):
        """Test checking combinations of capabilities."""
        # Every broker should support basic pub/sub
        assert broker.has_capability(BrokerCapabilities.PUBLISH)
        assert broker.has_capability(BrokerCapabilities.SUBSCRIBE)

        # Test has_all_capabilities with basic operations
        assert broker.has_all_capabilities(BrokerCapabilities.PUBLISH)
        assert broker.has_all_capabilities(BrokerCapabilities.SUBSCRIBE)
        assert broker.has_all_capabilities(BrokerCapabilities.BASIC_PUBSUB)

        # Test has_any_capability with mixed capabilities
        assert broker.has_any_capability(
            BrokerCapabilities.PUBLISH | BrokerCapabilities.REPLAY
        )
        assert broker.has_any_capability(
            BrokerCapabilities.SUBSCRIBE | BrokerCapabilities.STREAM_PARTITIONING
        )

        # Complex combination tests
        if broker.has_capability(BrokerCapabilities.CONSUMER_GROUPS):
            # If broker has consumer groups, test related capabilities
            assert broker.has_all_capabilities(BrokerCapabilities.CONSUMER_GROUPS)
            assert broker.has_any_capability(
                BrokerCapabilities.CONSUMER_GROUPS
                | BrokerCapabilities.DEAD_LETTER_QUEUE
            )

            if broker.has_capability(BrokerCapabilities.ACK_NACK):
                # If broker has ACK/NACK, it should have consumer groups too
                assert broker.has_all_capabilities(
                    BrokerCapabilities.CONSUMER_GROUPS | BrokerCapabilities.ACK_NACK
                )
