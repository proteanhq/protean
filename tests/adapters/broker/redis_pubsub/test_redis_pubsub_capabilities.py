"""Tests for RedisPubSubBroker capability declarations."""

import pytest

from protean.port.broker import BrokerCapabilities


@pytest.mark.redis
class TestRedisPubSubBrokerCapabilities:
    """Test capability methods specifically with Redis PubSub broker."""

    def test_capabilities(self, broker):
        """RedisPubSubBroker should have SIMPLE_QUEUING capabilities."""
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
