from protean import Domain

identity_domain = Domain(name="Identity")


# --8<-- [start:fact-events]
from protean.core.aggregate import BaseAggregate
from protean.fields import String


@identity_domain.aggregate(fact_events=True)
class Customer(BaseAggregate):
    name = String(required=True)
    email = String(required=True)
    segment = String()


# --8<-- [end:fact-events]
