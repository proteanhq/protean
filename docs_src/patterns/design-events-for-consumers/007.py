from protean import Domain, handle
from protean.fields import (
    Auto,
    DateTime,
    Float,
    Identifier,
    Integer,
    List,
    String,
)
from protean.utils.globals import current_domain

domain = Domain(name="ProjectionDrivenEvents")
domain.config["event_processing"] = "sync"


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_name: String(required=True)
    status: String(default="draft")


# --8<-- [start:projection]
@domain.projection
class OrderSummaryProjection:
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()
    item_count: Integer()
    total: Float()
    placed_at: DateTime()
    shipped_at: DateTime()


# --8<-- [end:projection]


# --8<-- [start:events]
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(required=True)
    items: List(required=True)
    total: Float(required=True)
    placed_at: DateTime(required=True)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)


# --8<-- [end:events]


# --8<-- [start:projector]
@domain.projector(projector_for=OrderSummaryProjection, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # No aggregate loading needed -- event has everything
        projection = OrderSummaryProjection(
            order_id=event.order_id,
            customer_name=event.customer_name,
            status="placed",
            item_count=len(event.items),
            total=event.total,
            placed_at=event.placed_at,
        )
        current_domain.repository_for(OrderSummaryProjection).add(projection)

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderSummaryProjection)
        projection = repo.get(event.order_id)
        projection.status = "shipped"
        projection.shipped_at = event.shipped_at
        repo.add(projection)


# --8<-- [end:projector]
