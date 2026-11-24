"""The generated ``shared/value_objects.py`` enforces its rules and adds and
subtracts money exactly.

Runs inside a project that ``protean new`` generates, under the project's own
``conftest.py``.
"""

from decimal import Decimal

import pytest
from scaffolded.shared.value_objects import EmailAddress, Money

from protean.exceptions import ValidationError


def test_email_without_at_sign_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        EmailAddress(email="not-an-email")

    assert "email" in exc.value.messages


def test_valid_email_is_accepted() -> None:
    assert EmailAddress(email="a@example.com").email == "a@example.com"


def test_money_adds_exactly_as_decimal() -> None:
    total = Money(amount=Decimal("10.10"), currency="EUR").add(
        Money(amount=Decimal("0.20"), currency="EUR")
    )

    assert isinstance(total.amount, Decimal)
    assert str(total.amount) == "10.30"
    assert total.currency == "EUR"


def test_money_subtracts_exactly_as_decimal() -> None:
    rest = Money(amount=Decimal("10.30"), currency="EUR").subtract(
        Money(amount=Decimal("0.20"), currency="EUR")
    )

    assert isinstance(rest.amount, Decimal)
    assert str(rest.amount) == "10.10"
    assert rest.currency == "EUR"


@pytest.mark.parametrize("operation", ["add", "subtract"])
def test_mixed_currencies_raise_validation_error(operation: str) -> None:
    usd = Money(amount=Decimal(1), currency="USD")
    eur = Money(amount=Decimal(1), currency="EUR")

    with pytest.raises(ValidationError) as exc:
        getattr(usd, operation)(eur)

    assert "currency" in exc.value.messages
