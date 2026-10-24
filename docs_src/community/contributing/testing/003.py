import pytest

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String

domain = Domain(name="Shop")


@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, required=True)

    @invariant.post
    def amount_is_not_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})


@pytest.fixture(scope="module", autouse=True)
def shop():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:public_api]
def test_money_keeps_its_amount_and_currency():
    money = Money(amount=12.5, currency="USD")

    assert money.amount == 12.5
    assert money.currency == "USD"


def test_a_negative_amount_is_rejected():
    with pytest.raises(ValidationError) as exc:
        Money(amount=-5.0, currency="USD")

    assert exc.value.messages == {"amount": ["Amount cannot be negative"]}


# --8<-- [end:public_api]
