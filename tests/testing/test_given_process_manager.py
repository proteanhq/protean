"""Tests for the process manager testing DSL in ``protean.testing``.

Exercises the PM integration test pipeline:
    given(PMClass, *events) → ProcessManagerResult
    given(*events).results_in(PMClass) → ProcessManagerResult
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.fields import Float, Identifier, String
from protean.testing import EventSequence, ProcessManagerResult, given
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class Order(BaseAggregate):
    customer_id: Identifier()
    total: Float()
    status: String(default="new")


class Payment(BaseAggregate):
    order_id: Identifier()
    amount: Float()
    status: String(default="pending")


class Shipping(BaseAggregate):
    order_id: Identifier()
    status: String(default="pending")


# Events
class OrderPlaced(BaseEvent):
    order_id: Identifier()
    customer_id: Identifier()
    total: Float()


class PaymentConfirmed(BaseEvent):
    payment_id: Identifier()
    order_id: Identifier()
    amount: Float()


class PaymentFailed(BaseEvent):
    payment_id: Identifier()
    order_id: Identifier()
    reason: String()


class ShipmentDelivered(BaseEvent):
    order_id: Identifier()


# Process Manager
class OrderFulfillmentPM(BaseProcessManager):
    order_id: Identifier()
    payment_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        self.status = "cancelled"

    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
        self.status = "completed"
        self.mark_as_complete()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Payment)
    test_domain.register(PaymentConfirmed, part_of=Payment)
    test_domain.register(PaymentFailed, part_of=Payment)
    test_domain.register(Shipping)
    test_domain.register(ShipmentDelivered, part_of=Shipping)
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)


@pytest.fixture
def order_id():
    return str(uuid4())


@pytest.fixture
def order_placed(order_id):
    return OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)


@pytest.fixture
def payment_confirmed(order_id):
    return PaymentConfirmed(payment_id="PAY-1", order_id=order_id, amount=100.0)


@pytest.fixture
def payment_failed(order_id):
    return PaymentFailed(payment_id="PAY-1", order_id=order_id, reason="Insufficient funds")


@pytest.fixture
def shipment_delivered(order_id):
    return ShipmentDelivered(order_id=order_id)


# ---------------------------------------------------------------------------
# Tests: given(PMClass, *events) — basic usage
# ---------------------------------------------------------------------------
class TestGivenPMBasic:
    @pytest.mark.eventstore
    def test_single_start_event(self, order_placed):
        """given(PM, start_event) creates a PM and processes the event."""
        result = given(OrderFulfillmentPM, order_placed)

        assert isinstance(result, ProcessManagerResult)
        assert result.status == "awaiting_payment"
        assert result.transition_count == 1
        assert not result.is_complete

    @pytest.mark.eventstore
    def test_two_events(self, order_placed, payment_confirmed):
        """given(PM, e1, e2) processes both events in order."""
        result = given(OrderFulfillmentPM, order_placed, payment_confirmed)

        assert result.status == "awaiting_shipment"
        assert result.transition_count == 2
        assert not result.is_complete

    @pytest.mark.eventstore
    def test_full_lifecycle(self, order_placed, payment_confirmed, shipment_delivered):
        """given(PM, *events) tracks through to completion."""
        result = given(
            OrderFulfillmentPM,
            order_placed,
            payment_confirmed,
            shipment_delivered,
        )

        assert result.status == "completed"
        assert result.is_complete
        assert result.transition_count == 3

    @pytest.mark.eventstore
    def test_end_handler_marks_complete(self, order_placed, payment_failed):
        """end=True handler auto-marks the PM as complete."""
        result = given(OrderFulfillmentPM, order_placed, payment_failed)

        assert result.status == "cancelled"
        assert result.is_complete
        assert result.transition_count == 2


# ---------------------------------------------------------------------------
# Tests: ProcessManagerResult properties
# ---------------------------------------------------------------------------
class TestProcessManagerResultProperties:
    @pytest.mark.eventstore
    def test_not_started_with_no_events(self):
        """PM with no events is not started."""
        result = given(OrderFulfillmentPM)

        assert result.not_started
        assert not result.is_complete
        assert result.transition_count == 0

    @pytest.mark.eventstore
    def test_process_manager_property(self, order_placed):
        """The .process_manager property exposes the raw PM instance."""
        result = given(OrderFulfillmentPM, order_placed)

        assert result.process_manager is not None
        assert isinstance(result.process_manager, OrderFulfillmentPM)

    @pytest.mark.eventstore
    def test_process_manager_property_none_when_not_started(self):
        """The .process_manager is None when no events were processed."""
        result = given(OrderFulfillmentPM)

        assert result.process_manager is None

    @pytest.mark.eventstore
    def test_getattr_proxies_to_pm(self, order_placed, payment_confirmed):
        """Attribute access on the result proxies to the PM instance."""
        result = given(OrderFulfillmentPM, order_placed, payment_confirmed)

        assert result.order_id == order_placed.order_id
        assert result.payment_id == "PAY-1"

    @pytest.mark.eventstore
    def test_getattr_not_started_raises(self):
        """Accessing PM attributes when not started raises AttributeError."""
        result = given(OrderFulfillmentPM)

        with pytest.raises(AttributeError, match="Process manager not found"):
            _ = result.status

    def test_getattr_private_attribute_raises(self):
        """Accessing a private attribute raises AttributeError directly."""
        result = given(OrderFulfillmentPM)

        with pytest.raises(AttributeError):
            _ = result._some_private_attr


# ---------------------------------------------------------------------------
# Tests: repr
# ---------------------------------------------------------------------------
class TestProcessManagerResultRepr:
    @pytest.mark.eventstore
    def test_repr_not_started(self):
        """Repr shows 'not_started' when no events processed."""
        result = given(OrderFulfillmentPM)
        assert "not_started" in repr(result)
        assert "OrderFulfillmentPM" in repr(result)

    @pytest.mark.eventstore
    def test_repr_with_transitions(self, order_placed):
        """Repr shows transition count."""
        result = given(OrderFulfillmentPM, order_placed)
        assert "transitions=1" in repr(result)

    @pytest.mark.eventstore
    def test_repr_complete(self, order_placed, payment_failed):
        """Repr shows 'complete' when PM is done."""
        result = given(OrderFulfillmentPM, order_placed, payment_failed)
        assert "complete" in repr(result)


# ---------------------------------------------------------------------------
# Tests: given() dispatch detection
# ---------------------------------------------------------------------------
class TestGivenDispatch:
    @pytest.mark.eventstore
    def test_given_pm_class_returns_pm_result(self, order_placed):
        """given(PMClass, ...) returns ProcessManagerResult."""
        result = given(OrderFulfillmentPM, order_placed)
        assert isinstance(result, ProcessManagerResult)

    @pytest.mark.eventstore
    def test_given_events_returns_event_sequence(self, order_placed):
        """given(event, ...) returns EventSequence."""
        result = given(order_placed)
        assert isinstance(result, EventSequence)


# ---------------------------------------------------------------------------
# Tests: EventSequence.results_in()
# ---------------------------------------------------------------------------
class TestResultsIn:
    @pytest.mark.eventstore
    def test_results_in_basic(self, order_id, order_placed, payment_confirmed):
        """EventSequence.results_in(PM, id=...) works."""
        result = given(order_placed, payment_confirmed).results_in(
            OrderFulfillmentPM, id=order_id
        )

        assert isinstance(result, ProcessManagerResult)
        assert result.status == "awaiting_shipment"
        assert result.transition_count == 2

    @pytest.mark.eventstore
    def test_results_in_full_lifecycle(
        self, order_id, order_placed, payment_confirmed, shipment_delivered
    ):
        """results_in() works through full lifecycle."""
        result = given(
            order_placed, payment_confirmed, shipment_delivered
        ).results_in(OrderFulfillmentPM, id=order_id)

        assert result.is_complete
        assert result.status == "completed"
        assert result.transition_count == 3

    @pytest.mark.eventstore
    def test_results_in_without_identity(self, order_placed, payment_confirmed):
        """results_in() without identity infers correlation from events."""
        result = given(order_placed, payment_confirmed).results_in(
            OrderFulfillmentPM
        )

        assert result.status == "awaiting_shipment"
        assert result.transition_count == 2


# ---------------------------------------------------------------------------
# Tests: Correlation value inference
# ---------------------------------------------------------------------------
class TestCorrelationInference:
    @pytest.mark.eventstore
    def test_correlation_inferred_from_start_event(self, order_id, order_placed):
        """Correlation value is inferred from the first event."""
        result = given(OrderFulfillmentPM, order_placed)

        assert result.order_id == order_id
        assert result.transition_count == 1

    @pytest.mark.eventstore
    def test_multiple_instances_separate(self):
        """Different correlation values create separate PM instances."""
        oid1 = str(uuid4())
        oid2 = str(uuid4())

        event1 = OrderPlaced(order_id=oid1, customer_id="C1", total=50.0)
        event2 = OrderPlaced(order_id=oid2, customer_id="C2", total=75.0)
        pay1 = PaymentConfirmed(payment_id="P1", order_id=oid1, amount=50.0)

        # Process events for two separate PM instances
        result1 = given(OrderFulfillmentPM, event1, pay1)
        assert result1.status == "awaiting_shipment"

        # The second PM should work independently
        result2 = given(OrderFulfillmentPM, event2)
        assert result2.status == "awaiting_payment"


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    @pytest.mark.eventstore
    def test_non_start_event_without_existing_pm(self):
        """Non-start events with no existing PM are skipped."""
        # PaymentConfirmed is not a start event, so if no PM exists,
        # the handler should be skipped
        event = PaymentConfirmed(
            payment_id="PAY-1", order_id="nonexistent", amount=100.0
        )
        result = given(OrderFulfillmentPM, event)

        assert result.not_started
        assert result.transition_count == 0

    @pytest.mark.eventstore
    def test_events_after_completion_skipped(
        self, order_placed, payment_failed, shipment_delivered
    ):
        """Events after PM completion are skipped."""
        result = given(
            OrderFulfillmentPM,
            order_placed,
            payment_failed,      # end=True → marks complete
            shipment_delivered,   # should be skipped
        )

        assert result.status == "cancelled"
        assert result.is_complete
        # Only 2 transitions recorded (3rd event skipped)
        assert result.transition_count == 2

    @pytest.mark.eventstore
    def test_infer_correlation_value_with_no_events(self):
        """_infer_correlation_value returns None when events list is empty."""
        result = ProcessManagerResult(OrderFulfillmentPM)
        # Manually test the defensive guard
        assert result._infer_correlation_value() is None

    @pytest.mark.eventstore
    def test_infer_correlation_value_no_correlate_spec(self, order_placed):
        """_infer_correlation_value returns None when handler lacks correlate."""
        result = ProcessManagerResult(OrderFulfillmentPM, [order_placed])
        # Temporarily remove _correlate from the handler to test the guard
        handlers = OrderFulfillmentPM._handlers.get(
            order_placed.__class__.__type__
        )
        handler = next(iter(handlers))
        original = handler._correlate
        try:
            handler._correlate = None
            # Re-create to test inference with no correlate
            fresh = ProcessManagerResult.__new__(ProcessManagerResult)
            fresh._pm_cls = OrderFulfillmentPM
            fresh._events = [order_placed]
            assert fresh._infer_correlation_value() is None
        finally:
            handler._correlate = original

    @pytest.mark.eventstore
    def test_unrecognized_event_type_results_not_started(self, test_domain):
        """An event with no matching PM handler results in not_started."""
        # Create a PM that only handles OrderPlaced — register a separate
        # one-handler PM for this test
        class MinimalPM(BaseProcessManager):
            order_id: Identifier()
            status: String(default="new")

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_order_placed(self, event: OrderPlaced) -> None:
                self.order_id = event.order_id
                self.status = "started"

        test_domain.register(
            MinimalPM,
            stream_categories=["test::order"],
        )
        test_domain.init(traverse=False)

        # Send an event that MinimalPM doesn't handle — no handler match
        # so _infer_correlation_value returns None → not_started
        unhandled_event = PaymentConfirmed(
            payment_id="PAY-1", order_id="o1", amount=100.0
        )
        result = given(MinimalPM, unhandled_event)

        assert result.not_started
        assert result.transition_count == 0
