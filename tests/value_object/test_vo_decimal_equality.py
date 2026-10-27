from decimal import Decimal as D

import pytest

from protean.core.value_object import BaseValueObject
from protean.fields import Decimal, String, ValueObject


class Price(BaseValueObject):
    amount: Decimal(precision=19, scale=4, required=True)


class Quantity(BaseValueObject):
    amount: Decimal()


class OtherPrice(BaseValueObject):
    amount: Decimal(precision=19, scale=4, required=True)


class DiscountedPrice(Price):
    pass


class Inner(BaseValueObject):
    amount: Decimal()


class Outer(BaseValueObject):
    label: String(max_length=20)
    inner = ValueObject(Inner)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Price)
    test_domain.register(Quantity)
    test_domain.register(OtherPrice)
    test_domain.register(DiscountedPrice)
    test_domain.register(Inner)
    test_domain.register(Outer)
    test_domain.init(traverse=False)


class TestEqualDecimalsWithDifferentScales:
    def test_scaled_field_values_compare_and_hash_equal(self):
        a = Price(amount=D("9.99"))
        b = Price(amount=D("9.9900"))

        assert a == b
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_unscaled_field_values_compare_and_hash_equal(self):
        a = Quantity(amount=D("1.0"))
        b = Quantity(amount=D(1))

        assert a == b
        assert hash(a) == hash(b)

    def test_nested_value_objects_compare_and_hash_equal(self):
        a = Outer(label="x", inner=Inner(amount=D("1.0")))
        b = Outer(label="x", inner=Inner(amount=D(1)))

        assert a == b
        assert hash(a) == hash(b)


class TestUnequalValueObjects:
    def test_different_amounts_are_unequal(self):
        assert Price(amount=D("9.99")) != Price(amount=D("9.98"))

    def test_different_classes_with_same_values_are_unequal(self):
        assert Price(amount=D("9.99")) != OtherPrice(amount=D("9.99"))

    def test_subclass_with_same_values_is_unequal_to_parent(self):
        assert Price(amount=D("9.99")) != DiscountedPrice(amount=D("9.99"))

    def test_non_value_objects_are_unequal(self):
        price = Price(amount=D("9.99"))

        assert price != "x"
        assert price != None


def test_to_dict_keeps_the_given_scale():
    price = Price(amount=D("9.9900"))

    assert price.to_dict() == {"amount": "9.9900"}
    assert str(price.amount) == "9.9900"
