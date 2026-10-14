from protean.exceptions import ValidationError
from protean.fields import Auto, Float, HasMany, Identifier, Integer, List, String

# isort: split

# --8<-- [start:domain]
# domain.py -- Domain initialization with enrichers

from protean import Domain
from protean.utils.globals import g

domain = Domain(name="SaasApp")


# --- Event enrichers ---


@domain.event_enricher
def enrich_event_with_tenant(event, aggregate):
    """Inject tenant context into every domain event."""
    return {
        "tenant_id": getattr(g, "tenant_id", None),
    }


@domain.event_enricher
def enrich_event_with_audit(event, aggregate):
    """Inject user and request context for audit trails."""
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }


# --- Command enrichers ---


@domain.command_enricher
def enrich_command_with_tenant(command):
    """Inject tenant context into every command."""
    return {
        "tenant_id": getattr(g, "tenant_id", None),
    }


@domain.command_enricher
def enrich_command_with_audit(command):
    """Inject user and request context into every command."""
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }


# --8<-- [end:domain]


# --8<-- [start:model]
@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    price: Float(required=True)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    status: String(default="draft")
    items: HasMany(OrderItem)
    total: Float(default=0.0)

    def add_item(self, product_id: str, quantity: int, price: float) -> None:
        self.add_items(OrderItem(product_id=product_id, quantity=quantity, price=price))

    def place(self) -> None:
        """Place the order and emit a domain event."""
        self._validate_can_place()
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                items=[item.to_dict() for item in self.items],
                total=self.total,
            )
        )

    def _validate_can_place(self) -> None:
        if not self.items:
            raise ValidationError({"items": ["An order needs at least one item"]})


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float()
    # No tenant_id, no user_id, no request_id.
    # Enrichers handle that.


# --8<-- [end:model]


# --8<-- [start:tests]
class TestOrderPlacement:
    def test_business_logic_without_enrichment(self, test_domain):
        """Enrichers run but produce None values -- harmless."""
        order = Order(
            customer_id="cust-1",
            total=99.99,
        )
        order.add_item(product_id="prod-1", quantity=2, price=49.99)
        order.place()

        assert order.status == "placed"
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderPlaced)

    def test_enrichment_with_tenant_context(self, test_domain):
        """Set up g to verify enrichers populate extensions."""
        g.tenant_id = "acme-corp"
        g.user_id = "user-42"
        g.request_id = "req-abc-123"

        order = Order(
            customer_id="cust-1",
            total=99.99,
        )
        order.add_item(product_id="prod-1", quantity=2, price=49.99)
        order.place()

        event = order._events[0]
        assert event._metadata.extensions["tenant_id"] == "acme-corp"
        assert event._metadata.extensions["user_id"] == "user-42"
        assert event._metadata.extensions["request_id"] == "req-abc-123"

        # Business payload is clean
        assert not hasattr(event, "tenant_id")
        assert not hasattr(event, "user_id")


# --8<-- [end:tests]
