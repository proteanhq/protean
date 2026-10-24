import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from protean import Domain
from protean.fields import Float, String

domain = Domain(name="Shop")


@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, required=True)


@pytest.fixture(scope="module", autouse=True)
def shop():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:property]
@settings(deadline=None)
@given(
    amount=st.floats(min_value=0, max_value=1_000_000, allow_nan=False),
    currency=st.sampled_from(["EUR", "INR", "USD"]),
)
def test_money_rebuilt_from_its_dict_equals_the_original(amount, currency):
    money = Money(amount=amount, currency=currency)

    rebuilt = Money(**money.to_dict())

    assert rebuilt.amount == amount
    assert rebuilt.currency == currency


# --8<-- [end:property]
