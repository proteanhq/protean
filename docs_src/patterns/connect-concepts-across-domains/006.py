from protean import Domain
from protean.fields import Auto, Boolean, Identifier, String

domain = Domain(name="Shipping")


# --8<-- [start:shipment]
@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)  # Correlates to Order context
    customer_id: Identifier(required=True)  # Correlates to Sales context
    warehouse_id: Identifier(required=True)  # Correlates to Inventory context


# --8<-- [end:shipment]


# --8<-- [start:customer-reference]
@domain.projection
class CustomerReference:
    """Read-only reference to a customer, built from Sales events."""

    customer_id: Identifier(identifier=True)
    name: String()
    email: String()
    is_active: Boolean(default=True)


# --8<-- [end:customer-reference]
