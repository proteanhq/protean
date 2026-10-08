# --8<-- [start:domains]
# my_app/identity/__init__.py
from protean import Domain

identity_domain = Domain(name="Identity")

# my_app/catalogue/__init__.py
catalogue_domain = Domain(name="Catalogue")

# my_app/fulfillment/__init__.py
fulfillment_domain = Domain(name="Fulfillment")
# --8<-- [end:domains]


# --8<-- [start:fastapi-app]
# my_app/api/app.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from protean import current_domain
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

# Also import identity_domain, catalogue_domain and fulfillment_domain
# from my_app.identity, my_app.catalogue and my_app.fulfillment.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all domains at startup
    for d in [identity_domain, catalogue_domain, fulfillment_domain]:
        d.init()
        with d.domain_context():
            d.setup_database()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
        "/shipments": fulfillment_domain,
    },
)
register_exception_handlers(app)


@app.post("/customers", status_code=201)
async def register_customer(payload: dict) -> dict:
    return {"domain": current_domain.name}


@app.get("/products")
async def list_products() -> dict:
    return {"domain": current_domain.name}


# --8<-- [end:fastapi-app]


# --8<-- [start:external-events]
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier, String


# Define the external event class in your domain.
# This is YOUR domain's representation of the external event.
# It does not import from the other domain's package.
class PaymentReceived(BaseEvent):
    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    amount = Float()


class StockReserved(BaseEvent):
    order_id = Identifier(required=True)
    inventory_item_id = Identifier(required=True)
    quantity = Float()


class StockUnavailable(BaseEvent):
    order_id = Identifier(required=True)
    inventory_item_id = Identifier(required=True)


# Register external events with their type strings
fulfillment_domain.register_external_event(
    PaymentReceived, "Billing.PaymentReceived.v1"
)
fulfillment_domain.register_external_event(StockReserved, "Inventory.StockReserved.v1")
fulfillment_domain.register_external_event(
    StockUnavailable, "Inventory.StockUnavailable.v1"
)
# --8<-- [end:external-events]


# --8<-- [start:process-manager]
from protean import handle


# The fulfillment domain's own order and event
@fulfillment_domain.aggregate
class Order:
    status = String(default="new")


@fulfillment_domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)


@fulfillment_domain.process_manager(
    stream_categories=[
        "fulfillment::order",  # Own domain
        "billing::payment",  # External domain stream
        "inventory::inventory_item",  # External domain stream
    ]
)
class OrderFulfillmentPM:
    order_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentReceived, correlate="order_id")
    def on_payment_received(self, event: PaymentReceived) -> None:
        if self.status != "awaiting_payment":
            return
        self.status = "awaiting_stock"

    @handle(StockReserved, correlate="order_id")
    def on_stock_reserved(self, event: StockReserved) -> None:
        if self.status != "awaiting_stock":
            return
        self.status = "completed"
        self.mark_as_complete()

    @handle(StockUnavailable, correlate="order_id", end=True)
    def on_stock_unavailable(self, event: StockUnavailable) -> None:
        self.status = "stock_unavailable"


# --8<-- [end:process-manager]


# --8<-- [start:event-handler]
# Also import current_domain from protean.


# Fulfillment's own copy of the identity event, and its shipment aggregate
class CustomerRegistered(BaseEvent):
    customer_id = Identifier(required=True)
    name = String(required=True)


fulfillment_domain.register_external_event(
    CustomerRegistered, "Identity.CustomerRegistered.v1"
)


@fulfillment_domain.aggregate
class Shipment:
    recipient_id = Identifier(required=True)


@fulfillment_domain.event_handler(
    part_of=Shipment,
    stream_category="identity::customer",
)
class CustomerSyncHandler:
    @handle(CustomerRegistered)
    def on_registered(self, event: CustomerRegistered):
        recipient = Recipient(
            customer_id=event.customer_id,
            name=event.name,
        )
        current_domain.repository_for(Recipient).add(recipient)


# --8<-- [end:event-handler]


# --8<-- [start:subscriber]
from protean.fields import Text


@fulfillment_domain.command(part_of="Recipient")
class CreateRecipient:
    customer_id = Identifier(required=True)
    name = String(required=True)
    address = Text()


@fulfillment_domain.subscriber(stream="identity_customer_events")
class CustomerEventSubscriber:
    """Anti-corruption layer: translates external customer events."""

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "CustomerRegistered":
            current_domain.process(
                CreateRecipient(
                    customer_id=payload["customer_id"],
                    name=payload["full_name"],  # Field name translation
                    address=payload.get("shipping_address"),
                )
            )


# --8<-- [end:subscriber]


# --8<-- [start:correlation]
from protean.core.aggregate import BaseAggregate
from protean.fields import Auto


# Identity context: the authority for customer data
@identity_domain.aggregate
class Customer(BaseAggregate):
    customer_id = Auto(identifier=True)
    name = String(required=True)
    email = String(required=True)


# Fulfillment context: local representation with only relevant fields
@fulfillment_domain.aggregate
class Recipient(BaseAggregate):
    recipient_id = Auto(identifier=True)
    customer_id = Identifier(required=True)  # Correlation ID
    name = String(required=True)
    delivery_address = Text()


# --8<-- [end:correlation]


# --8<-- [start:fixtures]
import pytest

from protean.integrations.pytest import DomainFixture

# Also import identity_domain and fulfillment_domain
# from my_app.identity and my_app.fulfillment.


@pytest.fixture(scope="session")
def identity_fixture():
    identity_domain.config["command_processing"] = "sync"
    identity_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(identity_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(scope="session")
def fulfillment_fixture():
    fulfillment_domain.config["command_processing"] = "sync"
    fulfillment_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(fulfillment_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


# --8<-- [end:fixtures]


# --8<-- [start:cross-domain-test]
def test_customer_registration_creates_recipient(fulfillment_fixture):
    with fulfillment_fixture.domain_context():
        # The event the identity domain publishes, as fulfillment defines it
        event = CustomerRegistered(customer_id="cust-1", name="Alice")
        CustomerSyncHandler().on_registered(event)

        repo = fulfillment_domain.repository_for(Recipient)
        recipients = repo.query.filter(name="Alice").all()
        assert recipients.total == 1
        assert recipients.first.customer_id == "cust-1"


# --8<-- [end:cross-domain-test]


# --8<-- [start:api-tests]
from fastapi.testclient import TestClient

# Also import app from my_app.api.app.


@pytest.fixture
def client():
    return TestClient(app)


def test_customer_endpoint_uses_identity_domain(client):
    response = client.post("/customers", json={"name": "Alice"})
    assert response.status_code == 201
    assert response.json() == {"domain": "Identity"}


def test_product_endpoint_uses_catalogue_domain(client):
    response = client.get("/products")
    assert response.status_code == 200
    assert response.json() == {"domain": "Catalogue"}


# --8<-- [end:api-tests]
