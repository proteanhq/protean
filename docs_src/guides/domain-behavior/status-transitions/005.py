from protean import Domain
from protean.fields import Status

domain = Domain()


# --8<-- [start:multiple]
from enum import Enum


class PaymentStatus(Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(Enum):
    UNFULFILLED = "UNFULFILLED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"


@domain.aggregate
class Order:
    payment = Status(
        PaymentStatus,
        default="PENDING",
        transitions={
            PaymentStatus.PENDING: [PaymentStatus.PAID],
            PaymentStatus.PAID: [PaymentStatus.REFUNDED],
        },
    )
    fulfillment = Status(
        FulfillmentStatus,
        default="UNFULFILLED",
        transitions={
            FulfillmentStatus.UNFULFILLED: [FulfillmentStatus.FULFILLED],
            FulfillmentStatus.FULFILLED: [FulfillmentStatus.RETURNED],
        },
    )


# --8<-- [end:multiple]
