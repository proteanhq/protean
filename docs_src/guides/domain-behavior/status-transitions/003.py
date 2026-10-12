from enum import Enum

from protean import Domain
from protean.fields import Status

domain = Domain()


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# --8<-- [start:idempotent]
@domain.aggregate
class Order:
    status = Status(
        OrderStatus,
        default="DRAFT",
        transitions={
            OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
            OrderStatus.PLACED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
            OrderStatus.CONFIRMED: [OrderStatus.SHIPPED],
            OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
            # CANCELLED is idempotent: re-entry is explicitly allowed
            OrderStatus.CANCELLED: [OrderStatus.CANCELLED],
        },
    )


# --8<-- [end:idempotent]
