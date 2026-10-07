from enum import Enum

from protean import Domain
from protean.fields import Status

domain = Domain(name="Ordering")


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# --8<-- [start:transitions]
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
            # DELIVERED and CANCELLED are terminal: absent from keys
        },
    )


# --8<-- [end:transitions]


# --8<-- [start:can_transition_to]
with domain.domain_context():
    order = Order()
    order.status = "PLACED"

order.can_transition_to("status", OrderStatus.SHIPPED)  # False
order.can_transition_to("status", OrderStatus.CONFIRMED)  # True
# --8<-- [end:can_transition_to]
