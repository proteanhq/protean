from enum import Enum

from protean import Domain, apply
from protean.fields import Identifier, Status

domain = Domain()


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"


# --8<-- [start:es_order]
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    status = Status(
        OrderStatus,
        default="DRAFT",
        transitions={
            OrderStatus.DRAFT: [OrderStatus.PLACED],
            OrderStatus.PLACED: [OrderStatus.CONFIRMED],
        },
    )

    def place(self):
        self.raise_(OrderPlaced(order_id=self.id))

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        self.status = "PLACED"  # Validated on atomic_change exit


# --8<-- [end:es_order]
