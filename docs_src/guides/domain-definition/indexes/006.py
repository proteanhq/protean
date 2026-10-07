from protean import Domain, Index
from protean.fields import Identifier, String

domain = Domain(name="Reporting")


# --8<-- [start:projection]
@domain.projection(indexes=[Index("status"), Index("customer_id")])
class OrderSummary:
    id = Identifier(identifier=True)
    status = String(max_length=32)
    customer_id = String(max_length=64)


# --8<-- [end:projection]
