# --8<-- [start:atomic_change]
from protean import Domain, atomic_change, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, HasMany, Identifier, Integer

domain = Domain(name="EncapsulateStateChangesRestructure")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1)
    unit_price: Float()

    @property
    def line_total(self) -> float:
        return self.quantity * self.unit_price


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    items = HasMany(OrderItem)
    total: Float(default=0.0)

    def restructure_order(self, new_items: list, new_total: float) -> None:
        """Replace all items and recalculate total atomically."""
        with atomic_change(self):
            self.items = []
            for item_data in new_items:
                self.add_items(OrderItem(**item_data))
            self.total = new_total
        # Invariants checked here, after all changes are applied

    @invariant.post
    def total_must_match_items(self):
        if self.total != sum(item.line_total for item in self.items):
            raise ValidationError({"total": ["Total must match the order items"]})


# --8<-- [end:atomic_change]
