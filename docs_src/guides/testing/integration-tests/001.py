# --8<-- [start:domain]
from protean import Domain, handle
from protean.fields import HasMany, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain(name="Warehouse")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    order_id: Identifier(required=True)


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1, required=True)


@domain.aggregate
class Order:
    customer_id: String(max_length=50)
    status: String(max_length=20, default="placed")
    items = HasMany(OrderItem)

    @classmethod
    def create(cls, customer_id, items, **kwargs):
        order = cls(customer_id=customer_id, items=items, **kwargs)
        for item in items:
            order.raise_(
                OrderPlaced(
                    order_id=order.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                )
            )
        return order


@domain.event(part_of="Reservation")
class InventoryReserved:
    order_id: Identifier(required=True)


@domain.aggregate
class Reservation:
    order_id: Identifier(identifier=True)
    product_id: String(max_length=50, required=True)
    quantity: Integer(required=True)

    @classmethod
    def reserve(cls, order_id, product_id, quantity):
        reservation = cls(order_id=order_id, product_id=product_id, quantity=quantity)
        reservation.raise_(InventoryReserved(order_id=order_id))
        return reservation


@domain.repository(part_of=Reservation)
class ReservationRepository:
    def get_by_order(self, order_id):
        return self._dao.query.filter(order_id=order_id).all().first


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    product_id: String(required=True)
    qty: Integer(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order.create(
            customer_id="anonymous",
            items=[OrderItem(product_id=command.product_id, quantity=command.qty)],
            id=command.order_id,
        )
        current_domain.repository_for(Order).add(order)


@domain.event_handler(part_of=Order)
class InventoryHandler:
    """Reserves stock for every order placed."""

    @handle(OrderPlaced)
    def reserve(self, event: OrderPlaced):
        reservation = Reservation.reserve(
            event.order_id, event.product_id, event.quantity
        )
        current_domain.repository_for(Reservation).add(reservation)


@domain.event_handler(part_of=Reservation)
class ShippingHandler:
    """Ships an order once its stock is reserved."""

    @handle(InventoryReserved)
    def ship(self, event: InventoryReserved):
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.status = "shipped"
        repo.add(order)


# --8<-- [end:domain]


# --8<-- [start:conftest]
import pytest

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    # Handlers run asynchronously, in the server engine.
    domain.config["event_processing"] = "async"
    domain.config["command_processing"] = "async"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


def get_order(order_id):
    return domain.repository_for(Order).get(order_id)


# --8<-- [end:conftest]


# --8<-- [start:engine_test_mode]
from protean.server import Engine


def test_order_creates_inventory_reservation():
    """Test that creating an order reserves inventory."""
    # Arrange: Create order (raises events)
    with domain.domain_context():
        order = Order.create(
            customer_id="123", items=[OrderItem(product_id="ABC", quantity=5)]
        )
        domain.repository_for(Order).add(order)

    # Act: Process events in test mode
    engine = Engine(domain, test_mode=True)
    engine.run()

    # Assert: Verify inventory was reserved
    with domain.domain_context():
        reservation = domain.repository_for(Reservation).get_by_order(order.id)
        assert reservation is not None
        assert reservation.quantity == 5


# --8<-- [end:engine_test_mode]


# --8<-- [start:cascade]
def test_order_fulfillment_flow():
    """Test complete order fulfillment flow."""
    # Order created -> Inventory reserved -> Order shipped
    with domain.domain_context():
        order = Order.create(
            customer_id="123", items=[OrderItem(product_id="ABC", quantity=5)]
        )
        domain.repository_for(Order).add(order)

    # Process all cascading events
    engine = Engine(domain, test_mode=True)
    engine.run()

    with domain.domain_context():
        order = domain.repository_for(Order).get(order.id)
        assert order.status == "shipped"


# --8<-- [end:cascade]


# --8<-- [start:process_and_wait]
from protean.testing import process_and_wait


def test_placing_an_order_reserves_inventory():
    outcome = process_and_wait(
        PlaceOrder(order_id="o1", product_id="ABC", qty=5), domain
    )

    assert outcome.succeeded
    assert OrderPlaced in outcome.events
    assert outcome.events[OrderPlaced].order_id == "o1"

    with domain.domain_context():
        reservation = domain.repository_for(Reservation).get("o1")
        assert reservation.quantity == 5


# --8<-- [end:process_and_wait]


# --8<-- [start:event_log]
def test_the_event_log():
    outcome = process_and_wait(
        PlaceOrder(order_id="o1", product_id="ABC", qty=5), domain
    )

    assert OrderPlaced in outcome.events  # membership by type
    assert outcome.events[OrderPlaced].order_id == "o1"  # first event of a type
    assert outcome.events.get(OrderCancelled) is None  # safe access, no KeyError
    assert outcome.events.types == [OrderPlaced, InventoryReserved]
    assert len(outcome.events) == 2


# --8<-- [end:event_log]


# --8<-- [start:drain]
from protean.testing import drain


def test_order_ships_after_reservation():
    domain.process(PlaceOrder(order_id="o1", product_id="ABC", qty=5))

    drain(domain, until=lambda: get_order("o1").status == "shipped")

    assert get_order("o1").status == "shipped"


# --8<-- [end:drain]
