import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Integer, String


class Store(BaseAggregate):
    name = String(max_length=50)


class Item(BaseEntity):
    name = String(max_length=10, required=True)
    price = Float(required=True)
    quantity = Integer(default=0)

    @invariant.post
    def check_price_is_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Store)
    test_domain.register(Item, part_of=Store)
    test_domain.init(traverse=False)


class TestEntityInitializedFlag:
    """Test that entity's _initialized flag is set correctly."""

    def test_initialized_is_true_after_successful_initialization(self):
        """_initialized should be True after successful entity creation."""
        item = Item(name="Widget", price=10.0, quantity=5)

        assert item._initialized is True

    def test_initialized_is_true_with_default_values(self):
        """_initialized should be True even when using default values."""
        item = Item(name="Widget", price=10.0)

        assert item._initialized is True
        assert item.quantity == 0  # default value
