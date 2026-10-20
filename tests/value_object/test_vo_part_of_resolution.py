"""A value object's string `part_of` resolves to the aggregate class at init."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError
from protean.fields import Float, HasMany, String


class Product(BaseAggregate):
    name: String()


class TierPrice(BaseValueObject):
    amount: Float(required=True)


class Order(BaseAggregate):
    lines = HasMany("Line")


class Line(BaseEntity):
    sku: String()


def test_string_part_of_resolves_to_aggregate_class(test_domain):
    test_domain.register(Product)
    test_domain.register(TierPrice, part_of="Product")
    test_domain.init(traverse=False)

    assert TierPrice.meta_.part_of is Product


def test_class_part_of_is_unchanged(test_domain):
    test_domain.register(Product)
    test_domain.register(TierPrice, part_of=Product)
    test_domain.init(traverse=False)

    assert TierPrice.meta_.part_of is Product


def test_value_object_without_part_of_keeps_none(test_domain):
    test_domain.register(Product)
    test_domain.register(TierPrice)
    test_domain.init(traverse=False)

    assert TierPrice.meta_.part_of is None


def test_misspelled_aggregate_name_fails_init(test_domain):
    test_domain.register(Product)
    test_domain.register(TierPrice, part_of="Prodct")

    with pytest.raises(ConfigurationError) as exc:
        test_domain.init(traverse=False)

    message = str(exc.value)
    assert "`TierPrice` references `Prodct` via part_of" in message


def test_entity_name_fails_init(test_domain):
    test_domain.register(Order)
    test_domain.register(Line, part_of=Order)
    test_domain.register(TierPrice, part_of="Line")

    with pytest.raises(ConfigurationError) as exc:
        test_domain.init(traverse=False)

    message = str(exc.value)
    assert "`TierPrice` references `Line` via part_of" in message
