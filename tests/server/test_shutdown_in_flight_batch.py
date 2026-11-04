"""Tests for what happens to a batch already read when the engine shuts down.

A shutdown lets the batch finish inside the drain window. A batch still
running when the window ends is cancelled, and its unhandled messages stay
with the broker untouched. The engine counts the batches in flight so that
``POST /drainz`` can report when the worker is drained.
"""

import asyncio
import logging
import time

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
from protean.server.engine import DEFAULT_RECLAIM_IDLE_SECONDS
from protean.server.subscription.broker_subscription import BrokerSubscription
from tests.server.test_trace_correlation import _attach_recording_redis

handled: list[dict] = []


class FailsOnFlagSubscriber(BaseSubscriber):
    """Raises for a message carrying ``fail``, records every other one."""

    def __call__(self, data: dict) -> None:
        if data.get("fail"):
            raise RuntimeError("intentional failure")
        handled.append(data)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value
    test_domain.register(FailsOnFlagSubscriber, stream="orders")
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def clear_handled():
    yield
    handled.clear()


def _subscription(engine, retry_delay_seconds):
    return BrokerSubscription(
        engine,
        engine.domain.brokers["default"],
        "orders",
        FailsOnFlagSubscriber,
        max_retries=3,
        retry_delay_seconds=retry_delay_seconds,
    )


def _publish_batch(engine):
    """Publish a failing message ahead of two good ones."""
    broker = engine.domain.brokers["default"]
    broker.publish("orders", {"name": "first", "fail": True})
    broker.publish("orders", {"name": "second"})
    broker.publish("orders", {"name": "third"})


class TestBatchOnShutdown:
    def test_messages_after_shutdown_starts_are_handled(self, test_domain):
        """A shutdown that starts mid-batch does not fail the rest of it.

        The first message fails and its retry delay yields to the event loop.
        Shutdown starts during that delay. The two later messages are handled
        and acknowledged, and none of them is counted as a retry.
        """
        engine = Engine(test_domain, test_mode=True)
        subscription = _subscription(engine, retry_delay_seconds=0.1)
        _publish_batch(engine)

        async def run():
            messages = await subscription.get_next_batch_of_messages()
            assert len(messages) == 3
            batch = asyncio.ensure_future(subscription.process_batch(messages))
            await asyncio.sleep(0.02)
            engine.shutting_down = True
            return await batch

        successful = engine.loop.run_until_complete(run())

        assert [m["name"] for m in handled] == ["second", "third"]
        assert successful == 2
        assert list(subscription.retry_counts.values()) == [1]

    def test_drain_timeout_cancels_the_batch_without_failing_it(self, test_domain):
        """A batch still running when the drain window ends is cancelled.

        Shutdown starts before the first message is handled. The first two
        messages are handled after that, then the batch waits until the drain
        window ends and is cancelled. The third message is not handled, gets
        no retry count and no ``message.nacked`` trace, and shutdown does not
        wait out the retry delay.
        """
        test_domain.config["server"]["drain_timeout"] = 0.1
        engine = Engine(test_domain, test_mode=True)
        subscription = _subscription(engine, retry_delay_seconds=5)
        traces = _attach_recording_redis(engine.emitter)
        broker = engine.domain.brokers["default"]
        for name in ("first", "second", "third"):
            broker.publish("orders", {"name": name})
        handle_broker_message = engine.handle_broker_message

        async def handle_then_hold(subscriber_cls, message, **kwargs):
            if message["name"] == "first":
                # Shutdown starts during this pause.
                await asyncio.sleep(0.02)
            result = await handle_broker_message(subscriber_cls, message, **kwargs)
            if message["name"] == "second":
                # Hold the batch until the drain window cancels it.
                await asyncio.Event().wait()
            return result

        engine.handle_broker_message = handle_then_hold  # type: ignore[method-assign]

        async def run():
            messages = await subscription.get_next_batch_of_messages()
            assert len(messages) == 3
            batch = asyncio.ensure_future(subscription.process_batch(messages))
            await asyncio.sleep(0.01)
            started = time.monotonic()
            await engine.shutdown()
            return batch, time.monotonic() - started

        batch, shutdown_seconds = engine.loop.run_until_complete(run())

        assert batch.cancelled()
        assert [m["name"] for m in handled] == ["first", "second"]
        assert subscription.retry_counts == {}
        assert [t for t in traces.traces() if t["event"] == "message.nacked"] == []
        assert shutdown_seconds < 2


class TestBatchesInFlight:
    def test_drained_until_a_batch_starts_and_after_it_ends(self, test_domain):
        engine = Engine(test_domain, test_mode=True)
        assert engine.batches_drained is True

        with engine.batch_in_flight():
            assert engine.batches_drained is False
            with engine.batch_in_flight():
                assert engine.batches_drained is False
            assert engine.batches_drained is False

        assert engine.batches_drained is True

    def test_a_batch_that_raises_is_no_longer_counted(self, test_domain):
        engine = Engine(test_domain, test_mode=True)

        with pytest.raises(RuntimeError), engine.batch_in_flight():
            raise RuntimeError("batch failed")

        assert engine.batches_drained is True

    def test_broker_subscription_poll_counts_its_tick(self, test_domain):
        """The base poll loop counts a tick of a subscription that pauses on
        drain as a batch in flight."""
        engine = Engine(test_domain, test_mode=True)
        subscription = _subscription(engine, retry_delay_seconds=0)
        seen: list[bool] = []

        async def tick() -> bool:
            # Stop first: the poll loop retries a tick that raises.
            subscription.keep_going = False
            seen.append(engine.batches_drained)
            return False

        subscription.tick = tick  # type: ignore[method-assign]
        engine.loop.run_until_complete(subscription.poll())

        assert seen == [False]
        assert engine.batches_drained is True

    def test_poll_of_a_loop_that_keeps_running_on_drain_is_not_counted(
        self, test_domain
    ):
        """Negative: the outbox keeps running through a drain, so its ticks
        must not hold the engine's drained report at false."""
        engine = Engine(test_domain, test_mode=True)
        subscription = _subscription(engine, retry_delay_seconds=0)
        subscription.pauses_on_drain = False
        seen: list[bool] = []

        async def tick() -> bool:
            # Stop first: the poll loop retries a tick that raises.
            subscription.keep_going = False
            seen.append(engine.batches_drained)
            return False

        subscription.tick = tick  # type: ignore[method-assign]
        engine.loop.run_until_complete(subscription.poll())

        assert seen == [True]


class TestReclaimIdleSetting:
    def test_default_is_120_seconds(self, test_domain):
        assert DEFAULT_RECLAIM_IDLE_SECONDS == 120
        assert test_domain.config["server"]["reclaim_idle_seconds"] == 120
        assert Engine(test_domain, test_mode=True).reclaim_idle_seconds == 120.0

    def test_configured_value_is_used(self, test_domain):
        test_domain.config["server"]["reclaim_idle_seconds"] = 300
        assert Engine(test_domain, test_mode=True).reclaim_idle_seconds == 300.0

    @pytest.mark.parametrize(
        ("seconds", "milliseconds"), [(120, 120_000), (0.0015, 2), (0.0004, 1)]
    )
    def test_threshold_in_milliseconds_rounds_up(
        self, test_domain, seconds, milliseconds
    ):
        """A positive threshold under a millisecond never becomes 0 ms, which
        would claim entries a running consumer read moments ago."""
        test_domain.config["server"]["reclaim_idle_seconds"] = seconds
        assert Engine(test_domain, test_mode=True).reclaim_idle_ms == milliseconds

    @pytest.mark.parametrize("value", ["soon", True, float("nan"), float("inf")])
    def test_invalid_value_falls_back_and_warns(self, test_domain, caplog, value):
        test_domain.config["server"]["reclaim_idle_seconds"] = value
        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            engine = Engine(test_domain, test_mode=True)

        assert engine.reclaim_idle_seconds == 120.0
        assert [r.message for r in caplog.records] == [
            "engine.reclaim_idle_seconds_invalid_using_default"
        ]

    @pytest.mark.parametrize("value", [0, -30])
    def test_non_positive_value_falls_back_and_warns(self, test_domain, caplog, value):
        """A zero threshold would claim a running consumer's entries."""
        test_domain.config["server"]["reclaim_idle_seconds"] = value
        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            engine = Engine(test_domain, test_mode=True)

        assert engine.reclaim_idle_seconds == 120.0
        assert [r.message for r in caplog.records] == [
            "engine.reclaim_idle_seconds_not_positive_using_default"
        ]


class TestBaseBrokerReclaimHook:
    def test_inline_broker_claims_nothing(self, test_domain):
        """A broker without consumer-owned pending entries has nothing to claim."""
        broker = test_domain.brokers["default"]
        broker.publish("orders", {"name": "first"})
        broker.read("orders", "group", 1)

        assert broker._reclaim_idle_pending("orders", "group", None, 1) == {}

    def test_broker_subscription_initialize_seeds_nothing(self, test_domain):
        engine = Engine(test_domain, test_mode=True)
        subscription = _subscription(engine, retry_delay_seconds=0)

        engine.loop.run_until_complete(subscription.initialize())

        assert subscription.retry_counts == {}
