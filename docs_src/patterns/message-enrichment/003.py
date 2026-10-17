from protean import Domain, handle
from protean.fields import Auto, DateTime, Dict, Identifier, List, String
from protean.utils.globals import current_domain, g

domain = Domain(name="SaasApp")


@domain.event_enricher
def enrich_event_with_tenant(event, aggregate):
    return {"tenant_id": getattr(g, "tenant_id", None)}


@domain.event_enricher
def enrich_event_with_audit(event, aggregate):
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    items: List(content_type=Dict)

    def place(self) -> None:
        self.raise_(OrderPlaced(order_id=self.order_id, items=self.items))


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    items: List(content_type=Dict, required=True)


# --8<-- [start:handler]
@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    reservations: List(content_type=Dict)

    def reserve(self, order_id: str, quantity: int, tenant_id: str) -> None:
        self.reservations = [
            *self.reservations,
            {"order_id": order_id, "quantity": quantity, "tenant_id": tenant_id},
        ]


@domain.event_handler(part_of=Inventory, stream_category="saasapp::order")
class InventoryEventHandler:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        # Access enriched metadata from the message in context
        tenant_id = g.message_in_context.metadata.extensions.get("tenant_id")

        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
                tenant_id=tenant_id,  # Pass to domain logic if needed
            )
            repo.add(inventory)


# --8<-- [end:handler]


# --8<-- [start:projector]
@domain.projection
class OrderAuditProjection:
    order_id: Identifier(identifier=True)
    action: String(required=True)
    performed_by: String()
    request_id: String()
    tenant_id: String()
    timestamp: DateTime()


@domain.projector(projector_for=OrderAuditProjection, aggregates=[Order])
class OrderAuditProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        extensions = g.message_in_context.metadata.extensions

        repo = current_domain.repository_for(OrderAuditProjection)
        repo.add(
            OrderAuditProjection(
                order_id=event.order_id,
                action="placed",
                performed_by=extensions.get("user_id", "unknown"),
                request_id=extensions.get("request_id"),
                tenant_id=extensions.get("tenant_id"),
                timestamp=g.message_in_context.metadata.headers.time,
            )
        )


# --8<-- [end:projector]
