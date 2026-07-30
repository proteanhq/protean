"""Tests for RedisBroker capability declarations."""

import pytest

from protean.port.broker import BrokerCapabilities


@pytest.mark.redis
class TestRedisBrokerCapabilities:
    """Test capability methods specifically with Redis broker."""

    def test_capabilities(self, broker):
        """RedisBroker has ordered messaging, blocking reads, DLQ, and
        partition-per-key streams (STREAM_PARTITIONING, added in ADR-0028)."""
        expected_caps = (
            BrokerCapabilities.ORDERED_MESSAGING
            | BrokerCapabilities.BLOCKING_READ
            | BrokerCapabilities.DEAD_LETTER_QUEUE
            | BrokerCapabilities.STREAM_PARTITIONING
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
        assert broker.has_all_capabilities(BrokerCapabilities.STREAM_PARTITIONING)
        assert broker.has_all_capabilities(expected_caps)

        # Should not have some advanced capabilities it does not implement.
        assert not broker.has_all_capabilities(BrokerCapabilities.REPLAY)
        assert not broker.has_all_capabilities(BrokerCapabilities.ENTERPRISE_STREAMING)

        # Test has_any_capability
        assert broker.has_any_capability(BrokerCapabilities.MESSAGE_ORDERING)
        assert broker.has_any_capability(
            BrokerCapabilities.BLOCKING_READ | BrokerCapabilities.REPLAY
        )
        # Advertises STREAM_PARTITIONING but not REPLAY.
        assert broker.has_any_capability(
            BrokerCapabilities.REPLAY | BrokerCapabilities.STREAM_PARTITIONING
        )
        assert not broker.has_any_capability(BrokerCapabilities.REPLAY)
