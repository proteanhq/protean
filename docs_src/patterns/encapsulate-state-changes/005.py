# --8<-- [start:defaults_and_place]
from datetime import UTC, datetime

from protean import Domain
from protean.fields import Auto, DateTime, Float, HasMany, Identifier, Integer, String

domain = Domain(name="EncapsulateStateChangesPlacement")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1)
    unit_price: Float()

    @property
    def line_total(self) -> float:
        return self.quantity * self.unit_price


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float()
    placed_at: DateTime()


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float()
    placed_at: DateTime()

    def defaults(self):
        """Set conditional defaults at initialization."""
        if not self.total:
            self.total = sum(item.line_total for item in self.items)

    def place(self):
        """Business operation: place the order."""
        self.status = "placed"
        self.placed_at = datetime.now(UTC)
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                total=self.total,
                placed_at=self.placed_at,
            )
        )


# --8<-- [end:defaults_and_place]
