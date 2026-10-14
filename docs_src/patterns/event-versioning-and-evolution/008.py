from protean import Domain
from protean.fields import Auto, Float, Identifier, List, String

domain = Domain(name="UpcastOrders")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:import]
from protean.core.upcaster import BaseUpcaster

# --8<-- [end:import]


# --8<-- [start:upcasters]
# Current event definition (v3)
@domain.event(part_of=Order)
class OrderPlaced:
    __version__ = 3
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    line_items = List(required=True)
    subtotal = Float(required=True)
    tax = Float(required=True)
    total = Float(required=True)
    currency = String(required=True)


# v1 → v2: added currency field
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


# v2 → v3: renamed 'items' to 'line_items', split total into subtotal + tax
@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastOrderPlacedV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["line_items"] = data.pop("items", [])
        data["subtotal"] = data["total"]
        data["tax"] = 0.0
        return data


# --8<-- [end:upcasters]
