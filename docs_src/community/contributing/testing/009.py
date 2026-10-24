import pytest
from hypothesis import given
from hypothesis import strategies as st

from protean import Domain
from protean.fields import Float, String

domain = Domain(name="Shop")


@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, required=True)


# Hypothesis runs a test body many times inside one call of the test, so a
# function-scoped fixture would not reset between those runs.
@pytest.fixture(scope="module", autouse=True)
def shop():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:property]
@given(
    amount=st.floats(min_value=0, max_value=1_000_000, allow_nan=False),
    currency=st.sampled_from(["EUR", "INR", "USD"]),
)
def test_money_rebuilt_from_its_dict_equals_the_original(amount, currency):
    money = Money(amount=amount, currency=currency)

    assert Money(**money.to_dict()) == money


# --8<-- [end:property]
