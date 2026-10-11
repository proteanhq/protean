from protean import Domain, invariant
from protean.fields import HasMany, Integer, String

domain = Domain()


@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")


# --8<-- [start:invariant]
from protean.exceptions import ValidationError


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()

    @invariant.post
    def quantity_must_be_positive(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": ["Quantity must be positive"]})


# --8<-- [end:invariant]
