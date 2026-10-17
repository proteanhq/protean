# --8<-- [start:sales-customer]
# Sales context: the authority for Customer
from enum import Enum

from protean import Domain
from protean.fields import Auto, Identifier, String

sales = Domain(__file__, "Sales")


class CustomerSegment(Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


@sales.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True, max_length=100)
    email: String(required=True)
    segment: String(choices=CustomerSegment, default="STANDARD")


# --8<-- [end:sales-customer]


# --8<-- [start:sales-events]
@sales.event(part_of=Customer)
class CustomerRegistered:
    customer_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)


@sales.event(part_of=Customer)
class CustomerEmailUpdated:
    customer_id: Identifier(required=True)
    new_email: String(required=True)


@sales.event(part_of=Customer)
class CustomerAddressUpdated:
    customer_id: Identifier(required=True)
    street: String(required=True)
    city: String(required=True)
    zip_code: String(required=True)


@sales.event(part_of=Customer)
class CustomerDeactivated:
    customer_id: Identifier(required=True)
    reason: String()


# --8<-- [end:sales-events]
