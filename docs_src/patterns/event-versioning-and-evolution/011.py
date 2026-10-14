from protean import Domain
from protean.fields import Auto, Float, Identifier, String

domain = Domain(name="CorrectingEvents")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:correcting_event]
# NEVER do this:
# event_store.update(event_id, corrected_data)


# Instead, raise a correcting event:
@domain.event(part_of=Order)
class OrderTotalCorrected:
    order_id: Identifier(required=True)
    old_total: Float(required=True)
    new_total: Float(required=True)
    correction_reason: String(required=True)


# --8<-- [end:correcting_event]
