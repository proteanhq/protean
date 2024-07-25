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


def test_vo_invariant_raises_error_on_initialization(test_domain):
    test_domain.register(Balance)

    with pytest.raises(ValidationError) as exc:
        Balance(currency="USD", amount=-100.0)

    assert str(exc.value) == "{'balance': ['Balance cannot be negative for USD']}"
