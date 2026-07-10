"""Tests for the ``process_and_wait`` / ``drain`` integration-test helpers.

Exercises the full command runtime path in both synchronous and
asynchronous processing modes:

    command -> handler -> aggregate -> UoW commit -> outbox
            -> engine -> broker -> subscription -> projector -> read model
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.fields import Float, Identifier, String
from protean.testing import EventLog, ProcessResult, drain, process_and_wait
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer = String(required=True)
    amount = Float(required=True)


class Order(BaseAggregate):
    customer = String(required=True)
    amount = Float(required=True)
    status = String(default="PLACED")

    def place(self) -> None:
        self.raise_(
            OrderPlaced(order_id=self.id, customer=self.customer, amount=self.amount)
        )


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer = String(required=True)
    amount = Float(required=True)


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place(self, command: PlaceOrder) -> str:
        if command.amount <= 0:
            raise ValidationError({"amount": ["Amount must be positive"]})
        order = Order(
            id=command.order_id, customer=command.customer, amount=command.amount
        )
        order.place()
        current_domain.repository_for(Order).add(order)
        return order.id


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer = String()
    amount = Float()


class OrderSummaryProjector(BaseProjector):
    @on(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(
            OrderSummary(
                order_id=event.order_id,
                customer=event.customer,
                amount=event.amount,
            )
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.register(OrderSummary)
    test_domain.register(
        OrderSummaryProjector, projector_for=OrderSummary, aggregates=[Order]
    )
    test_domain.init(traverse=False)


@pytest.fixture
def order_id():
    return str(uuid4())


@pytest.fixture
def async_mode(test_domain):
    test_domain.config["command_processing"] = "async"
    test_domain.config["event_processing"] = "async"


def summary_exists(order_id: str) -> bool:
    """Read-model readiness predicate for ``until=`` drains."""
    try:
        current_domain.repository_for(OrderSummary).get(order_id)
        return True
    except ObjectNotFoundError:
        return False


# ---------------------------------------------------------------------------
# process_and_wait — synchronous mode (default test_domain config)
# ---------------------------------------------------------------------------
class TestProcessAndWaitSync:
    def test_returns_process_result(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )
        assert isinstance(outcome, ProcessResult)

    def test_repr_reflects_status_and_event_count(self, order_id):
        ok = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )
        assert repr(ok) == "<ProcessResult succeeded events=1>"

        bad = process_and_wait(
            PlaceOrder(order_id=str(uuid4()), customer="Alice", amount=-5.0)
        )
        assert repr(bad) == "<ProcessResult failed events=0>"

    def test_command_result_is_returned(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )
        assert outcome.result == order_id
        assert outcome.succeeded
        assert not outcome.failed
        assert outcome.error is None

    def test_events_fired_are_captured(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )
        assert isinstance(outcome.events, EventLog)
        assert OrderPlaced in outcome.events
        assert outcome.events[OrderPlaced].order_id == order_id
        assert outcome.events[OrderPlaced].customer == "Alice"

    def test_read_model_is_updated_inline(self, order_id):
        process_and_wait(PlaceOrder(order_id=order_id, customer="Alice", amount=99.99))

        summary = current_domain.repository_for(OrderSummary).get(order_id)
        assert summary.customer == "Alice"
        assert summary.amount == 99.99

    def test_explicit_domain_argument(self, test_domain, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Bob", amount=10.0),
            test_domain,
        )
        assert outcome.result == order_id

    def test_handler_error_is_captured_not_raised(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=-5.0)
        )
        assert outcome.failed
        assert outcome.error is not None
        assert isinstance(outcome.error, ValidationError)
        assert outcome.result is None

    def test_no_events_captured_on_failure(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=-5.0)
        )
        assert len(outcome.events) == 0
        assert OrderPlaced not in outcome.events

    def test_events_are_scoped_to_this_command(self):
        """Each call captures only its own correlation chain, not the whole store.

        Guards the correlation filter in ``_events_for_correlation``: a second
        command's events must not bleed into the first's ``ProcessResult`` (and
        vice versa), even though both are in the same event store.
        """
        first_id, second_id = str(uuid4()), str(uuid4())

        first = process_and_wait(
            PlaceOrder(order_id=first_id, customer="Alice", amount=10.0)
        )
        second = process_and_wait(
            PlaceOrder(order_id=second_id, customer="Bob", amount=20.0)
        )

        assert len(first.events) == 1
        assert first.events[OrderPlaced].order_id == first_id
        assert len(second.events) == 1
        assert second.events[OrderPlaced].order_id == second_id


# ---------------------------------------------------------------------------
# process_and_wait — asynchronous mode (engine-drained)
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("async_mode")
class TestProcessAndWaitAsync:
    def test_same_body_drains_engine(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )

        # Command result is the enqueue (store) position in async mode
        assert isinstance(outcome.result, int)
        assert outcome.error is None

        # Events fired are still captured from the correlation chain
        assert OrderPlaced in outcome.events
        assert outcome.events[OrderPlaced].order_id == order_id

        # Read model is updated after the engine drains
        summary = current_domain.repository_for(OrderSummary).get(order_id)
        assert summary.customer == "Alice"

    def test_until_predicate_stops_early(self, order_id):
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            until=lambda: summary_exists(order_id),
        )
        assert summary_exists(order_id)
        assert OrderPlaced in outcome.events

    def test_async_handler_failure_is_not_surfaced(self, order_id):
        """Submission succeeds; the async handler error is absorbed by the engine.

        The amount check lives inside the handler, so it fails only once the
        engine runs the command. ``process_and_wait`` reports submission
        success (``error is None``) and captures no events / read model —
        the negative counterpart to ``succeeded`` reflecting the async path.
        """
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=-5.0)
        )

        # Submission itself succeeded — the failure happens later, in the engine
        assert outcome.succeeded
        assert outcome.error is None

        # No event was raised and no read model was written
        assert OrderPlaced not in outcome.events
        assert not summary_exists(order_id)


# ---------------------------------------------------------------------------
# process_and_wait — mixed processing modes
# ---------------------------------------------------------------------------
class TestProcessAndWaitMixedMode:
    """Sync command handling with async event processing (and the reverse).

    A new config combination is a distinct entry point (config keys must reach
    every entry point), so both crossed modes are exercised.
    """

    def test_sync_command_async_events(self, test_domain, order_id):
        test_domain.config["command_processing"] = "sync"
        test_domain.config["event_processing"] = "async"

        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )

        # Sync command handler ran inline and returned the aggregate id
        assert outcome.result == order_id
        assert OrderPlaced in outcome.events

        # Projector runs asynchronously — drained before returning
        summary = current_domain.repository_for(OrderSummary).get(order_id)
        assert summary.customer == "Alice"

    def test_async_command_sync_events(self, test_domain, order_id):
        test_domain.config["command_processing"] = "async"
        test_domain.config["event_processing"] = "sync"

        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )

        # Async command → enqueue position; engine drains the handler
        assert isinstance(outcome.result, int)
        assert OrderPlaced in outcome.events
        summary = current_domain.repository_for(OrderSummary).get(order_id)
        assert summary.customer == "Alice"


# ---------------------------------------------------------------------------
# process_and_wait — real Redis broker (acceptance: "test (Redis)")
# ---------------------------------------------------------------------------
@pytest.mark.redis
@pytest.mark.usefixtures("async_mode")
class TestProcessAndWaitRedis:
    def test_same_body_drains_real_redis_broker(self, order_id):
        """The unchanged helper drives the full path over a real Redis stream."""
        outcome = process_and_wait(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99),
            until=lambda: summary_exists(order_id),
        )

        assert isinstance(outcome.result, int)
        assert OrderPlaced in outcome.events
        assert outcome.events[OrderPlaced].order_id == order_id

        summary = current_domain.repository_for(OrderSummary).get(order_id)
        assert summary.customer == "Alice"


# ---------------------------------------------------------------------------
# drain — bounded engine loop
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("async_mode")
class TestDrain:
    def test_drains_pending_work(self, order_id):
        current_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )

        cycles = drain()
        assert cycles == 1

        summary = current_domain.repository_for(OrderSummary).get(order_id)
        assert summary.customer == "Alice"

    def test_runs_until_predicate(self, order_id):
        current_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )

        cycles = drain(until=lambda: summary_exists(order_id))
        assert cycles >= 1
        assert summary_exists(order_id)

    def test_until_is_consulted_each_cycle_and_controls_stop(self):
        """The predicate is called every cycle and its return value stops the loop.

        A predicate that stays falsey for the first pass and flips truthy on
        the second forces exactly two cycles — proving ``until`` is both
        consulted and authoritative (not ignored, not short-circuited to one).
        """
        calls = []

        def flip_on_second() -> bool:
            calls.append(1)
            return len(calls) >= 2

        cycles = drain(until=flip_on_second, max_cycles=5)
        assert cycles == 2
        assert len(calls) == 2

    def test_bounded_by_max_cycles(self):
        calls = []

        def never() -> bool:
            calls.append(1)
            return False

        with pytest.warns(UserWarning, match="exhausted max_cycles=3"):
            cycles = drain(until=never, max_cycles=3)
        assert cycles == 3
        # Predicate consulted once per pass — proves the engine looped 3×,
        # not that the function merely echoed its argument.
        assert len(calls) == 3

    def test_no_warning_when_until_satisfied(self, order_id, recwarn):
        current_domain.process(
            PlaceOrder(order_id=order_id, customer="Alice", amount=99.99)
        )
        drain(until=lambda: summary_exists(order_id))
        assert not [w for w in recwarn.list if issubclass(w.category, UserWarning)]

    def test_explicit_domain_argument(self, test_domain, order_id):
        test_domain.process(PlaceOrder(order_id=order_id, customer="Bob", amount=5.0))
        cycles = drain(test_domain, max_cycles=5)
        assert cycles == 1

    def test_max_cycles_must_be_positive(self):
        with pytest.raises(ValueError, match="max_cycles must be at least 1"):
            drain(max_cycles=0)
