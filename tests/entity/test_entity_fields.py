import pytest

from protean.core.entity import BaseEntity
from protean.core.field.basic import Integer, String
from protean.exceptions import IncorrectUsageError


def test_that_entities_cannot_hold_entities(test_domain):
    class Address(BaseEntity):
        street = String(max_length=50)

    with pytest.raises(IncorrectUsageError) as exc:

        class Person(BaseEntity):
            name = String(max_length=50, required=True)
            age = Integer(default=21)
            address = Address()

    assert exc.value.messages == {
        "entity": ["'address' of type 'Address' cannot be part of an entity."]
    }
