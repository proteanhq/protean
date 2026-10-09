# --8<-- [start:domain-imports]
from protean import Domain, Q, handle
from protean.fields import Identifier, Integer, List, String, ValueObject
from protean.utils.globals import current_domain

# --8<-- [end:domain-imports]
# isort: split

# --8<-- [start:api-imports]
from fastapi import FastAPI
from pydantic import BaseModel

from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

# --8<-- [end:api-imports]
# isort: split

# --8<-- [start:pytest-import]
import pytest

# --8<-- [end:pytest-import]
# isort: split

# --8<-- [start:fixture-import]
from protean.integrations.pytest import DomainFixture

# --8<-- [end:fixture-import]
# isort: split

# --8<-- [start:client-import]
from fastapi.testclient import TestClient

# --8<-- [end:client-import]

# --8<-- [start:domain]
domain = Domain(name="Bookstore")


@domain.aggregate
class Customer:
    name = String(required=True, max_length=100)
    email = String(max_length=254)


@domain.value_object
class OrderItemVO:
    book_id = String(required=True)
    quantity = Integer(required=True, min_value=1)


@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO))
    status = String(default="PENDING")


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO))


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO))


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> str:
        # Raises ObjectNotFoundError when the customer does not exist
        current_domain.repository_for(Customer).get(command.customer_id)

        order = Order(customer_id=command.customer_id, items=command.items)
        order.raise_(OrderPlaced(order_id=order.id, items=command.items))
        current_domain.repository_for(Order).add(order)
        return order.id


@domain.aggregate
class Inventory:
    book_id = String(required=True)
    quantity = Integer(default=0)


@domain.event_handler(part_of=Inventory, stream_category="bookstore::order")
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            for inventory in repo.find(Q(book_id=item.book_id)).items:
                inventory.quantity -= item.quantity
                repo.add(inventory)


# --8<-- [end:domain]


# --8<-- [start:api]
app = FastAPI()
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
register_exception_handlers(app)


class PlaceOrderRequest(BaseModel):
    customer_id: str
    items: list[dict]


@app.post("/orders", status_code=201)
def place_order(payload: PlaceOrderRequest):
    order_id = current_domain.process(
        PlaceOrder(
            customer_id=payload.customer_id,
            items=[OrderItemVO(**item) for item in payload.items],
        )
    )
    return {"order_id": order_id}


# --8<-- [end:api]


# --8<-- [start:query-endpoint]
@app.get("/customers/{customer_id}")
def get_customer(customer_id: str):
    customer = current_domain.repository_for(Customer).get(customer_id)
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
    }


# --8<-- [end:query-endpoint]


# --8<-- [start:conftest]
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


# --8<-- [start:client]
@pytest.fixture
def client():
    return TestClient(app)


# --8<-- [end:client]


# --8<-- [start:alice]
@pytest.fixture
def alice():
    """A pre-existing customer for order tests."""
    customer = Customer(name="Alice", email="alice@example.com")
    domain.repository_for(Customer).add(customer)
    return customer


# --8<-- [end:alice]


# --8<-- [start:happy-path]
def test_place_order_returns_201(client):
    # Seed the customer that the order references
    customer = Customer(name="Alice")
    domain.repository_for(Customer).add(customer)

    response = client.post(
        "/orders",
        json={
            "customer_id": customer.id,
            "items": [{"book_id": "book-1", "quantity": 2}],
        },
    )

    assert response.status_code == 201
    assert "order_id" in response.json()


# --8<-- [end:happy-path]


# --8<-- [start:side-effects]
def test_place_order_creates_order(client):
    customer = Customer(name="Bob")
    domain.repository_for(Customer).add(customer)

    response = client.post(
        "/orders",
        json={
            "customer_id": customer.id,
            "items": [{"book_id": "book-1", "quantity": 3}],
        },
    )

    order_id = response.json()["order_id"]
    order = domain.repository_for(Order).get(order_id)
    assert order.customer_id == customer.id
    assert order.status == "PENDING"


# --8<-- [end:side-effects]


# --8<-- [start:errors]
def test_place_order_for_nonexistent_customer_returns_404(client):
    response = client.post(
        "/orders",
        json={
            "customer_id": "nonexistent",
            "items": [{"book_id": "book-1", "quantity": 1}],
        },
    )

    assert response.status_code == 404
    assert "error" in response.json()


def test_place_order_with_invalid_data_returns_400(client):
    response = client.post(
        "/orders",
        json={
            "customer_id": "",
            "items": [],
        },
    )

    assert response.status_code == 400


# --8<-- [end:errors]


# --8<-- [start:query-tests]
def test_get_customer_returns_200(client):
    customer = Customer(name="Alice", email="alice@example.com")
    domain.repository_for(Customer).add(customer)

    response = client.get(f"/customers/{customer.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Alice"
    assert data["email"] == "alice@example.com"


def test_get_nonexistent_customer_returns_404(client):
    response = client.get("/customers/does-not-exist")

    assert response.status_code == 404


# --8<-- [end:query-tests]


# --8<-- [start:event-side-effects]
def test_placing_order_updates_inventory(client):
    customer = Customer(name="Alice")
    domain.repository_for(Customer).add(customer)

    inventory = Inventory(book_id="book-1", quantity=10)
    domain.repository_for(Inventory).add(inventory)

    client.post(
        "/orders",
        json={
            "customer_id": customer.id,
            "items": [{"book_id": "book-1", "quantity": 3}],
        },
    )

    # The OrderPlaced event handler has already run (sync processing)
    updated = domain.repository_for(Inventory).get(inventory.id)
    assert updated.quantity == 7


# --8<-- [end:event-side-effects]


# --8<-- [start:seed-fixture-test]
def test_place_order(client, alice):
    response = client.post(
        "/orders",
        json={
            "customer_id": alice.id,
            "items": [{"book_id": "book-1", "quantity": 1}],
        },
    )
    assert response.status_code == 201


# --8<-- [end:seed-fixture-test]


# --8<-- [start:auth-client]
@pytest.fixture
def auth_client(client):
    """Client with a valid auth token."""
    client.headers["Authorization"] = "Bearer test-token-for-alice"
    return client


# --8<-- [end:auth-client]


# --8<-- [start:assert-helper]
def assert_error_response(response, status_code, message_fragment=None):
    """Assert that the response is an error with the expected status."""
    assert response.status_code == status_code
    data = response.json()
    assert "error" in data
    if message_fragment:
        error_text = str(data["error"])
        assert message_fragment in error_text


# --8<-- [end:assert-helper]
