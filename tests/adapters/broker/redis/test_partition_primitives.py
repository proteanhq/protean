"""Direct tests for the Redis partition-per-key primitives (ADR-0028).

Covers the broker surface the partitioned consumer builds on — the partition
index, the ownership lease with its fencing token, fenced read/ack, crash
reclaim via XAUTOCLAIM, and cold-partition reaping — against a live Redis.
"""

from uuid import uuid4

import pytest
import redis

from protean.adapters.broker.redis import RedisBroker
from protean.port.broker import BrokerCapabilities, LeaseLostError

pytestmark = pytest.mark.redis


@pytest.fixture
def broker(test_domain) -> RedisBroker:
    b = test_domain.brokers["default"]
    assert isinstance(b, RedisBroker)
    return b


def _payload(seq: int) -> dict:
    return {"data": {"seq": seq}, "metadata": {"headers": {"type": f"e{seq}"}}}


def _cat() -> str:
    return f"cat-{uuid4().hex[:8]}"


def test_advertises_stream_partitioning(broker: RedisBroker) -> None:
    assert broker.has_capability(BrokerCapabilities.STREAM_PARTITIONING)


def test_partition_index_record_and_read(broker: RedisBroker) -> None:
    cat = _cat()
    broker.record_partition(cat, "a")
    broker.record_partition(cat, "b")
    broker.record_partition(cat, "a")  # idempotent
    assert broker.partition_keys(cat) == {"a", "b"}


def test_partition_keys_empty_for_unknown_category(broker: RedisBroker) -> None:
    assert broker.partition_keys(_cat()) == set()


def test_lease_acquire_generation_and_renew(broker: RedisBroker) -> None:
    lease = f"lease-{uuid4().hex[:8]}"
    gen_key = f"{lease}:gen"
    g1 = broker.acquire_partition_lease(lease, gen_key, "owner-1", 5000)
    assert g1 == 1
    # Held → a second acquirer gets nothing.
    assert broker.acquire_partition_lease(lease, gen_key, "owner-2", 5000) is None
    # Renew succeeds for the holder, fails for a stale token.
    assert broker.renew_partition_lease(lease, "owner-1:1", 5000) is True
    assert broker.renew_partition_lease(lease, "owner-2:1", 5000) is False
    # Release then re-acquire increments the generation (monotonic fence).
    assert broker.release_partition_lease(lease, "owner-1:1") is True
    assert broker.acquire_partition_lease(lease, gen_key, "owner-2", 5000) == 2


def test_release_lease_fails_when_not_held(broker: RedisBroker) -> None:
    lease = f"lease-{uuid4().hex[:8]}"
    assert broker.release_partition_lease(lease, "owner-x:1") is False


def test_fenced_read_and_stale_owner_rejected(broker: RedisBroker) -> None:
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    lease = f"{group}:a:__lease__"
    gen_key = f"{group}:a:__generation__"
    for i in range(2):
        broker._publish(stream, _payload(i))
    gen = broker.acquire_partition_lease(lease, gen_key, "owner-1", 5000)
    fence = f"owner-1:{gen}"

    msgs = broker.read_partition_fenced(stream, group, fence, lease, fence, count=10)
    assert [m[1]["data"]["seq"] for m in msgs] == [0, 1]

    # A stale fence token cannot read.
    with pytest.raises(LeaseLostError):
        broker.read_partition_fenced(stream, group, "owner-0:0", lease, "owner-0:0")


def test_fenced_ack_and_stale_owner_rejected(broker: RedisBroker) -> None:
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    lease = f"{group}:a:__lease__"
    gen_key = f"{group}:a:__generation__"
    broker._publish(stream, _payload(0))
    gen = broker.acquire_partition_lease(lease, gen_key, "owner-1", 5000)
    fence = f"owner-1:{gen}"
    ((identifier, _),) = broker.read_partition_fenced(
        stream, group, fence, lease, fence, count=1
    )

    # Stale owner cannot ack.
    with pytest.raises(LeaseLostError):
        broker.ack_partition_fenced(stream, identifier, group, lease, "owner-0:0")
    # Real owner acks.
    assert broker.ack_partition_fenced(stream, identifier, group, lease, fence) is True


def test_reclaim_pending_via_xautoclaim(broker: RedisBroker) -> None:
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    lease = f"{group}:a:__lease__"
    gen_key = f"{group}:a:__generation__"
    for i in range(3):
        broker._publish(stream, _payload(i))
    gen = broker.acquire_partition_lease(lease, gen_key, "owner-1", 5000)
    fence = f"owner-1:{gen}"
    # owner-1 delivers all three into its PEL (unacked = pending).
    broker.read_partition_fenced(stream, group, fence, lease, fence, count=3)

    # A new owner reclaims the dead owner's pending entries.
    reclaimed = broker.reclaim_partition_pending(
        stream, group, "owner-2:2", min_idle_ms=0
    )
    assert sorted(m[1]["data"]["seq"] for m in reclaimed) == [0, 1, 2]


def test_reap_only_when_idle_and_drained(broker: RedisBroker) -> None:
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    broker.record_partition(cat, "a")
    broker._ensure_group(group, stream)
    identifier = broker._publish(stream, _payload(0))

    # Deliver + leave pending via a plain group read: a pending entry present
    # means the partition is never reaped, however idle.
    broker._client.xreadgroup(group, "c1", {stream: ">"}, count=1)
    assert broker.reap_partition(cat, "a", min_idle_ms=0) is False

    # Ack it → drained. A large idle floor still blocks the reap.
    broker._client.xack(stream, group, identifier)
    assert broker.reap_partition(cat, "a", min_idle_ms=10_000_000) is False
    # Idle floor of 0 → reaped: index entry and stream gone.
    assert broker.reap_partition(cat, "a", min_idle_ms=0) is True
    assert "a" not in broker.partition_keys(cat)


def test_reap_is_lane_aware(broker: RedisBroker) -> None:
    # With a backfill lane, reap refuses while the lane has pending entries and,
    # once drained, deletes both lanes — so a backfill message is never stranded.
    cat = _cat()
    main = f"{cat}:a"
    backfill = f"{cat}:a:backfill"
    group = "grp.Handler"
    broker.record_partition(cat, "a")
    broker._ensure_group(group, backfill)
    broker._publish(backfill, _payload(0))
    resp = broker._client.xreadgroup(group, "c1", {backfill: ">"}, count=1)  # pending
    bid = broker._decode_if_bytes(resp[0][1][0][0])

    # Backfill lane has a pending entry → not reaped.
    assert (
        broker.reap_partition(cat, "a", min_idle_ms=0, backfill_suffix="backfill")
        is False
    )
    assert "a" in broker.partition_keys(cat)

    # Ack it → both lanes drained → reaped, and both streams are gone.
    broker._client.xack(backfill, group, bid)
    assert (
        broker.reap_partition(cat, "a", min_idle_ms=0, backfill_suffix="backfill")
        is True
    )
    assert "a" not in broker.partition_keys(cat)
    assert broker._client.exists(main) == 0
    assert broker._client.exists(backfill) == 0


def test_reap_leaves_generation_counter(broker: RedisBroker) -> None:
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    gen_key = f"{cat}:a:__generation__"
    lease = f"{cat}:a:__lease__"
    broker.record_partition(cat, "a")
    broker._ensure_group(group, stream)
    ident = broker._publish(stream, _payload(0))
    broker._client.xreadgroup(group, "c1", {stream: ">"}, count=1)
    broker._client.xack(stream, group, ident)  # fully consumed
    # advance the generation a couple of times
    broker.acquire_partition_lease(lease, gen_key, "o1", 100)
    broker.release_partition_lease(lease, "o1:1")
    broker.acquire_partition_lease(lease, gen_key, "o2", 100)
    broker.release_partition_lease(lease, "o2:2")

    assert broker.reap_partition(cat, "a", min_idle_ms=0) is True
    # A re-created partition keeps a monotonic generation (fence never resets).
    assert broker.acquire_partition_lease(lease, gen_key, "o3", 100) == 3


def test_reap_blocked_by_group_behind_with_zero_pending(broker: RedisBroker) -> None:
    # A partition stream is shared by every handler on the category (one group
    # each). A group can be behind with ZERO pending — it never read, or acked all
    # it read but has unread entries left. Reaping then would silently lose its
    # unread messages, so the reap must refuse until every group has caught up.
    cat = _cat()
    stream = f"{cat}:a"
    g1 = "grp.H1"
    g2 = "grp.H2"
    broker.record_partition(cat, "a")
    broker._ensure_group(g1, stream)
    broker._ensure_group(g2, stream)  # exists but never reads
    ident = broker._publish(stream, _payload(0))

    # g1 fully consumes; g2 is behind (last-delivered still 0-0) with 0 pending.
    broker._client.xreadgroup(g1, "c1", {stream: ">"}, count=1)
    broker._client.xack(stream, g1, ident)
    assert broker.reap_partition(cat, "a", min_idle_ms=0) is False
    assert "a" in broker.partition_keys(cat)

    # g2 catches up → every group consumed → reaped.
    broker._client.xreadgroup(g2, "c2", {stream: ">"}, count=1)
    broker._client.xack(stream, g2, ident)
    assert broker.reap_partition(cat, "a", min_idle_ms=0) is True
    assert "a" not in broker.partition_keys(cat)


def test_colon_bearing_partition_stream_group_roundtrips(broker: RedisBroker) -> None:
    # A partition stream name carries colons (category::agg + :key); the group
    # cache must recover it by splitting off the last colon, not the first.
    stream = f"dom::order:{uuid4().hex[:6]}"
    group = "tests.module.OrderHandler"
    broker._ensure_group(group, stream)
    broker._publish(stream, _payload(0))
    assert stream in broker._get_streams_to_check()
    assert group in broker._calculate_consumer_groups_info()["names"]


def test_parse_fenced_read_handles_empty_and_missing_fields(
    broker: RedisBroker,
) -> None:
    # Defensive parsing of the raw Lua reply: an empty reply, a stream with no
    # entries, and an entry whose fields were claimed/deleted all yield nothing.
    assert broker._parse_fenced_read(None) == []
    assert broker._parse_fenced_read([[b"s", []]]) == []
    assert broker._parse_fenced_read([[b"s", [[b"1-0", []]]]]) == []


def test_fenced_read_reraises_non_fence_response_error(
    broker: RedisBroker, monkeypatch
) -> None:
    # A ResponseError that is not the FENCED sentinel is a real broker error and
    # must propagate, not be masked as a lost lease.
    def _boom(*args, **kwargs):
        raise redis.ResponseError("WRONGTYPE something else")

    monkeypatch.setattr(broker, "_lua_read_fenced", _boom)
    with pytest.raises(redis.ResponseError):
        broker.read_partition_fenced("s", "g", "c", "lease", "owner:1")


def test_fenced_read_recovers_from_missing_group(broker: RedisBroker) -> None:
    # Another process may reap a stream (deleting its groups) and re-create it
    # while our group cache still believes the group exists. The fenced read must
    # rebuild the group and retry rather than fail NOGROUP forever.
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    lease = f"{group}:a:__lease__"
    gen_key = f"{group}:a:__generation__"
    broker._publish(stream, _payload(0))
    gen = broker.acquire_partition_lease(lease, gen_key, "o", 5000)
    fence = f"o:{gen}"
    broker.read_partition_fenced(stream, group, fence, lease, fence)  # caches group

    # Destroy the stream+group behind the cache's back, then re-create the stream.
    broker._client.delete(stream)
    broker._publish(stream, _payload(1))

    msgs = broker.read_partition_fenced(
        stream, group, fence, lease, fence, new_messages=True
    )
    # Recovered: group rebuilt and the new message delivered.
    assert [m[1]["data"]["seq"] for m in msgs] == [1]


def test_reclaim_recovers_from_missing_group(broker: RedisBroker) -> None:
    # A missing group means nothing to reclaim: reclaim rebuilds the group and
    # returns empty rather than failing NOGROUP.
    cat = _cat()
    stream = f"{cat}:a"
    group = "grp.Handler"
    broker._ensure_group(group, stream)  # caches group
    broker._client.delete(stream)  # destroy behind the cache
    assert broker.reclaim_partition_pending(stream, group, "c:1") == []


def test_reclaim_propagates_broker_error(broker: RedisBroker, monkeypatch) -> None:
    # A broker error mid-reclaim must propagate, not be swallowed as "nothing to
    # reclaim": reclaim is a correctness precondition for the new owner, so the
    # consumer needs to see the failure and give up the partition rather than
    # drain new messages ahead of un-reclaimed pending ones.
    stream = f"{_cat()}:a"
    broker._ensure_group("grp.Handler", stream)

    def _boom(*args, **kwargs):
        raise redis.ResponseError("boom")

    monkeypatch.setattr(broker.redis_instance, "xautoclaim", _boom)
    with pytest.raises(redis.ResponseError):
        broker.reclaim_partition_pending(stream, "grp.Handler", "c:1")
