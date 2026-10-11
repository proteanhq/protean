# --8<-- [start:imports]
import pytest

from protean.exceptions import ValidationError

# --8<-- [end:imports]
# isort: split

from protean import Domain, invariant
from protean.fields import HasMany, Identifier, String

domain = Domain(name="Ordering")


@domain.entity(part_of="Order")
class OrderItem:
    sku: String(max_length=20, required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)

    @invariant.post
    def has_at_least_one_item(self):
        if not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})


# --8<-- [start:assert_invalid]
def test_an_order_needs_an_item():
    with pytest.raises(ValidationError) as exc_info:
        Order(customer_id="c1", items=[])

    assert "at least one item" in exc_info.value.messages["items"][0]


# --8<-- [end:assert_invalid]


# --8<-- [start:match]
def test_an_order_needs_an_item_with_match():
    with pytest.raises(ValidationError, match="at least one item"):
        Order(customer_id="c1", items=[])


# --8<-- [end:match]


# --8<-- [start:assert_valid]
def test_an_order_with_an_item_is_valid():
    item = OrderItem(sku="SKU-1")
    order = Order(customer_id="c1", items=[item])

    assert order.items == [item]


# --8<-- [end:assert_valid]
