"""Tests for RedisBroker._cleanup_stale_consumers().

Integration tests that verify stale consumer cleanup using a real Redis instance.
"""

import pytest

from protean.adapters.broker.redis import RedisBroker


@pytest.fixture
def redis_broker(test_domain) -> RedisBroker:
    return test_domain.brokers["default"]


@pytest.mark.redis
class TestCleanupStaleConsumers:
    """Integration tests for _cleanup_stale_consumers() with real Redis."""

    def test_removes_stale_consumer_with_same_prefix(self, redis_broker):
        """Removes a consumer that shares the class-hostname-pid prefix but has a different hex suffix."""
        stream = "test::cleanup-stale"
        group = "TestHandler"
        current = "TestHandler-host1-1000-aabbcc"
        stale = "TestHandler-host1-1000-112233"

        # Set up stream and group
        redis_broker._ensure_group(group, stream)

        # Create stale consumer by reading with its name, then ack so pending=0
        redis_broker.redis_instance.xadd(stream, {"data": "msg1"})
        redis_broker.redis_instance.xreadgroup(group, stale, {stream: ">"}, count=1)
        # ACK so stale consumer has 0 pending
        entries = redis_broker.redis_instance.xinfo_consumers(stream, group)
        for e in entries:
            name = e.get("name") or e.get(b"name")
            if isinstance(name, bytes):
                name = name.decode()
            if name == stale:
                # Find the pending message and ack it
                pending = redis_broker.redis_instance.xpending_range(
                    stream, group, min="-", max="+", count=10
                )
                for p in pending:
                    mid = p.get("message_id") or p.get(b"message_id")
                    redis_broker.redis_instance.xack(stream, group, mid)

        # Create current consumer
        redis_broker.redis_instance.xadd(stream, {"data": "msg2"})
        redis_broker.redis_instance.xreadgroup(group, current, {stream: ">"}, count=1)

        # Verify both consumers exist
        consumers = redis_broker.redis_instance.xinfo_consumers(stream, group)
        names = {
            (c.get("name") or c.get(b"name")).decode()
            if isinstance(c.get("name") or c.get(b"name"), bytes)
            else str(c.get("name") or c.get(b"name"))
            for c in consumers
        }
        assert stale in names
        assert current in names

        # Run cleanup
        removed = redis_broker._cleanup_stale_consumers(stream, group, current)
        assert removed == 1

        # Verify stale consumer is gone
        consumers_after = redis_broker.redis_instance.xinfo_consumers(stream, group)
        names_after = {
            (c.get("name") or c.get(b"name")).decode()
            if isinstance(c.get("name") or c.get(b"name"), bytes)
            else str(c.get("name") or c.get(b"name"))
            for c in consumers_after
        }
        assert stale not in names_after
        assert current in names_after

    def test_skips_consumer_with_pending_messages(self, redis_broker):
        """Does not remove a stale consumer that has pending (un-ACKed) messages."""
        stream = "test::cleanup-pending"
        group = "PendingHandler"
        current = "PendingHandler-host1-1000-newwww"
        stale = "PendingHandler-host1-1000-oldold"

        redis_broker._ensure_group(group, stream)

        # Create stale consumer with a pending message (don't ACK)
        redis_broker.redis_instance.xadd(stream, {"data": "unacked"})
        redis_broker.redis_instance.xreadgroup(group, stale, {stream: ">"}, count=1)

        # Verify stale consumer has pending > 0
        consumers = redis_broker.redis_instance.xinfo_consumers(stream, group)
        for c in consumers:
            name = c.get("name") or c.get(b"name")
            if isinstance(name, bytes):
                name = name.decode()
            if name == stale:
                pending = c.get("pending") or c.get(b"pending") or 0
                assert int(pending) > 0

        # Run cleanup — should skip because of pending messages
        removed = redis_broker._cleanup_stale_consumers(stream, group, current)
        assert removed == 0

        # Verify stale consumer is still there
        consumers_after = redis_broker.redis_instance.xinfo_consumers(stream, group)
        names_after = {
            (c.get("name") or c.get(b"name")).decode()
            if isinstance(c.get("name") or c.get(b"name"), bytes)
            else str(c.get("name") or c.get(b"name"))
            for c in consumers_after
        }
        assert stale in names_after

    def test_does_not_remove_unrelated_consumer(self, redis_broker):
        """Does not remove consumers with a different class-hostname-pid prefix."""
        stream = "test::cleanup-unrelated"
        group = "MixedGroup"
        current = "HandlerA-host1-1000-aabbcc"
        unrelated = "HandlerB-host2-2000-ddeeff"

        redis_broker._ensure_group(group, stream)

        # Create unrelated consumer
        redis_broker.redis_instance.xadd(stream, {"data": "msg1"})
        redis_broker.redis_instance.xreadgroup(group, unrelated, {stream: ">"}, count=1)
        # ACK so pending=0
        pending = redis_broker.redis_instance.xpending_range(
            stream, group, min="-", max="+", count=10
        )
        for p in pending:
            mid = p.get("message_id") or p.get(b"message_id")
            redis_broker.redis_instance.xack(stream, group, mid)

        # Run cleanup
        removed = redis_broker._cleanup_stale_consumers(stream, group, current)
        assert removed == 0

        # Verify unrelated consumer is still there
        consumers = redis_broker.redis_instance.xinfo_consumers(stream, group)
        names = {
            (c.get("name") or c.get(b"name")).decode()
            if isinstance(c.get("name") or c.get(b"name"), bytes)
            else str(c.get("name") or c.get(b"name"))
            for c in consumers
        }
        assert unrelated in names

    def test_does_not_remove_current_consumer(self, redis_broker):
        """Never removes the current consumer (itself)."""
        stream = "test::cleanup-self"
        group = "SelfGroup"
        current = "Handler-host1-1000-aabbcc"

        redis_broker._ensure_group(group, stream)

        # Create current consumer
        redis_broker.redis_instance.xadd(stream, {"data": "msg"})
        redis_broker.redis_instance.xreadgroup(group, current, {stream: ">"}, count=1)

        removed = redis_broker._cleanup_stale_consumers(stream, group, current)
        assert removed == 0

        consumers = redis_broker.redis_instance.xinfo_consumers(stream, group)
        assert len(consumers) >= 1

    def test_returns_zero_when_no_consumers_exist(self, redis_broker):
        """Returns 0 when consumer group has no consumers."""
        stream = "test::cleanup-empty"
        group = "EmptyGroup"
        current = "Handler-host1-1000-aabbcc"

        redis_broker._ensure_group(group, stream)

        removed = redis_broker._cleanup_stale_consumers(stream, group, current)
        assert removed == 0

    def test_returns_zero_for_consumer_name_without_hyphen(self, redis_broker):
        """Returns 0 when current_consumer_name has no hyphens (no prefix to match)."""
        stream = "test::cleanup-nohyphen"
        group = "NoHyphenGroup"

        redis_broker._ensure_group(group, stream)

        removed = redis_broker._cleanup_stale_consumers(stream, group, "nohyphen")
        assert removed == 0

    def test_removes_multiple_stale_consumers(self, redis_broker):
        """Removes multiple stale consumers that share the same prefix."""
        stream = "test::cleanup-multi"
        group = "MultiGroup"
        current = "Handler-host1-1000-current"
        stale1 = "Handler-host1-1000-old001"
        stale2 = "Handler-host1-1000-old002"

        redis_broker._ensure_group(group, stream)

        # Create stale consumers and ack their messages
        for stale_name in [stale1, stale2]:
            redis_broker.redis_instance.xadd(stream, {"data": f"msg-{stale_name}"})
            redis_broker.redis_instance.xreadgroup(
                group, stale_name, {stream: ">"}, count=1
            )
            # ACK all pending for this consumer
            pending = redis_broker.redis_instance.xpending_range(
                stream, group, min="-", max="+", count=100
            )
            for p in pending:
                mid = p.get("message_id") or p.get(b"message_id")
                cname = p.get("consumer") or p.get(b"consumer")
                if isinstance(cname, bytes):
                    cname = cname.decode()
                if cname == stale_name:
                    redis_broker.redis_instance.xack(stream, group, mid)

        # Verify both stale consumers exist
        consumers = redis_broker.redis_instance.xinfo_consumers(stream, group)
        assert len(consumers) == 2

        # Run cleanup
        removed = redis_broker._cleanup_stale_consumers(stream, group, current)
        assert removed == 2
