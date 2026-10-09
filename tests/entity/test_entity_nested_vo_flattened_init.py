"""Flattened value object arguments on an entity stop at one level.

An entity accepts ``address_street=...`` for an embedded ``Address`` value
object. A value object nested inside ``Address`` is passed as an object. A
two-level flattened argument such as ``address_location_latitude`` is rejected.
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import HasMany, ValueObject


class Location(BaseValueObject):
    latitude: float = 0.0
    longitude: float = 0.0


class Address(BaseValueObject):
    street: str = ""
    city: str = ""
    location = ValueObject(Location)


class Shop(BaseEntity):
    name: str = ""
    address = ValueObject(Address)


class Mall(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: str = ""
    shops = HasMany(Shop)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Location)
    test_domain.register(Address)
    test_domain.register(Mall)
    test_domain.register(Shop, part_of=Mall)
    test_domain.init(traverse=False)


def test_one_level_flattened_argument_sets_the_field():
    shop = Shop(name="Books", address_street="1 Main St")

    assert shop.address.street == "1 Main St"
    assert shop.address.city == ""
    assert shop.address.location is None


def test_one_level_flattened_argument_through_the_aggregate():
    mall = Mall(name="Central", shops=[Shop(name="Books", address_street="1 Main St")])

    assert mall.shops[0].address.street == "1 Main St"
    assert mall.shops[0].address.city == ""


def test_nested_vo_passed_as_object():
    shop = Shop(
        name="Books",
        address=Address(
            street="1 Main St",
            location=Location(latitude=12.5, longitude=77.6),
        ),
    )

    assert shop.address.street == "1 Main St"
    assert shop.address.location == Location(latitude=12.5, longitude=77.6)


def test_two_level_flattened_argument_is_rejected():
    with pytest.raises(ValidationError) as exc:
        Shop(name="Books", address_location_latitude=12.5)

    assert exc.value.messages["address_location_latitude"] == [
        "Extra inputs are not permitted"
    ]
