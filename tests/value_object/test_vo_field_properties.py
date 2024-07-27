import pytest

from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, HasMany, String


def test_vo_cannot_contain_fields_marked_unique():
    with pytest.raises(IncorrectUsageError) as exception:

        class Balance(BaseValueObject):
            currency = String(max_length=3, required=True, unique=True)
            amount = Float(required=True)

    assert (
        str(exception.value)
        == "Value Objects cannot contain fields marked 'unique' (field 'currency')"
    )


def test_vo_cannot_contain_fields_marked_as_identifiers():
    with pytest.raises(IncorrectUsageError) as exception:

        class Balance(BaseValueObject):
            currency = String(max_length=3, required=True, identifier=True)
            amount = Float(required=True)

    assert (
        str(exception.value)
        == "Value Objects cannot contain fields marked 'identifier' (field 'currency')"
    )


def test_vo_cannot_have_association_fields():
    with pytest.raises(IncorrectUsageError) as exception:

        class Address(BaseEntity):
            street_address = String()

        class Office(BaseValueObject):
            addresses = HasMany(Address)

    assert str(exception.value) == (
        "Value Objects cannot have associations. Remove addresses (HasMany) from class Office"
    )
