from protean import Domain

domain = Domain(name="Ordering")


# --8<-- [start:status]
from enum import Enum

from protean.fields import Status


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


@domain.aggregate
class Order:
    status = Status(OrderStatus, default="DRAFT")


# --8<-- [end:status]
