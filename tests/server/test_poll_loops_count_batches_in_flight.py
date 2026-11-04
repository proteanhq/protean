"""Each subscription poll loop counts the batch it is working on as in flight.

``POST /drainz`` reports ``drained`` from the engine's count of batches in
flight. Each test stands in a batch step that records ``batches_drained`` while
it runs, then checks the count is back to zero once the loop ends.
"""

import pytest

from protean.domain import Processing
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.server.subscription.partitioned_stream_subscription import (
    PartitionedStreamSubscription,
    _OwnedPartition,
)
from tests.server.test_circuit_breaker import (
    Registered,
    ToggleEventHandler,
    User,
    _make_stream_subscription,
)
from tests.server.test_priority_lanes_combined_read import (
    BACKFILL_MESSAGE,
    PRIMARY_MESSAGE,
)


class ScriptedLanesBroker:
    """Returns fixed replies to the two lanes reads and records each combined read.

    The inline broker returns a waiting primary message from the non-blocking
    primary read, so its combined read never holds primary entries; on Redis they
    appear when a message lands on the primary stream between the two reads.
    """

    def __init__(self, combined_reply=None, primary_reply=()):
        self.combined_reply = combined_reply or {}
        self.primary_reply = list(primary_reply)
        self.combined_reads: list[dict] = []
        self.trimmed: list[str] = []

    def read_blocking(self, **kwargs):
        return list(self.primary_reply)

    def read_blocking_streams(self, **kwargs):
        self.combined_reads.append(kwargs)
        return self.combined_reply

    def trim(self, stream, maxlen):
        self.trimmed.append(stream)
        return 0


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ToggleEventHandler, part_of=User)
    test_domain.init(traverse=False)


def _record_drained_then_stop(subscription, seen):
    """A ``process_batch`` that records the engine's drained report and stops."""

    async def process_batch(messages, stream=None):
        seen.append(subscription.engine.batches_drained)
        subscription.keep_going = False
        return len(messages)

    return process_batch


class TestStreamSubscriptionPoll:
    async def test_standard_mode_counts_the_batch(self, test_domain):
        sub = _make_stream_subscription(test_domain)
        seen: list[bool] = []

        async def one_message():
            return [PRIMARY_MESSAGE]

        sub.get_next_batch_of_messages = one_message
        sub.process_batch = _record_drained_then_stop(sub, seen)

        await sub.poll()

        assert seen == [False]
        assert sub.engine.batches_drained is True

    async def test_lanes_mode_counts_the_primary_batch(self, test_domain):
        sub = _make_stream_subscription(test_domain)
        sub._lanes_enabled = True
        sub.broker = ScriptedLanesBroker(primary_reply=[PRIMARY_MESSAGE])
        seen: list[bool] = []
        sub.process_batch = _record_drained_then_stop(sub, seen)

        await sub.poll()

        assert seen == [False]
        assert sub.engine.batches_drained is True

    async def test_lanes_mode_counts_the_combined_read_batch(self, test_domain):
        sub = _make_stream_subscription(test_domain)
        sub._lanes_enabled = True
        sub.broker = ScriptedLanesBroker(
            combined_reply={sub.backfill_stream: [BACKFILL_MESSAGE]}
        )
        seen: list[bool] = []
        sub.process_batch = _record_drained_then_stop(sub, seen)

        await sub.poll()

        assert seen == [False]
        assert sub.engine.batches_drained is True


class TestEventStoreSubscriptionPoll:
    async def test_tick_counts_as_a_batch(self, test_domain):
        engine = Engine(test_domain, test_mode=True)
        sub = EventStoreSubscription(
            engine, User.meta_.stream_category, ToggleEventHandler
        )
        seen: list[bool] = []

        async def tick() -> bool:
            seen.append(engine.batches_drained)
            sub.keep_going = False
            return True

        sub.tick = tick

        await sub.poll()

        assert seen == [False]
        assert engine.batches_drained is True


class TestPartitionedWorker:
    async def test_each_drain_step_counts_as_a_batch(self, test_domain):
        engine = Engine(test_domain, test_mode=True)
        sub = PartitionedStreamSubscription(
            engine=engine,
            stream_category=User.meta_.stream_category,
            handler=ToggleEventHandler,
            stream_categories=[User.meta_.stream_category],
        )
        owned = _OwnedPartition("p-1", [], "lease", 1, "fence")
        sub._owned[owned.partition_id] = owned
        seen: list[bool] = []

        async def no_reclaim(owned_partition) -> None:
            return None

        async def drain_once(owned_partition) -> int:
            seen.append(engine.batches_drained)
            sub.keep_going = False
            return 1

        sub._reclaim = no_reclaim
        sub._drain_once = drain_once

        await sub._run_partition(owned)

        assert seen == [False]
        assert engine.batches_drained is True
