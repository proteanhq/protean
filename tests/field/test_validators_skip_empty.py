"""Regression for #1025.

Per-field ``validators=[...]`` must not run against empty values (notably ``None``
for an omitted optional field). The legacy field system skipped validators for
``empty_values``; the Pydantic-based field system must do the same so that an
optional validated field stays optional.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ValidationError
from protean.fields import String
from protean.fields.validators import RegexValidator


class Account(BaseAggregate):
    name = String(required=True)
    # Optional field carrying a format validator that is NOT None-aware.
    referral_code = String(
        validators=[RegexValidator(regex=r"^[A-Z0-9]{6,12}$", message="bad code")]
    )


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(Account)
    test_domain.init(traverse=False)


def test_omitted_optional_field_skips_validators():
    """An unset optional field arrives as None and must not be validated."""
    account = Account(name="Acme")
    assert account.referral_code is None


def test_validator_still_runs_on_a_provided_value():
    with pytest.raises(ValidationError) as exc:
        Account(name="Acme", referral_code="bad!")
    assert "bad code" in str(exc.value)


def test_valid_provided_value_passes():
    account = Account(name="Acme", referral_code="ABC123")
    assert account.referral_code == "ABC123"
