from protean import Domain
from protean.fields import Auto, Identifier, String

domain = Domain(name="ThinEvents")


@domain.aggregate(fact_events=True)
class Order:
    order_id: Auto(identifier=True)
    status: String(default="draft")


# --8<-- [start:internal_trigger]
# Internal trigger -- no external consumers
@domain.event(part_of=Order)
class OrderProjectionStale:
    order_id: Identifier(required=True)


# --8<-- [end:internal_trigger]


# --8<-- [start:thin_delta]
# Thin delta event for specific consumers
@domain.event(part_of=Order)
class OrderCancelled:
    order_id: Identifier(required=True)
    reason: String(required=True)
    # Consumers that need full order state use the OrderFactEvent instead


# --8<-- [end:thin_delta]
