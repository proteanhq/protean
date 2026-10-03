"""Live Redis tests for read_blocking_streams.

One XREADGROUP call waits on the primary and backfill streams at once, so a
message published to the primary stream during the wait ends it at once.
"""

import threading
import time
from uuid import uuid4

import pytest


@pytest.mark.redis
class TestReadBlockingStreamsAgainstRedis:
    def test_message_on_primary_ends_the_wait_at_once(self, test_domain):
        broker = test_domain.brokers["default"]
        primary = f"lanes-{uuid4().hex}"
        backfill = f"{primary}:backfill"
        group = "lanes-group"
        # Create the groups first, so the message published below is new to
        # the group and is returned by the ">" read.
        broker._ensure_group(group, primary)
        broker._ensure_group(group, backfill)

        publisher = threading.Timer(0.1, broker.publish, args=(primary, {"n": 1}))

        started = time.monotonic()
        publisher.start()
        try:
            result = broker.read_blocking_streams(
                [primary, backfill], group, "lanes-consumer", timeout_ms=1000
            )
            elapsed = time.monotonic() - started
        finally:
            publisher.join()

        assert list(result) == [primary, backfill]
        assert len(result[primary]) == 1
        assert result[primary][0][1]["n"] == 1
        assert result[backfill] == []
        assert elapsed < 0.5

    def test_pending_entries_are_returned_before_new_ones(self, test_domain):
        broker = test_domain.brokers["default"]
        primary = f"lanes-{uuid4().hex}"
        backfill = f"{primary}:backfill"
        group = "lanes-group"
        broker._ensure_group(group, primary)
        broker._ensure_group(group, backfill)
        broker.publish(backfill, {"n": 1})

        # Deliver the backfill message without acking it, so it stays pending.
        first = broker.read_blocking_streams(
            [primary, backfill], group, "lanes-consumer", timeout_ms=0
        )
        assert len(first[backfill]) == 1
        broker.publish(primary, {"n": 2})

        again = broker.read_blocking_streams(
            [primary, backfill], group, "lanes-consumer", timeout_ms=0
        )

        assert again[primary] == []
        assert [message for _, message in again[backfill]] == [
            message for _, message in first[backfill]
        ]
