"""Tests for RedisPubSubBroker capability declarations."""

import pytest

from protean.port.broker import BrokerCapabilities


@pytest.mark.redis
class TestRedisPubSubBrokerCapabilities:
    """Test capability methods specifically with Redis PubSub broker."""

    def test_capabilities(self, broker):
        """RedisPubSubBroker should have SIMPLE_QUEUING capabilities."""
        expected_caps = BrokerCapabilities.SIMPLE_QUEUING

        # Every flag the broker declares
        assert BrokerCapabilities.PUBLISH in broker.capabilities
        assert BrokerCapabilities.SUBSCRIBE in broker.capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS in broker.capabilities
        assert expected_caps in broker.capabilities

        # Should not have advanced capabilities
        assert BrokerCapabilities.ACK_NACK not in broker.capabilities
        assert BrokerCapabilities.MESSAGE_ORDERING not in broker.capabilities
        assert BrokerCapabilities.BLOCKING_READ not in broker.capabilities
        assert BrokerCapabilities.RELIABLE_MESSAGING not in broker.capabilities

        # At least one flag of a set
        assert bool(broker.capabilities & BrokerCapabilities.CONSUMER_GROUPS)
        assert bool(
            broker.capabilities
            & (BrokerCapabilities.CONSUMER_GROUPS | BrokerCapabilities.ACK_NACK)
        )
        assert not (
            broker.capabilities
            & (
                BrokerCapabilities.ACK_NACK
                | BrokerCapabilities.MESSAGE_ORDERING
                | BrokerCapabilities.STREAM_PARTITIONING
            )
        )
