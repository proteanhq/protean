"""Tests for RedisBroker capability declarations."""

import pytest

from protean.port.broker import BrokerCapabilities


@pytest.mark.redis
class TestRedisBrokerCapabilities:
    """Test capability methods specifically with Redis broker."""

    def test_capabilities(self, broker):
        """RedisBroker has ordered messaging, blocking reads, DLQ,
        partition-per-key streams (STREAM_PARTITIONING, added in ADR-0028) and
        stream trimming (STREAM_RETENTION)."""
        expected_caps = (
            BrokerCapabilities.ORDERED_MESSAGING
            | BrokerCapabilities.BLOCKING_READ
            | BrokerCapabilities.DEAD_LETTER_QUEUE
            | BrokerCapabilities.STREAM_PARTITIONING
            | BrokerCapabilities.STREAM_RETENTION
        )
        assert broker.capabilities == expected_caps

        # Every flag the broker declares
        assert BrokerCapabilities.PUBLISH in broker.capabilities
        assert BrokerCapabilities.SUBSCRIBE in broker.capabilities
        assert BrokerCapabilities.CONSUMER_GROUPS in broker.capabilities
        assert BrokerCapabilities.ACK_NACK in broker.capabilities
        assert BrokerCapabilities.DELIVERY_GUARANTEES in broker.capabilities
        assert BrokerCapabilities.MESSAGE_ORDERING in broker.capabilities
        assert BrokerCapabilities.BLOCKING_READ in broker.capabilities
        assert BrokerCapabilities.DEAD_LETTER_QUEUE in broker.capabilities
        assert BrokerCapabilities.STREAM_PARTITIONING in broker.capabilities
        assert BrokerCapabilities.STREAM_RETENTION in broker.capabilities
        assert expected_caps in broker.capabilities

        # Should not have some advanced capabilities it does not implement.
        assert BrokerCapabilities.REPLAY not in broker.capabilities
        assert BrokerCapabilities.ENTERPRISE_STREAMING not in broker.capabilities

        # At least one flag of a set
        assert bool(broker.capabilities & BrokerCapabilities.MESSAGE_ORDERING)
        assert bool(
            broker.capabilities
            & (BrokerCapabilities.BLOCKING_READ | BrokerCapabilities.REPLAY)
        )
        # Advertises STREAM_PARTITIONING but not REPLAY.
        assert bool(
            broker.capabilities
            & (BrokerCapabilities.REPLAY | BrokerCapabilities.STREAM_PARTITIONING)
        )
        assert not (broker.capabilities & BrokerCapabilities.REPLAY)
