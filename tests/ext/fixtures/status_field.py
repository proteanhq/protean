"""Fixture: Status field factory resolves to str."""

from enum import Enum

from protean.fields import Status


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"


s = Status(OrderStatus, required=True)
reveal_type(s)  # E: Revealed type is "builtins.str"

s2 = Status(OrderStatus, default="DRAFT")
reveal_type(s2)  # E: Revealed type is "builtins.str"

s3 = Status(
    OrderStatus,
    transitions={OrderStatus.DRAFT: [OrderStatus.PLACED]},
)
reveal_type(s3)  # E: Revealed type is "builtins.str"
