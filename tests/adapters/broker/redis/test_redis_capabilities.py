"""Tests for RedisBroker capability declarations."""

import pytest

from protean.port.broker import BrokerCapabilities


@pytest.mark.redis
class TestRedisBrokerCapabilities:
    """Test capability methods specifically with Redis broker."""

    def test_capabilities(self, broker):
        """RedisBroker should have ORDERED_MESSAGING | BLOCKING_READ capabilities."""
        expected_caps = (
            BrokerCapabilities.ORDERED_MESSAGING
            | BrokerCapabilities.BLOCKING_READ
            | BrokerCapabilities.DEAD_LETTER_QUEUE
        )

        # Test has_all_capabilities
        assert broker.has_all_capabilities(BrokerCapabilities.PUBLISH)
        assert broker.has_all_capabilities(BrokerCapabilities.SUBSCRIBE)
        assert broker.has_all_capabilities(BrokerCapabilities.CONSUMER_GROUPS)
        assert broker.has_all_capabilities(BrokerCapabilities.ACK_NACK)
        assert broker.has_all_capabilities(BrokerCapabilities.DELIVERY_GUARANTEES)
        assert broker.has_all_capabilities(BrokerCapabilities.MESSAGE_ORDERING)
        assert broker.has_all_capabilities(BrokerCapabilities.BLOCKING_READ)
        assert broker.has_all_capabilities(BrokerCapabilities.DEAD_LETTER_QUEUE)
        assert broker.has_all_capabilities(expected_caps)

        # Should not have some advanced capabilities
        assert not broker.has_all_capabilities(BrokerCapabilities.REPLAY)
        assert not broker.has_all_capabilities(BrokerCapabilities.ENTERPRISE_STREAMING)

        # Test has_any_capability
        assert broker.has_any_capability(BrokerCapabilities.MESSAGE_ORDERING)
        assert broker.has_any_capability(
            BrokerCapabilities.BLOCKING_READ | BrokerCapabilities.REPLAY
        )
        assert not broker.has_any_capability(
            BrokerCapabilities.REPLAY | BrokerCapabilities.STREAM_PARTITIONING
        )
