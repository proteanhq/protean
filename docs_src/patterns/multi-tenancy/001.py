# ruff: noqa: F811
# The page shows middleware.py and domain.py as separate modules, so each imports g.


def decode_tenant_from_token(token: str) -> str | None:
    # Stand-in for real token verification: the token is "<tenant>:<user>".
    tenant, _, _ = token.removeprefix("Bearer ").partition(":")
    return tenant or None


def decode_user_from_token(token: str) -> str | None:
    _, _, user = token.removeprefix("Bearer ").partition(":")
    return user or None


# --8<-- [start:middleware]
# middleware.py

from protean.utils.globals import g


class TenantMiddleware:
    """Extract tenant_id from the auth token and store it in g."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            token = headers.get(b"authorization", b"").decode()

            g.tenant_id = decode_tenant_from_token(token)
            g.user_id = decode_user_from_token(token)

        await self.app(scope, receive, send)


# --8<-- [end:middleware]

# --8<-- [start:domain]
# domain.py

from protean import Domain
from protean.utils.globals import g

domain = Domain(name="SaasApp")


@domain.event_enricher
def enrich_event_with_tenant(event, aggregate):
    return {"tenant_id": getattr(g, "tenant_id", None)}


@domain.command_enricher
def enrich_command_with_tenant(command):
    return {"tenant_id": getattr(g, "tenant_id", None)}


# --8<-- [end:domain]

# --8<-- [start:app]
# main.py

from fastapi import FastAPI

from protean import current_domain
from protean.integrations.fastapi import DomainContextMiddleware

app = FastAPI()

# The middleware added last runs first, so DomainContextMiddleware pushes
# the domain context before TenantMiddleware writes to g.
app.add_middleware(TenantMiddleware)
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})


@app.post("/orders")
async def place_order(customer_id: str, product_id: str, quantity: int = 1):
    order = Order(
        tenant_id=g.tenant_id,
        customer_id=customer_id,
        product_id=product_id,
        quantity=quantity,
    )
    order.place()
    current_domain.repository_for(Order).add(order)
    return {"order_id": order.order_id, "tenant_id": order.tenant_id}


# --8<-- [end:app]

# --8<-- [start:aggregate]
from protean.fields import Auto, Float, Identifier, Integer, String


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    product_id = Identifier()
    quantity = Integer(default=1)
    total = Float()


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    tenant_id = String(required=True)
    customer_id = Identifier(required=True)
    product_id = Identifier()
    quantity = Integer(default=1)
    status = String(default="draft")
    total = Float(default=0.0)

    def place(self):
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                product_id=self.product_id,
                quantity=self.quantity,
                total=self.total,
            )
        )


# --8<-- [end:aggregate]

# --8<-- [start:queries]
# In a command handler or application service

from protean.utils.query import Q


def get_order(order_id):
    repo = current_domain.repository_for(Order)

    # Always filter by tenant
    return repo.find_by(order_id=order_id, tenant_id=g.tenant_id)


def placed_orders():
    repo = current_domain.repository_for(Order)

    # For listing
    return repo.find(Q(tenant_id=g.tenant_id, status="placed"))


# --8<-- [end:queries]


# --8<-- [start:tenant_query]
def tenant_query(aggregate_cls):
    """Return a query pre-filtered to the current tenant."""
    repo = current_domain.repository_for(aggregate_cls)
    return repo.query.filter(tenant_id=g.tenant_id)


# --8<-- [end:tenant_query]

# --8<-- [start:handler]
from protean import handle


@domain.aggregate
class Inventory:
    tenant_id = String(required=True)
    product_id = Identifier(required=True)
    available = Integer(default=0)
    reserved = Integer(default=0)

    def reserve(self, order_id, quantity):
        self.available -= quantity
        self.reserved += quantity


@domain.event_handler(part_of=Inventory, stream_category="saasapp::order")
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        # g.tenant_id is restored from metadata.extensions
        tenant_id = g.tenant_id

        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(
            product_id=event.product_id,
            tenant_id=tenant_id,
        )
        inventory.reserve(event.order_id, event.quantity)
        repo.add(inventory)


# --8<-- [end:handler]


# --8<-- [start:tests]
class TestOrderPlacement:
    def test_business_logic_without_tenant(self, test_domain):
        """Business logic works without tenant context."""
        order = Order(
            tenant_id="test-tenant",
            customer_id="cust-1",
            total=99.99,
        )
        order.place()
        assert order.status == "placed"

    def test_enrichment_with_tenant_context(self, test_domain):
        """Enrichers populate extensions when g.tenant_id is set."""
        g.tenant_id = "acme-corp"

        order = Order(
            tenant_id="acme-corp",
            customer_id="cust-1",
            total=99.99,
        )
        order.place()

        event = order._events[0]
        assert event._metadata.extensions["tenant_id"] == "acme-corp"
        # Business payload is clean
        assert not hasattr(event, "tenant_id")


# --8<-- [end:tests]

# --8<-- [start:handler_test]
import pytest

from protean.server import Engine
from protean.utils.eventing import Message


@pytest.mark.asyncio
async def test_handler_sees_tenant_from_extensions(test_domain):
    """Event handler receives tenant context from metadata.extensions."""
    repo = test_domain.repository_for(Inventory)
    repo.add(Inventory(tenant_id="acme-corp", product_id="sku-1", available=10))

    # Raise the event under a tenant, so the enricher records it
    with test_domain.domain_context(tenant_id="acme-corp"):
        order = Order(
            tenant_id="acme-corp",
            customer_id="cust-1",
            product_id="sku-1",
            quantity=2,
        )
        order.place()
    message = Message.from_domain_object(order._events[0])

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(InventoryEventHandler, message)

    # The handler found the stock through g.tenant_id
    inventory = repo.find_by(product_id="sku-1", tenant_id="acme-corp")
    assert inventory.reserved == 2


# --8<-- [end:handler_test]

domain.init(traverse=False)


@pytest.fixture
def test_domain():
    with domain.domain_context():
        yield domain
