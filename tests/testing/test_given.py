"""Tests for the ``given`` DSL in ``protean.testing``.

Exercises the full integration test pipeline:
    given(Aggregate, *events).process(command) → AggregateResult
"""

from enum import Enum
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String
from protean.testing import EventLog, given
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------
class OrderStatus(Enum):
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    CANCELLED = "CANCELLED"


# Events
class OrderCreated(BaseEvent):
    order_id = Identifier(required=True)
    customer = String(required=True)
    amount = Float(required=True)


class OrderConfirmed(BaseEvent):
    order_id = Identifier(required=True)


class PaymentInitiated(BaseEvent):
    order_id = Identifier(required=True)
    payment_id = String(required=True)


class OrderCancelled(BaseEvent):
    order_id = Identifier(required=True)
    reason = String()


# Commands
class CreateOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer = String(required=True)
    amount = Float(required=True)


class ConfirmOrder(BaseCommand):
    order_id = Identifier(identifier=True)


class InitiatePayment(BaseCommand):
    order_id = Identifier(identifier=True)
    payment_id = String(required=True)


class CancelOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    reason = String()


# Aggregate
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer = String(required=True)
    amount = Float(required=True)
    status = String(choices=OrderStatus)
    payment_id = String()

    @classmethod
    def create(cls, order_id: str, customer: str, amount: float) -> "Order":
        order = cls._create_new(order_id=order_id)
        order.raise_(OrderCreated(order_id=order_id, customer=customer, amount=amount))
        return order

    def confirm(self) -> None:
        if self.status != OrderStatus.CREATED.value:
            raise ValidationError(
                {"order": [f"Cannot confirm order in status {self.status}"]}
            )
        self.raise_(OrderConfirmed(order_id=self.order_id))

    def initiate_payment(self, payment_id: str) -> None:
        if self.status != OrderStatus.CONFIRMED.value:
            raise ValidationError({"order": ["Order must be confirmed before payment"]})
        self.raise_(PaymentInitiated(order_id=self.order_id, payment_id=payment_id))

    def cancel(self, reason: str = "") -> None:
        if self.status == OrderStatus.CANCELLED.value:
            raise ValidationError({"order": ["Order is already cancelled"]})
        self.raise_(OrderCancelled(order_id=self.order_id, reason=reason))

    @apply
    def on_created(self, event: OrderCreated) -> None:
        self.order_id = event.order_id
        self.customer = event.customer
        self.amount = event.amount
        self.status = OrderStatus.CREATED.value

    @apply
    def on_confirmed(self, event: OrderConfirmed) -> None:
        self.status = OrderStatus.CONFIRMED.value

    @apply
    def on_payment_initiated(self, event: PaymentInitiated) -> None:
        self.status = OrderStatus.PAYMENT_PENDING.value
        self.payment_id = event.payment_id

    @apply
    def on_cancelled(self, event: OrderCancelled) -> None:
        self.status = OrderStatus.CANCELLED.value


# Command handlers
class OrderCommandHandler(BaseCommandHandler):
    @handle(CreateOrder)
    def handle_create(self, command: CreateOrder) -> str:
        order = Order.create(
            order_id=command.order_id,
            customer=command.customer,
            amount=command.amount,
        )
        current_domain.repository_for(Order).add(order)
        return order.order_id

    @handle(ConfirmOrder)
    def handle_confirm(self, command: ConfirmOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm()
        repo.add(order)

    @handle(InitiatePayment)
    def handle_payment(self, command: InitiatePayment) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.initiate_payment(command.payment_id)
        repo.add(order)

    @handle(CancelOrder)
    def handle_cancel(self, command: CancelOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.cancel(command.reason)
        repo.add(order)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(OrderCreated, part_of=Order)
    test_domain.register(OrderConfirmed, part_of=Order)
    test_domain.register(PaymentInitiated, part_of=Order)
    test_domain.register(OrderCancelled, part_of=Order)
    test_domain.register(CreateOrder, part_of=Order)
    test_domain.register(ConfirmOrder, part_of=Order)
    test_domain.register(InitiatePayment, part_of=Order)
    test_domain.register(CancelOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.init(traverse=False)


@pytest.fixture
def order_id():
    return str(uuid4())


@pytest.fixture
def order_created(order_id):
    return OrderCreated(order_id=order_id, customer="Alice", amount=99.99)


@pytest.fixture
def order_confirmed(order_id):
    return OrderConfirmed(order_id=order_id)


@pytest.fixture
def payment_initiated(order_id):
    return PaymentInitiated(order_id=order_id, payment_id="pay-001")


# ---------------------------------------------------------------------------
# Tests: given() with no history (create commands)
# ---------------------------------------------------------------------------
class TestGivenNoHistory:
    @pytest.mark.eventstore
    def test_create_command(self):
        """given(Aggregate).process(create_command) works for new aggregates."""
        oid = str(uuid4())
        result = given(Order).process(
            CreateOrder(order_id=oid, customer="Alice", amount=50.0)
        )

        assert result.accepted
        assert not result.rejected
        assert result.rejection is None
        assert OrderCreated in result.events
        assert len(result.events) == 1

    @pytest.mark.eventstore
    def test_create_command_aggregate_state(self):
        """After processing a create command, the aggregate state is accessible."""
        oid = str(uuid4())
        result = given(Order).process(
            CreateOrder(order_id=oid, customer="Bob", amount=123.45)
        )

        assert result.customer == "Bob"
        assert result.amount == 123.45
        assert result.status == OrderStatus.CREATED.value
        assert result.order_id == oid

    @pytest.mark.eventstore
    def test_create_command_event_attributes(self):
        """Event attributes are accessible through the EventLog."""
        oid = str(uuid4())
        result = given(Order).process(
            CreateOrder(order_id=oid, customer="Charlie", amount=75.0)
        )

        event = result.events[OrderCreated]
        assert event.order_id == oid
        assert event.customer == "Charlie"
        assert event.amount == 75.0


# ---------------------------------------------------------------------------
# Tests: given() with history
# ---------------------------------------------------------------------------
class TestGivenWithHistory:
    @pytest.mark.eventstore
    def test_single_history_event(self, order_id, order_created):
        """given(Aggregate, event).process(command) seeds one event."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        assert result.accepted
        assert result.status == OrderStatus.CONFIRMED.value
        assert OrderConfirmed in result.events
        assert len(result.events) == 1

    @pytest.mark.eventstore
    def test_multiple_history_events(self, order_id, order_created, order_confirmed):
        """given(Aggregate, e1, e2).process(command) seeds multiple events."""
        result = given(Order, order_created, order_confirmed).process(
            InitiatePayment(order_id=order_id, payment_id="pay-42")
        )

        assert result.accepted
        assert result.status == OrderStatus.PAYMENT_PENDING.value
        assert result.payment_id == "pay-42"
        assert PaymentInitiated in result.events

    @pytest.mark.eventstore
    def test_preserves_aggregate_history_state(self, order_id, order_created):
        """Aggregate state reflects all given events before the command."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        # State from the initial OrderCreated event is preserved
        assert result.customer == "Alice"
        assert result.amount == 99.99


# ---------------------------------------------------------------------------
# Tests: .after() chaining
# ---------------------------------------------------------------------------
class TestAfterChaining:
    @pytest.mark.eventstore
    def test_after_adds_more_history(self, order_id, order_created, order_confirmed):
        """.after() accumulates additional history events."""
        result = (
            given(Order, order_created)
            .after(order_confirmed)
            .process(InitiatePayment(order_id=order_id, payment_id="pay-99"))
        )

        assert result.accepted
        assert result.status == OrderStatus.PAYMENT_PENDING.value

    @pytest.mark.eventstore
    def test_multiple_after_calls(self, order_id, order_created, order_confirmed):
        """.after() can be called multiple times."""
        payment = PaymentInitiated(order_id=order_id, payment_id="pay-x")
        result = (
            given(Order, order_created)
            .after(order_confirmed)
            .after(payment)
            .process(CancelOrder(order_id=order_id, reason="Changed mind"))
        )

        assert result.accepted
        assert result.status == OrderStatus.CANCELLED.value


# ---------------------------------------------------------------------------
# Tests: Command rejection
# ---------------------------------------------------------------------------
class TestCommandRejection:
    @pytest.mark.eventstore
    def test_rejected_command(self, order_id, order_created):
        """When a command raises an exception, the result is rejected."""
        # Try to initiate payment on a non-confirmed order
        result = given(Order, order_created).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )

        assert result.rejected
        assert not result.accepted
        assert result.rejection is not None
        assert isinstance(result.rejection, ValidationError)

    @pytest.mark.eventstore
    def test_rejected_events_are_empty(self, order_id, order_created):
        """A rejected command produces no new events."""
        result = given(Order, order_created).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )

        assert len(result.events) == 0
        assert PaymentInitiated not in result.events

    @pytest.mark.eventstore
    def test_rejected_aggregate_reflects_pre_command_state(
        self, order_id, order_created
    ):
        """On rejection, aggregate state reflects given events only."""
        result = given(Order, order_created).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )

        assert result.status == OrderStatus.CREATED.value
        assert result.customer == "Alice"

    @pytest.mark.eventstore
    def test_rejected_create_command_no_history(self):
        """Rejection with no given events leaves aggregate as None."""
        # ConfirmOrder requires the aggregate to exist; with no history
        # events, the repository can't find it → exception
        result = given(Order).process(ConfirmOrder(order_id="nonexistent-id"))

        assert result.rejected
        assert result.rejection is not None
        assert len(result.events) == 0
        assert result.aggregate is None

    @pytest.mark.eventstore
    def test_rejection_message(self, order_id, order_created):
        """The rejection exception carries the expected message."""
        result = given(Order, order_created).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )

        assert "must be confirmed" in str(result.rejection)


# ---------------------------------------------------------------------------
# Tests: AggregateResult properties
# ---------------------------------------------------------------------------
class TestAggregateResultProperties:
    @pytest.mark.eventstore
    def test_aggregate_property(self, order_id, order_created):
        """The .aggregate property exposes the raw aggregate."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        assert result.aggregate is not None
        assert isinstance(result.aggregate, Order)
        assert result.aggregate.order_id == order_id

    @pytest.mark.eventstore
    def test_events_property_returns_event_log(self, order_id, order_created):
        """The .events property returns an EventLog instance."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        assert isinstance(result.events, EventLog)

    @pytest.mark.eventstore
    def test_getattr_proxies_to_aggregate(self, order_id, order_created):
        """Attribute access on the result proxies to the aggregate."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        # These all proxy to the aggregate
        assert result.order_id == order_id
        assert result.customer == "Alice"
        assert result.amount == 99.99
        assert result.status == OrderStatus.CONFIRMED.value

    @pytest.mark.eventstore
    def test_getattr_before_process_raises(self):
        """Accessing aggregate attributes before .process() raises."""
        result = given(Order)

        with pytest.raises(AttributeError, match="Did you call .process"):
            _ = result.status

    def test_getattr_private_attribute_raises(self):
        """Accessing a private attribute raises AttributeError directly."""
        result = given(Order)

        with pytest.raises(AttributeError):
            _ = result._some_private_attr

    def test_repr_pending(self):
        """Repr shows 'pending' before process()."""
        result = given(Order)
        assert "pending" in repr(result)
        assert "Order" in repr(result)

    @pytest.mark.eventstore
    def test_repr_accepted(self, order_id, order_created):
        """Repr shows 'accepted' after successful process()."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))
        assert "accepted" in repr(result)

    @pytest.mark.eventstore
    def test_repr_rejected(self, order_id, order_created):
        """Repr shows 'rejected' after failed process()."""
        result = given(Order, order_created).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )
        assert "rejected" in repr(result)


# ---------------------------------------------------------------------------
# Tests: Event count and types
# ---------------------------------------------------------------------------
class TestEventCounting:
    @pytest.mark.eventstore
    def test_single_new_event(self, order_id, order_created):
        """A command that raises one event produces len(events) == 1."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        assert len(result.events) == 1
        assert result.events.types == [OrderConfirmed]

    @pytest.mark.eventstore
    def test_new_events_exclude_given_events(
        self, order_id, order_created, order_confirmed
    ):
        """Only events raised by the command appear in .events,
        not the given history events."""
        result = given(Order, order_created, order_confirmed).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )

        assert len(result.events) == 1
        assert result.events.types == [PaymentInitiated]
        # Given events should NOT appear
        assert OrderCreated not in result.events
        assert OrderConfirmed not in result.events

    @pytest.mark.eventstore
    def test_create_command_event_count(self):
        """A create command with no history produces exactly one event."""
        oid = str(uuid4())
        result = given(Order).process(
            CreateOrder(order_id=oid, customer="Eve", amount=200.0)
        )

        assert len(result.events) == 1


# ---------------------------------------------------------------------------
# Tests: Method chaining
# ---------------------------------------------------------------------------
class TestMethodChaining:
    @pytest.mark.eventstore
    def test_process_returns_self(self, order_id, order_created):
        """.process() returns the AggregateResult for fluent chaining."""
        result_obj = given(Order, order_created)
        returned = result_obj.process(ConfirmOrder(order_id=order_id))

        assert returned is result_obj

    @pytest.mark.eventstore
    def test_after_returns_self(self, order_created, order_confirmed):
        """.after() returns the AggregateResult for fluent chaining."""
        result_obj = given(Order, order_created)
        returned = result_obj.after(order_confirmed)

        assert returned is result_obj

    @pytest.mark.eventstore
    def test_full_fluent_chain(self, order_id, order_created, order_confirmed):
        """The full given().after().process() chain works end-to-end."""
        result = (
            given(Order, order_created)
            .after(order_confirmed)
            .process(InitiatePayment(order_id=order_id, payment_id="pay-chain"))
        )

        assert result.accepted
        assert result.payment_id == "pay-chain"
        assert PaymentInitiated in result.events


# ---------------------------------------------------------------------------
# Tests: Multi-command chaining
# ---------------------------------------------------------------------------
class TestMultiCommandChaining:
    @pytest.mark.eventstore
    def test_two_commands(self):
        """Chaining two .process() calls builds state through the pipeline."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(ConfirmOrder(order_id=oid))
        )

        assert result.accepted
        assert result.status == OrderStatus.CONFIRMED.value
        assert result.customer == "Alice"

    @pytest.mark.eventstore
    def test_three_commands(self):
        """Chaining three .process() calls works end-to-end."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Bob", amount=50.0))
            .process(ConfirmOrder(order_id=oid))
            .process(InitiatePayment(order_id=oid, payment_id="pay-chain"))
        )

        assert result.accepted
        assert result.status == OrderStatus.PAYMENT_PENDING.value
        assert result.payment_id == "pay-chain"

    @pytest.mark.eventstore
    def test_events_contains_only_last_command(self):
        """.events contains events from the last .process() only."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(ConfirmOrder(order_id=oid))
        )

        assert len(result.events) == 1
        assert OrderConfirmed in result.events
        assert OrderCreated not in result.events

    @pytest.mark.eventstore
    def test_all_events_contains_all_commands(self):
        """.all_events contains events from all .process() calls."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(ConfirmOrder(order_id=oid))
            .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
        )

        assert len(result.all_events) == 3
        assert OrderCreated in result.all_events
        assert OrderConfirmed in result.all_events
        assert PaymentInitiated in result.all_events

    @pytest.mark.eventstore
    def test_all_events_preserves_order(self):
        """.all_events maintains chronological order."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(ConfirmOrder(order_id=oid))
        )

        assert result.all_events.types == [OrderCreated, OrderConfirmed]

    @pytest.mark.eventstore
    def test_chaining_with_given_events(self):
        """Chaining works when given events seed the initial state."""
        oid = str(uuid4())
        order_created = OrderCreated(order_id=oid, customer="Alice", amount=99.99)
        result = (
            given(Order, order_created)
            .process(ConfirmOrder(order_id=oid))
            .process(InitiatePayment(order_id=oid, payment_id="pay-x"))
        )

        assert result.accepted
        assert result.status == OrderStatus.PAYMENT_PENDING.value
        # .events is from the last command only
        assert len(result.events) == 1
        assert PaymentInitiated in result.events
        # .all_events has both commands' events (not given events)
        assert len(result.all_events) == 2
        assert OrderConfirmed in result.all_events
        assert PaymentInitiated in result.all_events

    @pytest.mark.eventstore
    def test_rejection_mid_chain(self):
        """Rejection in a chained command captures the error."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
        )

        assert result.rejected
        assert isinstance(result.rejection, ValidationError)
        assert "must be confirmed" in str(result.rejection)
        # Aggregate reflects state before the failed command
        assert result.status == OrderStatus.CREATED.value

    @pytest.mark.eventstore
    def test_rejection_mid_chain_no_new_events(self):
        """A rejected chained command produces no new events."""
        oid = str(uuid4())
        result = (
            given(Order)
            .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
            .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
        )

        assert len(result.events) == 0

    @pytest.mark.eventstore
    def test_process_returns_self_on_chain(self):
        """.process() returns self for identity-based chaining."""
        oid = str(uuid4())
        result = given(Order)
        r1 = result.process(CreateOrder(order_id=oid, customer="A", amount=1.0))
        r2 = r1.process(ConfirmOrder(order_id=oid))

        assert r1 is result
        assert r2 is result

    @pytest.mark.eventstore
    def test_accepted_rejected_reflects_last_command(self):
        """.accepted/.rejected reflects only the last .process() call."""
        oid = str(uuid4())
        result = given(Order).process(
            CreateOrder(order_id=oid, customer="Alice", amount=99.99)
        )
        assert result.accepted

        # Second command fails
        result.process(InitiatePayment(order_id=oid, payment_id="pay-001"))
        assert result.rejected
        assert not result.accepted


# ---------------------------------------------------------------------------
# Tests: rejection_messages
# ---------------------------------------------------------------------------
class TestRejectionMessages:
    @pytest.mark.eventstore
    def test_rejection_messages_on_validation_error(self, order_id, order_created):
        """rejection_messages flattens ValidationError messages."""
        result = given(Order, order_created).process(
            InitiatePayment(order_id=order_id, payment_id="pay-001")
        )

        assert result.rejected
        assert "Order must be confirmed before payment" in result.rejection_messages

    @pytest.mark.eventstore
    def test_rejection_messages_when_accepted(self, order_id, order_created):
        """rejection_messages is empty when accepted."""
        result = given(Order, order_created).process(ConfirmOrder(order_id=order_id))

        assert result.rejection_messages == []

    @pytest.mark.eventstore
    def test_rejection_messages_on_non_validation_error(self):
        """rejection_messages wraps non-ValidationError as [str(exc)]."""
        result = given(Order).process(ConfirmOrder(order_id="nonexistent"))

        assert result.rejected
        assert len(result.rejection_messages) == 1
        assert isinstance(result.rejection_messages[0], str)
