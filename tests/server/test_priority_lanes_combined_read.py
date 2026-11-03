"""Tests for the combined primary + backfill read in the priority-lanes poll loop.

When the non-blocking primary read comes back empty, ``StreamSubscription.poll()``
makes one ``read_blocking_streams`` call that waits on both streams. The primary
entries of the reply are processed first, then the backfill entries, each batch
with its own stream.
"""

import asyncio

import pytest

from protean.domain import Processing
from protean.server.subscription.profiles import CircuitBreakerState
from tests.server.test_circuit_breaker import (
    Registered,
    ToggleEventHandler,
    User,
    _make_stream_subscription,
    _payload,
    _publish,
    _read,
)


@pytest.fixture()
def lanes_domain(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ToggleEventHandler, part_of=User)
    test_domain.init(traverse=False)
    return test_domain


PRIMARY_MESSAGE = ("1-0", {"lane": "primary"})
BACKFILL_MESSAGE = ("2-0", {"lane": "backfill"})


class ScriptedLanesBroker:
    """Returns fixed replies to the two lanes reads and records each combined read.

    These tests need replies the inline broker never gives. The inline broker
    returns a waiting primary message from the non-blocking primary read, so its
    combined read never holds primary entries; on Redis they appear when a
    message lands on the primary stream between the two reads. One test also
    scripts a ``None`` entry for a stream, which the subscription skips.
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


def _lanes_subscription(domain, combined_reply, primary_reply=(), **overrides):
    """A lanes-mode subscription on a ``ScriptedLanesBroker``.

    ``process_batch`` records each batch and its stream, and stops the loop
    after the turn.
    """
    sub = _make_stream_subscription(domain, **overrides)
    sub._lanes_enabled = True
    sub.broker = ScriptedLanesBroker(combined_reply, primary_reply)
    sub.batches = []

    async def recording_process_batch(messages, stream=None):
        sub.batches.append((messages, stream))
        sub.keep_going = False
        return len(messages)

    sub.process_batch = recording_process_batch
    return sub


class TestCombinedRead:
    @pytest.mark.asyncio
    async def test_primary_batch_is_processed_before_backfill_batch(self, lanes_domain):
        sub = _lanes_subscription(
            lanes_domain,
            {
                "test::user": [PRIMARY_MESSAGE],
                "test::user:backfill": [BACKFILL_MESSAGE],
            },
            retention_maxlen=100,
        )

        await sub.poll()

        assert sub.batches == [
            ([PRIMARY_MESSAGE], sub.stream_category),
            ([BACKFILL_MESSAGE], sub.backfill_stream),
        ]
        # Each stream is trimmed after its own batch.
        assert sub.broker.trimmed == [sub.stream_category, sub.backfill_stream]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "blocking_timeout_ms, expected_timeout_ms", [(5000, 1000), (100, 100)]
    )
    async def test_combined_read_waits_on_both_streams(
        self, lanes_domain, blocking_timeout_ms, expected_timeout_ms
    ):
        """The combined read waits on both streams for at most one second, and a
        shorter blocking timeout is passed through unchanged."""
        sub = _lanes_subscription(lanes_domain, {}, messages_per_tick=25)
        sub.blocking_timeout_ms = blocking_timeout_ms

        assert await sub._read_lanes_blocking() == ([], [])

        [kwargs] = sub.broker.combined_reads
        assert kwargs["streams"] == ["test::user", "test::user:backfill"]
        assert kwargs["consumer_group"] == sub.consumer_group
        assert kwargs["consumer_name"] == sub.consumer_name
        assert kwargs["timeout_ms"] == expected_timeout_ms
        assert kwargs["count"] == 25

    @pytest.mark.asyncio
    async def test_no_broker_reads_nothing(self, lanes_domain):
        sub = _make_stream_subscription(lanes_domain)
        sub.broker = None

        assert await sub._read_primary_nonblocking() == []
        assert await sub._read_lanes_blocking() == ([], [])

    @pytest.mark.asyncio
    async def test_primary_entries_skip_the_combined_read(self, lanes_domain):
        sub = _lanes_subscription(lanes_domain, {}, primary_reply=[PRIMARY_MESSAGE])

        await sub.poll()

        assert sub.batches == [([PRIMARY_MESSAGE], sub.stream_category)]
        assert sub.broker.combined_reads == []

    @pytest.mark.asyncio
    async def test_failed_combined_read_marks_the_read_failed(
        self, lanes_domain, monkeypatch
    ):
        sub = _make_stream_subscription(lanes_domain)
        sub._lanes_enabled = True

        def broker_down(**kwargs):
            raise RuntimeError("broker down")

        monkeypatch.setattr(sub.broker, "read_blocking_streams", broker_down)

        assert await sub._read_lanes_blocking() == ([], [])
        assert sub._read_failed is True

    @pytest.mark.asyncio
    async def test_lanes_off_never_uses_the_combined_read(self, lanes_domain):
        sub = _make_stream_subscription(lanes_domain)
        _publish(sub, [_payload("ok")])
        _publish(sub, [_payload("ok")], stream=sub.backfill_stream)

        sub.last_work_tick_finished = None

        task = asyncio.create_task(sub.poll())
        try:
            # The read runs in a worker thread, so wait for the work tick it
            # records rather than for a fixed time.
            async with asyncio.timeout(5):
                while sub.last_work_tick_finished is None:
                    await asyncio.sleep(0.01)
        finally:
            task.cancel()
            await task  # poll() swallows CancelledError and returns

        # The standard read took the primary message; the backfill message
        # was never read, so it is still there to read.
        assert _read(sub) == []
        assert len(_read(sub, stream=sub.backfill_stream)) == 1


class TestCombinedReadTickOutcome:
    @pytest.mark.asyncio
    async def test_primary_only_reply_counts_as_a_work_tick(self, lanes_domain):
        sub = _lanes_subscription(
            lanes_domain,
            {"test::user": [PRIMARY_MESSAGE], "test::user:backfill": []},
        )
        sub.last_work_tick_finished = None
        sub.last_idle_tick_started = None

        await sub.poll()

        assert sub.last_work_tick_finished is not None
        assert sub.last_idle_tick_started is None

    @pytest.mark.asyncio
    async def test_none_for_a_stream_is_read_as_no_messages(self, lanes_domain):
        sub = _lanes_subscription(
            lanes_domain,
            {"test::user": None, "test::user:backfill": [BACKFILL_MESSAGE]},
        )
        sub.last_work_tick_finished = None

        await sub.poll()

        assert sub.batches == [([BACKFILL_MESSAGE], sub.backfill_stream)]
        # The turn finished normally instead of raising on the None value.
        assert sub.last_work_tick_finished is not None


class TestBackfillAfterPrimaryBatch:
    @pytest.mark.asyncio
    async def test_backfill_is_processed_when_primary_batch_opens_the_breaker(
        self,
        lanes_domain,
    ):
        sub = _lanes_subscription(
            lanes_domain,
            {
                "test::user": [PRIMARY_MESSAGE],
                "test::user:backfill": [BACKFILL_MESSAGE],
            },
        )
        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        recording = sub.process_batch

        async def failing_probe(messages, stream=None):
            # The HALF_OPEN probe fails and re-opens the breaker.
            sub._open_circuit()
            return await recording(messages, stream)

        sub.process_batch = failing_probe

        await sub.poll()

        assert sub.broker.combined_reads[-1]["count"] == 1
        # The backfill entry is already delivered to this consumer, and the
        # consumer name changes on restart, so it is processed now rather than
        # left pending where no later read would find it.
        assert sub.batches == [
            ([PRIMARY_MESSAGE], sub.stream_category),
            ([BACKFILL_MESSAGE], sub.backfill_stream),
        ]
        assert sub.circuit_state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_backfill_is_processed_when_half_open_probe_succeeds(
        self,
        lanes_domain,
    ):
        sub = _lanes_subscription(
            lanes_domain,
            {
                "test::user": [PRIMARY_MESSAGE],
                "test::user:backfill": [BACKFILL_MESSAGE],
            },
        )
        sub.circuit_state = CircuitBreakerState.HALF_OPEN
        recording = sub.process_batch

        async def passing_probe(messages, stream=None):
            sub._record_handler_outcome(True)
            return await recording(messages, stream)

        sub.process_batch = passing_probe

        await sub.poll()

        assert sub.batches == [
            ([PRIMARY_MESSAGE], sub.stream_category),
            ([BACKFILL_MESSAGE], sub.backfill_stream),
        ]
        assert sub.circuit_state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_backfill_is_processed_when_drain_starts_during_primary_batch(
        self,
        lanes_domain,
    ):
        sub = _lanes_subscription(
            lanes_domain,
            {
                "test::user": [PRIMARY_MESSAGE],
                "test::user:backfill": [BACKFILL_MESSAGE],
            },
        )
        recording = sub.process_batch

        async def drain_during_batch(messages, stream=None):
            sub.engine.draining = True
            return await recording(messages, stream)

        sub.process_batch = drain_during_batch

        await sub.poll()

        # The backfill entries were already delivered, so they finish too.
        assert sub.batches == [
            ([PRIMARY_MESSAGE], sub.stream_category),
            ([BACKFILL_MESSAGE], sub.backfill_stream),
        ]
