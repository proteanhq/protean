from enum import Enum

from protean import Domain
from protean.fields import Float, Status

domain = Domain()


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
        },
    )
    amount = Float()


# --8<-- [end:transitions]


# --8<-- [start:direct]
def place_then_ship():
    order = Order()  # status = "DRAFT"
    order.status = "PLACED"  # OK: DRAFT → PLACED is allowed
    order.status = "SHIPPED"  # ValidationError: PLACED → SHIPPED is not allowed


# --8<-- [end:direct]


# --8<-- [start:reentry]
def reenter_draft():
    order = Order()  # status = "DRAFT"
    order.status = "DRAFT"  # ValidationError: DRAFT is not in DRAFT's target list


# --8<-- [end:reentry]


# --8<-- [start:initialization]
def create_orders():
    draft = Order()  # status = "DRAFT" (via default): OK
    placed = Order(status="PLACED")  # Also OK: initial assignment
    return draft, placed


# --8<-- [end:initialization]


# --8<-- [start:atomic_valid]
from protean import atomic_change


def place_with_amount():
    order = Order()  # status = "DRAFT"

    with atomic_change(order):
        order.status = "PLACED"
        order.amount = 100.0
    # On exit: validates DRAFT → PLACED: OK

    return order


# --8<-- [end:atomic_valid]


# --8<-- [start:atomic_invalid]
def place_and_confirm(order):
    with atomic_change(order):
        order.status = "PLACED"  # DRAFT → PLACED (valid step)
        order.status = "CONFIRMED"  # PLACED → CONFIRMED (valid step)
    # On exit: validates DRAFT → CONFIRMED: not in DRAFT's allowed list → ValidationError


# --8<-- [end:atomic_invalid]


# --8<-- [start:can_transition]
def show_moves(order):
    print(order.can_transition_to("status", OrderStatus.SHIPPED))  # False
    print(order.can_transition_to("status", OrderStatus.PLACED))  # True


# --8<-- [end:can_transition]
