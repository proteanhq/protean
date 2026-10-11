from protean import Domain
from protean.fields import Identifier

domain = Domain(name="Ordering")


# --8<-- [start:reserved]
@domain.aggregate(event_sourced=True, reserved=["note"])
class Order:
    order_id = Identifier(identifier=True)
    # `note` removed; its name is reserved so it is never reused


# --8<-- [end:reserved]
