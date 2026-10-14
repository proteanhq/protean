from protean import Domain, handle
from protean.fields import Float, Identifier
from protean.utils.globals import g

domain = Domain(name="Shop")


# --8<-- [start:create]
from protean.server import Engine


def create_engine(domain):
    # Create an engine for your domain
    return Engine(domain)


def create_test_engine(domain):
    # Or with options
    return Engine(
        domain,
        test_mode=True,  # Exit once queued messages are processed
        debug=False,  # Set True for verbose logging
    )


# --8<-- [end:create]


# --8<-- [start:order]
@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    total: Float(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


placed_orders = []


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def record(self, event: OrderPlaced) -> None:
        placed_orders.append(event.order_id)


# --8<-- [end:order]


# --8<-- [start:register]
def register_order_handler(engine):
    # Example: How the engine registers an event handler
    handler_cls = OrderEventHandler
    stream_category = engine._infer_stream_category(handler_cls)  # "shop::order"

    subscription = engine.subscription_factory.create_subscription(
        handler=handler_cls,
        stream_category=stream_category,
    )
    return stream_category, subscription


# --8<-- [end:register]


# --8<-- [start:context]
@domain.event_enricher
def add_tenant(event, aggregate):
    return {"tenant_id": g.get("tenant_id")}


seen_tenants = []


@domain.event_handler(part_of=Order)
class TenantAuditHandler:
    @handle(OrderPlaced)
    def audit(self, event: OrderPlaced) -> None:
        # Access the full extensions dict
        tenant_id = g.message_in_context.metadata.extensions.get("tenant_id")

        # Or use the restored g attribute directly (simpler)
        seen_tenants.append((tenant_id, g.tenant_id))


# --8<-- [end:context]
