import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Integer, String


class Inventory(BaseAggregate):
    name: String(max_length=50)


class Product(BaseEntity):
    name: String(max_length=10, required=True)
    price: Float(required=True)
    quantity: Integer(required=True)

    @invariant.post
    def check_price_is_positive(self):
        if self.price <= 0:
            raise ValidationError({"price": ["Price must be positive"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Inventory)
    test_domain.register(Product, part_of=Inventory)
    test_domain.init(traverse=False)


def test_entity_invariant_raises_error_on_initialization():
    with pytest.raises(ValidationError) as exc:
        Product(name="Widget", price=-10.0, quantity=5)

    assert "price" in exc.value.messages
    assert "must be positive" in exc.value.messages["price"][0]


class TestFieldValidationsBeforeInvariants:
    """Test that field-level validations are checked first,
    and invariants are only run when field validations pass."""

    def test_field_validation_errors_prevent_invariant_checks(self):
        """When field-level validations fail, invariants should not be run.

        Name exceeds max_length (10), and price is negative which would
        fail the invariant - but since field validation fails first,
        invariant should not run.
        """
        # Name too long (max_length=10) with data that would fail invariant
        with pytest.raises(ValidationError) as exc:
            Product(name="this_name_is_way_too_long", price=-10.0, quantity=5)

        # Only field validation error should be raised, not invariant error
        assert "name" in exc.value.messages
        assert "price" not in exc.value.messages

    def test_required_field_missing_prevents_invariant_checks(self):
        """When required fields are missing, invariants should not be run."""
        # Missing required price field
        with pytest.raises(ValidationError) as exc:
            Product(name="Widget", quantity=5)

        # Required field error should be raised (not invariant error)
        assert "price" in exc.value.messages
        assert "is required" in exc.value.messages["price"][0]
        assert "must be positive" not in str(exc.value.messages)

    def test_invalid_field_type_prevents_invariant_checks(self):
        """When field type validation fails, invariants should not be run."""
        # Invalid type for float field
        with pytest.raises(ValidationError) as exc:
            Product(name="Widget", price="not_a_number", quantity=5)

        # Type validation error should be raised, not invariant error
        assert "price" in exc.value.messages
        assert "must be positive" not in str(exc.value.messages)

    def test_invariants_run_when_field_validations_pass(self):
        """Invariants should be run when all field validations pass."""
        # Valid fields but fails invariant
        with pytest.raises(ValidationError) as exc:
            Product(name="Widget", price=-10.0, quantity=5)

        # Invariant error should be raised
        assert "price" in exc.value.messages
        assert "must be positive" in exc.value.messages["price"][0]

    def test_multiple_field_errors_collected_before_invariant_check(self):
        """Multiple field validation errors should be collected,
        and invariants should not run.
        """
        # Multiple fields have validation errors
        with pytest.raises(ValidationError) as exc:
            Product(name="this_name_is_way_too_long", price="invalid", quantity="bad")

        # Field errors should be present, not invariant error
        assert "name" in exc.value.messages
        assert "price" in exc.value.messages
        assert "quantity" in exc.value.messages
        assert "must be positive" not in str(exc.value.messages)
