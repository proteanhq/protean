"""Test mode stops the engine once every subscription has run out of work."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier
from protean.server.engine import Engine
from protean.server.subscription import TEST_MODE_MAX_TICK_PAUSE, BaseSubscription
from protean.server.subscription.partitioned_stream_subscription import (
    PartitionedStreamSubscription,
)
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

# The old test mode always ran this many 0.1s cycles before it could stop.
OLD_FIXED_CYCLES = 11

shipped: list[str] = []


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)


class OrderPlaced(BaseEvent):
    order_id: Identifier(identifier=True)


class Shipment(BaseAggregate):
    order_id: Identifier(identifier=True)


class ShipmentCreated(BaseEvent):
    order_id: Identifier(identifier=True)


class OrderEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def create_shipment(self, event: OrderPlaced) -> None:
        shipment = Shipment(order_id=event.order_id)
        shipment.raise_(ShipmentCreated(order_id=event.order_id))
        current_domain.repository_for(Shipment).add(shipment)


class ShipmentEventHandler(BaseEventHandler):
    @handle(ShipmentCreated)
    def record(self, event: ShipmentCreated) -> None:
        shipped.append(event.order_id)


class Parcel(BaseAggregate):
    parcel_id: Identifier(identifier=True)


class ParcelLost(BaseEvent):
    parcel_id: Identifier(identifier=True)


class FailingParcelHandler(BaseEventHandler):
    @handle(ParcelLost)
    def fail(self, event: ParcelLost) -> None:
        raise RuntimeError("handler failed")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    shipped.clear()
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(Order, stream_category="orders")
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Shipment, stream_category="shipments")
    test_domain.register(ShipmentCreated, part_of=Shipment)
    test_domain.register(OrderEventHandler, stream_category="orders")
    test_domain.register(ShipmentEventHandler, stream_category="shipments")
    test_domain.init(traverse=False)


def _cycles_run(caplog) -> int:
    return sum("Test mode cycle" in r.getMessage() for r in caplog.records)


def test_a_multi_step_flow_settles_before_the_engine_stops(test_domain, caplog):
    order_id = str(uuid4())
    order = Order(order_id=order_id)
    order.raise_(OrderPlaced(order_id=order_id))
    test_domain.repository_for(Order).add(order)

    with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
        Engine(domain=test_domain, test_mode=True).run()

    assert shipped == [order_id]
    assert 1 <= _cycles_run(caplog) < OLD_FIXED_CYCLES


def test_an_engine_with_nothing_to_do_stops_early(test_domain, caplog):
    with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
        Engine(domain=test_domain, test_mode=True).run()

    assert 1 <= _cycles_run(caplog) < OLD_FIXED_CYCLES


def test_a_failed_position_awaiting_retry_keeps_the_engine_busy(test_domain, caplog):
    test_domain.register(Parcel, stream_category="parcels")
    test_domain.register(ParcelLost, part_of=Parcel)
    test_domain.register(FailingParcelHandler, stream_category="parcels")
    test_domain.init(traverse=False)

    parcel = Parcel(parcel_id=str(uuid4()))
    parcel.raise_(ParcelLost(parcel_id=parcel.parcel_id))
    test_domain.repository_for(Parcel).add(parcel)

    with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
        Engine(domain=test_domain, test_mode=True).run()

    assert _cycles_run(caplog) == OLD_FIXED_CYCLES


def test_a_subscription_that_cannot_report_idleness_gets_the_old_wait(
    test_domain, caplog
):
    engine = Engine(domain=test_domain, test_mode=True)
    for subscription in engine._subscriptions.values():
        subscription.reports_idle = False

    with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
        engine.run()

    assert _cycles_run(caplog) == OLD_FIXED_CYCLES


class _Loop:
    """A stand-in poll loop carrying only the idle-tracking attributes."""

    def __init__(
        self,
        idle_started: float | None,
        work_finished: float | None = None,
        reports_idle: bool = True,
    ) -> None:
        self.last_idle_tick_started = idle_started
        self.last_work_tick_finished = work_finished
        self.reports_idle = reports_idle


class TestIdleCheck:
    @pytest.fixture
    def engine(self, test_domain):
        engine = Engine(domain=test_domain, test_mode=True)
        engine._subscriptions = {}
        engine._broker_subscriptions = {}
        engine._outbox_processors = {}
        return engine

    def test_idle_when_every_loop_ticked_empty_after_the_last_work(self, engine):
        engine._subscriptions = {"a": _Loop(5.0, work_finished=4.0)}
        engine._broker_subscriptions = {"b": _Loop(4.5)}
        engine._outbox_processors = {"c": _Loop(6.0)}
        assert engine._test_mode_idle() is True

    def test_idle_when_no_loop_ever_found_work(self, engine):
        engine._subscriptions = {"a": _Loop(1.0), "b": _Loop(2.0)}
        assert engine._test_mode_idle() is True

    def test_busy_while_a_loop_last_ticked_before_work_elsewhere_finished(self, engine):
        # "b" may have read its stream before "a" wrote a message to it.
        engine._subscriptions = {"a": _Loop(5.0, work_finished=4.0), "b": _Loop(3.0)}
        assert engine._test_mode_idle() is False

    def test_busy_on_a_tie_with_the_last_work(self, engine):
        engine._subscriptions = {"a": _Loop(5.0, work_finished=4.0), "b": _Loop(4.0)}
        assert engine._test_mode_idle() is False

    def test_busy_until_every_loop_has_ticked(self, engine):
        engine._subscriptions = {"a": _Loop(1.0), "b": _Loop(None)}
        assert engine._test_mode_idle() is False

    def test_busy_when_a_loop_cannot_report(self, engine):
        engine._subscriptions = {"a": _Loop(1.0), "b": _Loop(2.0, reports_idle=False)}
        assert engine._test_mode_idle() is False

    def test_an_object_without_the_flag_counts_as_unable_to_report(self, engine):
        engine._subscriptions = {"a": SimpleNamespace(last_idle_tick_started=1.0)}
        assert engine._test_mode_idle() is False

    def test_busy_while_shutting_down(self, engine):
        engine._subscriptions = {"a": _Loop(1.0)}
        engine.shutting_down = True
        assert engine._test_mode_idle() is False


class _Recording(BaseSubscription):
    subscriber_name = "recording"

    async def get_next_batch_of_messages(self) -> list:
        return []

    async def process_batch(self, messages) -> int:
        return 0


class TestTickTracking:
    def test_an_empty_tick_records_when_it_started(self, test_domain):
        sub = _Recording(Engine(domain=test_domain, test_mode=True))
        sub._record_tick(3.0, False)
        assert sub.last_idle_tick_started == 3.0
        assert sub.last_work_tick_finished is None

    def test_a_tick_with_work_records_when_it_finished(self, test_domain):
        sub = _Recording(Engine(domain=test_domain, test_mode=True))
        with patch("protean.server.subscription.time.monotonic", return_value=9.0):
            sub._record_tick(3.0, True)
        assert sub.last_work_tick_finished == 9.0
        assert sub.last_idle_tick_started is None

    def test_a_tick_that_cannot_tell_records_nothing(self, test_domain):
        sub = _Recording(Engine(domain=test_domain, test_mode=True))
        sub._record_tick(3.0, None)
        assert sub.last_idle_tick_started is None
        assert sub.last_work_tick_finished is None

    async def test_a_tick_override_returning_none_never_counts_as_idle(
        self, test_domain
    ):
        class LegacyTick(_Recording):
            async def tick(self):
                self.keep_going = False

        sub = LegacyTick(Engine(domain=test_domain, test_mode=True), tick_interval=0)
        await sub.poll()
        assert sub.last_idle_tick_started is None

    @pytest.mark.parametrize("recovered,expected_work", [(1, True), (0, False)])
    async def test_a_successful_recovery_counts_as_work(
        self, test_domain, recovered, expected_work
    ):
        test_domain.register(Parcel, stream_category="parcels")
        test_domain.register(ParcelLost, part_of=Parcel)
        test_domain.register(FailingParcelHandler, stream_category="parcels")
        test_domain.init(traverse=False)
        engine = Engine(domain=test_domain, test_mode=True)
        sub = next(iter(engine._subscriptions.values()))

        async def empty_tick() -> bool:
            return False

        async def recover() -> int:
            sub.keep_going = False
            return recovered

        sub.tick = empty_tick
        sub.maybe_run_recovery = recover
        await sub.poll()

        assert (sub.last_work_tick_finished is not None) is expected_work
        assert (sub.last_idle_tick_started is not None) is not expected_work

    def test_the_partitioned_subscription_cannot_report_idleness(self):
        assert PartitionedStreamSubscription.reports_idle is False
        assert BaseSubscription.reports_idle is True


class TestPauseBetweenTicks:
    @pytest.mark.parametrize(
        "test_mode,tick_interval,expected",
        [
            (True, 1, TEST_MODE_MAX_TICK_PAUSE),
            (True, 0.001, 0.001),
            (True, 0, 0),
            (False, 1, 1),
            (False, 0, 0),
        ],
    )
    async def test_pause(self, test_domain, test_mode, tick_interval, expected):
        engine = Engine(domain=test_domain, test_mode=test_mode)
        sub = _Recording(engine, tick_interval=tick_interval)
        slept: list[float] = []
        real_sleep = asyncio.sleep

        async def record(duration: float) -> None:
            slept.append(duration)
            await real_sleep(0)

        with patch("protean.server.subscription.asyncio.sleep", side_effect=record):
            await sub._pause_between_ticks()

        assert slept == [expected]


class TestStreamReadOutcome:
    """A stream read that swallowed a broker error is not an empty read."""

    @pytest.fixture
    def sub(self) -> StreamSubscription:
        return object.__new__(StreamSubscription)

    def test_messages_are_work(self, sub):
        assert sub._tick_outcome([("1", {})]) is True

    def test_an_empty_read_is_idle(self, sub):
        assert sub._tick_outcome([]) is False

    def test_an_empty_result_after_a_failed_read_is_unknown(self, sub):
        sub._read_failed = True
        assert sub._tick_outcome([]) is None

    async def test_a_failing_broker_read_marks_the_turn(self, sub):
        sub.broker = SimpleNamespace(
            read_blocking=lambda **kwargs: (_ for _ in ()).throw(OSError("down"))
        )
        sub.stream_category = "orders"
        sub.consumer_group = "group"
        sub.consumer_name = "consumer"
        sub.blocking_timeout_ms = 0
        sub._current_batch_size = lambda: 1

        assert await sub.get_next_batch_of_messages() == []
        assert sub._tick_outcome([]) is None
