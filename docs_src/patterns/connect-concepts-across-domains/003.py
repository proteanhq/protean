from enum import Enum

from protean import Domain
from protean.fields import Auto, String

sales = Domain(__file__, "Sales")


class CustomerSegment(Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


# --8<-- [start:fact-events]
# Sales context: enable fact events
@sales.aggregate(fact_events=True)
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True, max_length=100)
    email: String(required=True)
    segment: String(choices=CustomerSegment, default="STANDARD")


# --8<-- [end:fact-events]
