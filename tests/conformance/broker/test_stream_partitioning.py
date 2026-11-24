"""Brokers that declare ``STREAM_PARTITIONING`` hand out partition leases and
fence reads and acks on them."""

import time

import pytest

from protean.port.broker import BrokerCapabilities, LeaseLostError

pytestmark = pytest.mark.requires(BrokerCapabilities.STREAM_PARTITIONING)

STREAM = "orders:a"
GROUP = "orders.Handler"
LEASE = f"{GROUP}:a:__lease__"
GENERATION = f"{GROUP}:a:__generation__"
TTL_MS = 5000


def fence_token(owner, generation):
    return f"{owner}:{generation}"


def test_acquire_returns_a_rising_generation_and_refuses_a_held_lease(broker):
    first = broker._acquire_partition_lease(LEASE, GENERATION, "owner-1", TTL_MS)

    assert first is not None
    assert broker._acquire_partition_lease(LEASE, GENERATION, "owner-2", TTL_MS) is None

    assert broker._release_partition_lease(LEASE, fence_token("owner-1", first))
    second = broker._acquire_partition_lease(LEASE, GENERATION, "owner-2", TTL_MS)
    assert second is not None
    assert second > first


def test_renew_succeeds_only_for_the_holder(broker):
    generation = broker._acquire_partition_lease(LEASE, GENERATION, "owner-1", TTL_MS)

    assert broker._renew_partition_lease(
        LEASE, fence_token("owner-1", generation), TTL_MS
    )
    assert not broker._renew_partition_lease(
        LEASE, fence_token("owner-2", generation), TTL_MS
    )


def test_release_of_a_lease_that_is_not_held_returns_false(broker):
    assert broker._release_partition_lease(LEASE, fence_token("owner-1", 1)) is False


def test_the_holder_reads_and_acks_its_partition(broker):
    for n in range(2):
        broker.publish(STREAM, {"n": n})
    generation = broker._acquire_partition_lease(LEASE, GENERATION, "owner-1", TTL_MS)
    token = fence_token("owner-1", generation)

    messages = broker._read_partition_fenced(
        STREAM, GROUP, token, LEASE, token, limit=10
    )

    assert sorted(message["n"] for _, message in messages) == [0, 1]
    for identifier, _ in messages:
        assert broker._ack_partition_fenced(STREAM, identifier, GROUP, LEASE, token)


def test_a_fenced_read_without_the_lease_raises_and_reads_nothing(broker):
    broker.publish(STREAM, {"n": 0})
    generation = broker._acquire_partition_lease(LEASE, GENERATION, "owner-1", TTL_MS)
    stale = fence_token("owner-0", 0)

    with pytest.raises(LeaseLostError):
        broker._read_partition_fenced(STREAM, GROUP, stale, LEASE, stale)

    token = fence_token("owner-1", generation)
    messages = broker._read_partition_fenced(STREAM, GROUP, token, LEASE, token)
    assert [message for _, message in messages] == [{"n": 0}]


def test_an_ack_after_the_lease_is_taken_over_raises(broker):
    broker.publish(STREAM, {"n": 0})
    generation = broker._acquire_partition_lease(LEASE, GENERATION, "owner-1", 100)
    token = fence_token("owner-1", generation)
    [(identifier, _)] = broker._read_partition_fenced(
        STREAM, GROUP, token, LEASE, token
    )

    # Wait well past the lease's expiry, then let another owner take it.
    time.sleep(0.5)
    assert broker._acquire_partition_lease(LEASE, GENERATION, "owner-2", TTL_MS)

    with pytest.raises(LeaseLostError):
        broker._ack_partition_fenced(STREAM, identifier, GROUP, LEASE, token)
