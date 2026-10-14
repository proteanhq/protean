from protean import Domain
from protean.fields import Auto, Float, Identifier, List, String

# --8<-- [start:domain]
# A later release, where the aggregate raises OrderPlacedV2
domain = Domain(name="DeprecatedEvent")
# --8<-- [end:domain]


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier()

    def place(self, items, total):
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                items=items,
                total=total,
            )
        )


@domain.event(part_of=Order)
class OrderPlacedV2:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    line_items: List(required=True)
    subtotal: Float(required=True)
    tax: Float(required=True)
    total: Float(required=True)
    currency: String(required=True)


# --8<-- [start:deprecated]
@domain.event(
    part_of=Order,
    deprecated={"since": "0.16", "removal": "0.19"},
    superseded_by=OrderPlacedV2,  # an Event class or its name as a string
)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)


# --8<-- [end:deprecated]
