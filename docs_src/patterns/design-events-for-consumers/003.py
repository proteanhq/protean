from datetime import UTC, datetime

from protean import Domain
from protean.fields import (
    Auto,
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
)

domain = Domain(name="DeltaAndFactEvents")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_email: String(required=True)
    items: List(required=True)
    total: Float(required=True)
    placed_at: DateTime(required=True)


# --8<-- [start:combined]
@domain.aggregate(fact_events=True)
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    customer_email: String(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)
    placed_at: DateTime()

    def place(self):
        self.status = "placed"
        self.placed_at = datetime.now(UTC)
        # Delta event with specific operation semantics
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                customer_email=self.customer_email,
                items=[item.to_dict() for item in self.items],
                total=self.total,
                placed_at=self.placed_at,
            )
        )
        # Fact event is also auto-raised on persistence


# --8<-- [end:combined]
