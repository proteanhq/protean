from protean import Domain
from protean.fields import Auto, Identifier

domain = Domain(name="SmallAggregatesIdentifierField")


# --8<-- [start:identifiers]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # References Customer aggregate
    product_id: Identifier(required=True)  # References Product aggregate


@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)  # References Order aggregate
    carrier_id: Identifier(required=True)  # References Carrier aggregate


# --8<-- [end:identifiers]
