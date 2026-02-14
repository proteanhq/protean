import pytest

from protean.core.entity import invariant
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Float, String


class Balance(BaseValueObject):
    currency = String(max_length=3, required=True)
    amount = Float(required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError({"balance": ["Balance cannot be negative for USD"]})


@pytest.fixture(autouse=True)
def register_vo(test_domain):
    test_domain.register(Balance)


def test_vo_invariant_raises_error_on_initialization(test_domain):
    with pytest.raises(ValidationError) as exc:
        Balance(currency="USD", amount=-100.0)

    assert str(exc.value) == "{'balance': ['Balance cannot be negative for USD']}"


class TestFieldValidationsBeforeInvariants:
    """Test that field-level validations are checked first,
    and invariants are only run when field validations pass."""

    def test_field_validation_errors_prevent_invariant_checks(self, test_domain):
        """When field-level validations fail, invariants should not be run.

        Currency exceeds max_length (3), and amount is negative with what would
        be USD - but since field validation fails, invariant should not run.
        """

        # Currency too long (max_length=3) with data that would fail invariant
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USDT", amount=-100.0)

        # Only field validation error should be raised, not invariant error
        assert "currency" in exc.value.messages
        assert "balance" not in exc.value.messages

    def test_required_field_missing_prevents_invariant_checks(self, test_domain):
        """When required fields are missing, invariants should not be run."""

        # Missing required amount field
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USD")

        # Required field error should be raised (not invariant error)
        assert "amount" in exc.value.messages
        assert "is required" in exc.value.messages["amount"][0]
        assert "balance" not in exc.value.messages

    def test_invalid_field_type_prevents_invariant_checks(self, test_domain):
        """When field type validation fails, invariants should not be run."""

        # Invalid type for float field, with currency that would trigger invariant
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USD", amount="not_a_number")

        # Type validation error should be raised, not invariant error
        assert "amount" in exc.value.messages
        assert "balance" not in exc.value.messages

    def test_invariants_run_when_field_validations_pass(self, test_domain):
        """Invariants should be run when all field validations pass."""

        # Valid fields but fails invariant
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USD", amount=-100.0)

        assert "balance" in exc.value.messages
        assert "cannot be negative for USD" in exc.value.messages["balance"][0]

    def test_multiple_field_errors_collected_before_invariant_check(self, test_domain):
        """Multiple field validation errors should be collected,
        and invariants should not run.
        """

        # Both fields have validation errors
        with pytest.raises(ValidationError) as exc:
            Balance(currency="USDT", amount="invalid")

        # Field errors should be present, not invariant error
        assert "currency" in exc.value.messages
        assert "amount" in exc.value.messages
        assert "balance" not in exc.value.messages
