"""Tests for the combined primary + backfill read in the priority-lanes poll loop.

When the non-blocking primary read comes back empty, ``StreamSubscription.poll()``
makes one ``read_blocking_streams`` call that waits on both streams. The primary
entries of the reply are processed first, then the backfill entries, each batch
with its own stream.
"""

from unittest.mock import MagicMock

import pytest

from protean.domain import Processing
from protean.server.subscription.profiles import CircuitBreakerState

from .test_circuit_breaker import (
    Registered,
    ToggleEventHandler,
    User,
    _make_stream_subscription,
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


def _lanes_subscription(domain, combined_reply, **overrides):
    """A lanes-mode subscription whose primary read is empty and whose combined
    read returns ``combined_reply``. ``process_batch`` records each call and
    stops the loop after the turn."""
    sub = _make_stream_subscription(domain, **overrides)
    sub._lanes_enabled = True
    sub.broker.read_blocking_streams = MagicMock(return_value=combined_reply)
    sub.batches = []

    async def empty_primary():
        return []

    async def recording_process_batch(messages, stream=None):
        sub.batches.append((messages, stream))
        sub.keep_going = False
        return len(messages)

    sub._read_primary_nonblocking = empty_primary
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
        trimmed = [call.args[0] for call in sub.broker.trim.call_args_list]
        assert trimmed == [sub.stream_category, sub.backfill_stream]

    @pytest.mark.asyncio
    async def test_combined_read_waits_on_both_streams(self, lanes_domain):
        sub = _make_stream_subscription(lanes_domain, messages_per_tick=25)
        sub.blocking_timeout_ms = 5000
        sub.broker.read_blocking_streams = MagicMock(return_value={})

        assert await sub._read_lanes_blocking() == ([], [])

        kwargs = sub.broker.read_blocking_streams.call_args.kwargs
        assert kwargs["streams"] == ["test::user", "test::user:backfill"]
        assert kwargs["consumer_group"] == sub.consumer_group
        assert kwargs["consumer_name"] == sub.consumer_name
        assert kwargs["timeout_ms"] == 1000
        assert kwargs["count"] == 25

    @pytest.mark.asyncio
    async def test_short_blocking_timeout_is_passed_through(self, lanes_domain):
        sub = _make_stream_subscription(lanes_domain)
        sub.broker.read_blocking_streams = MagicMock(return_value={})

        await sub._read_lanes_blocking()

        assert sub.broker.read_blocking_streams.call_args.kwargs["timeout_ms"] == 100

    @pytest.mark.asyncio
    async def test_no_broker_reads_nothing(self, lanes_domain):
        sub = _make_stream_subscription(lanes_domain)
        sub.broker = None

        assert await sub._read_lanes_blocking() == ([], [])

    @pytest.mark.asyncio
    async def test_primary_entries_skip_the_combined_read(self, lanes_domain):
        sub = _lanes_subscription(lanes_domain, {})

        async def primary_with_entries():
            return [PRIMARY_MESSAGE]

        sub._read_primary_nonblocking = primary_with_entries

        await sub.poll()

        assert sub.batches == [([PRIMARY_MESSAGE], sub.stream_category)]
        sub.broker.read_blocking_streams.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_combined_read_marks_the_read_failed(self, lanes_domain):
        sub = _lanes_subscription(lanes_domain, {})
        sub.broker.read_blocking_streams = MagicMock(
            side_effect=RuntimeError("broker down")
        )

        assert await sub._read_lanes_blocking() == ([], [])
        assert sub._read_failed is True
        assert sub.batches == []

    @pytest.mark.asyncio
    async def test_lanes_off_never_uses_the_combined_read(self, lanes_domain):
        sub = _make_stream_subscription(lanes_domain)
        sub.broker.read_blocking_streams = MagicMock(return_value={})

        def read_then_stop(**kwargs):
            sub.keep_going = False
            return []

        sub.broker.read_blocking = MagicMock(side_effect=read_then_stop)

        await sub.poll()

        sub.broker.read_blocking.assert_called_once()
        sub.broker.read_blocking_streams.assert_not_called()


class TestBackfillAfterPrimaryBatch:
    @pytest.mark.asyncio
    async def test_backfill_is_skipped_when_primary_batch_opens_the_breaker(
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

        assert sub.broker.read_blocking_streams.call_args.kwargs["count"] == 1
        assert sub.batches == [([PRIMARY_MESSAGE], sub.stream_category)]
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
