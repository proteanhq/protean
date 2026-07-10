"""Re-entrant cascade under synchronous processing (issue #1048, ADR-0016).

A multi-step process manager whose handler dispatches the next command with
``current_domain.process(..., asynchronous=False)`` must advance past step 1
under ``event_processing = "sync"``. Before breadth-first dispatch, the next
event was processed re-entrantly — before the current step's transition was
persisted — so ``_load_or_create`` read an empty PM stream and silently skipped
the step.

Unlike ``test_sync_dispatch_integration.py`` (which drives each step from a
separate top-level aggregate save), these tests drive the cascade from *within*
a single handler, which is where the re-entrancy bug lives.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.exceptions import ValidationError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

# --- Aggregates / commands / events ---


class Order(BaseAggregate):
    customer = String()


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer = String()


class OrderPlaced(BaseEvent):
    order_id = Identifier()
    customer = String()


class Reservation(BaseAggregate):
    order_id = Identifier()


class ReserveStock(BaseCommand):
    order_id = Identifier(identifier=True)


class StockReserved(BaseEvent):
    order_id = Identifier()


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        order = Order(id=command.order_id, customer=command.customer)
        order.raise_(OrderPlaced(order_id=command.order_id, customer=command.customer))
        current_domain.repository_for(Order).add(order)


class ReservationCommandHandler(BaseCommandHandler):
    @handle(ReserveStock)
    def reserve(self, command: ReserveStock) -> None:
        reservation = Reservation(order_id=command.order_id)
        reservation.raise_(StockReserved(order_id=command.order_id))
        current_domain.repository_for(Reservation).add(reservation)


class FulfillmentSaga(BaseProcessManager):
    order_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "reserving"
        # Dispatch the next command from *inside* the handler — this raises
        # StockReserved synchronously and is the re-entrant shape under test.
        current_domain.process(
            ReserveStock(order_id=event.order_id), asynchronous=False
        )

    @handle(StockReserved, correlate="order_id")
    def on_reserved(self, event: StockReserved) -> None:
        self.status = "reserved"


class ExplodingSaga(BaseProcessManager):
    """A saga whose second step raises, to prove errors still surface."""

    order_id = Identifier()

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        current_domain.process(
            ReserveStock(order_id=event.order_id), asynchronous=False
        )

    @handle(StockReserved, correlate="order_id")
    def on_reserved(self, event: StockReserved) -> None:
        raise ValidationError({"stock": ["boom"]})


class OrderView(BaseProjection):
    order_id = Identifier(identifier=True)
    status = String()


class OrderViewProjector(BaseProjector):
    """Create-on-OrderPlaced, update-on-StockReserved. The update's get() fails
    with ObjectNotFoundError if the nested event's projector runs before the
    originating event's projector."""

    @on(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        current_domain.repository_for(OrderView).add(
            OrderView(order_id=event.order_id, status="placed")
        )

    @on(StockReserved)
    def on_reserved(self, event: StockReserved) -> None:
        view = current_domain.repository_for(OrderView).get(event.order_id)
        view.status = "reserved"
        current_domain.repository_for(OrderView).add(view)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Reservation)
    test_domain.register(ReserveStock, part_of=Reservation)
    test_domain.register(StockReserved, part_of=Reservation)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.register(ReservationCommandHandler, part_of=Reservation)
    test_domain.init(traverse=False)


def _register_saga(test_domain, saga_cls):
    """Register a saga on the order/reservation streams and re-initialize.

    Each test opts into exactly the saga it needs (rather than a shared autouse
    registration) so the drained cascade has a single, unambiguous trace — the
    error test in particular must not also run the happy-path saga.
    """
    test_domain.register(
        saga_cls, stream_categories=["test::order", "test::reservation"]
    )
    test_domain.init(traverse=False)


def _pm_transitions(test_domain, pm_cls, order_id):
    stream = f"{pm_cls.meta_.stream_category}-{order_id}"
    return test_domain.event_store.store.read(stream)


class TestReentrantCascade:
    def test_multi_step_saga_advances_past_step_one(self, test_domain):
        """The saga's second step (on_reserved) runs, so the PM reaches
        'reserved' — not stuck at 'reserving' after only the start handler."""
        _register_saga(test_domain, FulfillmentSaga)
        order_id = str(uuid4())

        current_domain.process(
            PlaceOrder(order_id=order_id, customer="Ada"), asynchronous=False
        )

        transitions = _pm_transitions(test_domain, FulfillmentSaga, order_id)
        # Two transitions: on_placed (reserving) then on_reserved (reserved).
        assert len(transitions) == 2, [
            t.to_domain_object().state["status"] for t in transitions
        ]
        final = transitions[-1].to_domain_object()
        assert final.state["status"] == "reserved"

    def test_cascade_error_propagates_to_caller(self, test_domain):
        """A failure in a drained (deferred) handler still surfaces to the
        top-level process() caller — 'sync raises' is preserved."""
        _register_saga(test_domain, ExplodingSaga)

        order_id = str(uuid4())
        with pytest.raises(Exception) as exc_info:
            current_domain.process(
                PlaceOrder(order_id=order_id, customer="Ada"), asynchronous=False
            )
        # The original ValidationError message survives the wrapping.
        assert "boom" in str(exc_info.value)

    def test_projector_create_before_update_ordering(self, test_domain):
        """The originating event's projector (create) runs before the nested
        event's projector (update), so the update's get() resolves instead of
        raising ObjectNotFoundError."""
        test_domain.register(OrderView)
        test_domain.register(
            OrderViewProjector, projector_for=OrderView, aggregates=[Order, Reservation]
        )
        _register_saga(test_domain, FulfillmentSaga)

        order_id = str(uuid4())
        current_domain.process(
            PlaceOrder(order_id=order_id, customer="Ada"), asynchronous=False
        )

        view = current_domain.repository_for(OrderView).get(order_id)
        assert view.status == "reserved"
