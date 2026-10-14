from protean import Domain
from protean.fields import Float, String

domain = Domain(name="ecommerce")


# --8<-- [start:event_sourced]
@domain.aggregate(event_sourced=True)
class Account:
    account_number: String(required=True)
    balance: Float(default=0.0)


# --8<-- [end:event_sourced]


# --8<-- [start:fact_events]
@domain.aggregate(fact_events=True)
class User: ...


# Regular events: ecommerce::user-123
# Fact events: ecommerce::user-fact-123
# --8<-- [end:fact_events]
