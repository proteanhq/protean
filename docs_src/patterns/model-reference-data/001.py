# --8<-- [start:choices]
from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="ReferenceDataChoices")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    status: String(choices=["draft", "placed", "shipped", "delivered"], default="draft")


# --8<-- [end:choices]

domain.init(traverse=False)
