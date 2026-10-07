# --8<-- [start:domain]
from uuid import uuid4

from protean import Domain, apply, handle
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String, ValueObject
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")


@domain.value_object
class Pricing:
    grand_total: Float(required=True)


@domain.event(part_of="Order")
class OrderCreated:
    order_id: Identifier(required=True)
    customer: String(required=True)
    amount: Float(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)


@domain.event(part_of="Order")
class PaymentPending:
    order_id: Identifier(required=True)
    payment_id: String(required=True)


@domain.event(part_of="Order")
class PaymentFailed:
    order_id: Identifier(required=True)
    payment_id: String(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    order_id: Identifier(identifier=True)
    customer: String(max_length=100)
    pricing = ValueObject(Pricing)
    status: String(max_length=20)

    @classmethod
    def create(cls, order_id, customer, amount):
        order = cls._create_new(order_id=order_id)
        order.raise_(OrderCreated(order_id=order_id, customer=customer, amount=amount))
        return order

    def confirm(self):
        self.raise_(OrderConfirmed(order_id=self.order_id))

    def initiate_payment(self, payment_id):
        if self.status != "CONFIRMED":
            raise ValidationError(
                {"status": ["Order must be confirmed before payment"]}
            )
        self.raise_(PaymentPending(order_id=self.order_id, payment_id=payment_id))

    @apply
    def on_created(self, event: OrderCreated):
        self.order_id = event.order_id
        self.customer = event.customer
        self.pricing = Pricing(grand_total=event.amount)
        self.status = "CREATED"

    @apply
    def on_confirmed(self, event: OrderConfirmed):
        self.status = "CONFIRMED"

    @apply
    def on_payment_pending(self, event: PaymentPending):
        self.status = "PAYMENT_PENDING"

    @apply
    def on_payment_failed(self, event: PaymentFailed):
        self.status = "CONFIRMED"


@domain.command(part_of=Order)
class CreateOrder:
    order_id: Identifier(identifier=True)
    customer: String(required=True)
    amount: Float(required=True)


@domain.command(part_of=Order)
class ConfirmOrder:
    order_id: Identifier(identifier=True)


@domain.command(part_of=Order)
class InitiatePayment:
    order_id: Identifier(identifier=True)
    payment_id: String(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(CreateOrder)
    def create_order(self, command: CreateOrder):
        order = Order.create(command.order_id, command.customer, command.amount)
        current_domain.repository_for(Order).add(order)
        return order.order_id  # the DSL finds the new aggregate by this id

    @handle(ConfirmOrder)
    def confirm_order(self, command: ConfirmOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm()
        repo.add(order)

    @handle(InitiatePayment)
    def initiate_payment(self, command: InitiatePayment):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.initiate_payment(command.payment_id)
        repo.add(order)


# --8<-- [end:domain]


# --8<-- [start:conftest]
import pytest

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


# --8<-- [end:conftest]


# --8<-- [start:event_fixtures]
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
def initiate_payment(order_id):
    return InitiatePayment(order_id=order_id, payment_id="pay-001")


# --8<-- [end:event_fixtures]


# --8<-- [start:three_words]
from protean.testing import given


def test_given_after_process(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"


# --8<-- [end:three_words]


# --8<-- [start:chaining]
def test_multi_command_chaining():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"


# --8<-- [end:chaining]


# --8<-- [start:events_vs_all_events]
def test_events_hold_only_the_last_command():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
    )

    # .events has only the last command's events
    assert OrderConfirmed in order.events
    assert OrderCreated not in order.events

    # .all_events has everything
    assert order.all_events.types == [OrderCreated, OrderConfirmed]


# --8<-- [end:events_vs_all_events]


# --8<-- [start:aggregate_state]
def test_aggregate_state(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert order.status == "PAYMENT_PENDING"
    assert order.customer == "Alice"
    assert order.pricing.grand_total == 99.99  # deep access works
    assert isinstance(order.aggregate, Order)  # the raw aggregate


# --8<-- [end:aggregate_state]


# --8<-- [start:accepted_or_rejected]
def test_accepted_command(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    assert order.accepted  # command processed without exception
    assert not order.rejected  # command raised no exception
    assert order.rejection is None  # the exception object, or None


# --8<-- [end:accepted_or_rejected]


# --8<-- [start:event_log]
def test_event_log(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created, order_confirmed).process(initiate_payment)

    # Presence check
    assert PaymentPending in order.events

    # Truthiness: truthy when non-empty, falsy when empty
    assert order.events

    # Access by type (first match; raises KeyError if missing)
    assert order.events[PaymentPending].payment_id == "pay-001"

    # Safe access (returns None if missing)
    assert order.events.get(PaymentFailed) is None

    # First and last event
    assert order.events.first is order.events[0]
    assert order.events.last is order.events[-1]

    # Ordered type list
    assert order.events.types == [PaymentPending]

    # Count
    assert len(order.events) == 1

    # All events of a type
    assert len(order.events.of_type(PaymentPending)) == 1

    # Iteration
    for event in order.events:
        print(event)

    # Access by index
    assert order.events[0].payment_id == "pay-001"


# --8<-- [end:event_log]


# --8<-- [start:create_command]
def test_create_order():
    order = given(Order).process(
        CreateOrder(order_id="ord-1", customer="Alice", amount=99.99)
    )

    assert order.accepted
    assert OrderCreated in order.events
    assert order.status == "CREATED"
    assert order.customer == "Alice"


# --8<-- [end:create_command]


# --8<-- [start:command_with_history]
def test_confirm_order(order_created):
    order = given(Order, order_created).process(
        ConfirmOrder(order_id=order_created.order_id)
    )

    assert order.accepted
    assert OrderConfirmed in order.events
    assert order.status == "CONFIRMED"


# --8<-- [end:command_with_history]


# --8<-- [start:rejection]
def test_cannot_pay_unconfirmed_order(order_created, initiate_payment):
    order = given(Order, order_created).process(initiate_payment)

    assert order.rejected
    assert "Order must be confirmed before payment" in order.rejection_messages
    assert not order.events
    assert order.status == "CREATED"  # unchanged


# --8<-- [end:rejection]


# --8<-- [start:multiple_history]
def test_payment_on_confirmed_order(order_created, order_confirmed, initiate_payment):
    order = given(Order, order_created).after(order_confirmed).process(initiate_payment)

    assert order.accepted
    assert PaymentPending in order.events
    assert order.events[PaymentPending].payment_id == "pay-001"


# --8<-- [end:multiple_history]


# --8<-- [start:event_attributes]
def test_payment_event_carries_payment_id(order_created, order_confirmed):
    order = given(Order, order_created, order_confirmed).process(
        InitiatePayment(order_id=order_created.order_id, payment_id="pay-42")
    )

    event = order.events[PaymentPending]
    assert event.payment_id == "pay-42"
    assert event.order_id == order_created.order_id


# --8<-- [end:event_attributes]


# --8<-- [start:lifecycle]
def test_order_lifecycle():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(ConfirmOrder(order_id=oid))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.accepted
    assert order.status == "PAYMENT_PENDING"
    assert order.all_events.types == [OrderCreated, OrderConfirmed, PaymentPending]


# --8<-- [end:lifecycle]


# --8<-- [start:rejection_mid_chain]
def test_cannot_pay_without_confirming():
    oid = str(uuid4())
    order = (
        given(Order)
        .process(CreateOrder(order_id=oid, customer="Alice", amount=99.99))
        .process(InitiatePayment(order_id=oid, payment_id="pay-001"))
    )

    assert order.rejected
    assert "Order must be confirmed before payment" in order.rejection_messages
    assert order.status == "CREATED"  # reflects state after CreateOrder


# --8<-- [end:rejection_mid_chain]
