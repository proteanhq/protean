# --8<-- [start:construction]
from datetime import date

import pytest
from isolation_shop.domain import DateRange, Email, Money

from protean.exceptions import IncorrectUsageError, ValidationError


class TestMoney:
    def test_valid_money(self):
        money = Money(amount=100.0, currency="USD")

        assert money.amount == 100.0
        assert money.currency == "USD"

    def test_negative_amount_rejected(self):
        with pytest.raises(ValidationError) as exc:
            Money(amount=-10.0, currency="USD")

        assert "cannot be negative" in str(exc.value)

    def test_invalid_currency_rejected(self):
        with pytest.raises(ValidationError) as exc:
            Money(amount=10.0, currency="XYZ")

        assert "Invalid currency" in str(exc.value)

    def test_zero_amount_allowed(self):
        money = Money(amount=0.0, currency="USD")
        assert money.amount == 0.0


# --8<-- [end:construction]


# --8<-- [start:equality]
class TestMoneyEquality:
    def test_same_values_are_equal(self):
        money1 = Money(amount=100.0, currency="USD")
        money2 = Money(amount=100.0, currency="USD")
        assert money1 == money2

    def test_different_amounts_are_not_equal(self):
        money1 = Money(amount=100.0, currency="USD")
        money2 = Money(amount=200.0, currency="USD")
        assert money1 != money2

    def test_different_currencies_are_not_equal(self):
        money1 = Money(amount=100.0, currency="USD")
        money2 = Money(amount=100.0, currency="EUR")
        assert money1 != money2


# --8<-- [end:equality]


# --8<-- [start:operations]
class TestMoneyOperations:
    def test_adding_same_currency(self):
        result = Money(amount=30.0, currency="USD").add(
            Money(amount=20.0, currency="USD")
        )
        assert result == Money(amount=50.0, currency="USD")

    def test_adding_different_currencies_fails(self):
        with pytest.raises(ValidationError) as exc:
            Money(amount=30.0, currency="USD").add(Money(amount=20.0, currency="EUR"))
        assert "Cannot add different currencies" in str(exc.value)


class TestDateRange:
    def test_contains_date(self):
        range_ = DateRange(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert range_.contains(date(2024, 6, 15)) is True
        assert range_.contains(date(2025, 1, 1)) is False

    def test_overlapping_ranges(self):
        range1 = DateRange(start_date=date(2024, 1, 1), end_date=date(2024, 6, 30))
        range2 = DateRange(start_date=date(2024, 4, 1), end_date=date(2024, 12, 31))
        assert range1.overlaps(range2) is True

    def test_non_overlapping_ranges(self):
        range1 = DateRange(start_date=date(2024, 1, 1), end_date=date(2024, 3, 31))
        range2 = DateRange(start_date=date(2024, 7, 1), end_date=date(2024, 12, 31))
        assert range1.overlaps(range2) is False


# --8<-- [end:operations]


# --8<-- [start:immutability]
class TestValueObjectImmutability:
    def test_value_object_is_immutable(self):
        email = Email(address="user@example.com")

        with pytest.raises(IncorrectUsageError):
            email.address = "other@example.com"


# --8<-- [end:immutability]
