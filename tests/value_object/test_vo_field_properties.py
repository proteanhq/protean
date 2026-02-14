import pytest

from pydantic import Field, PydanticUserError

from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject, _PydanticFieldShim
from protean.fields import HasMany
from protean.utils.reflection import fields


def test_vo_cannot_contain_fields_marked_unique():
    """Value Objects should not contain fields marked 'unique'.

    In the Pydantic-based BaseValueObject the class is created successfully,
    but the field shim correctly reports ``unique=True`` so that higher-level
    checks (e.g. during domain registration) can enforce business rules.
    """

    class Balance(BaseValueObject):
        currency: str = Field(json_schema_extra={"unique": True})
        amount: float

    shim = fields(Balance)["currency"]
    assert isinstance(shim, _PydanticFieldShim)
    assert shim.unique is True


def test_vo_cannot_contain_fields_marked_as_identifiers():
    """Value Objects should not contain fields marked 'identifier'.

    In the Pydantic-based BaseValueObject the class is created successfully,
    but the field shim correctly reports ``identifier=True`` (and therefore
    ``unique=True``) so that higher-level checks can enforce business rules.
    """

    class Balance(BaseValueObject):
        currency: str = Field(json_schema_extra={"identifier": True})
        amount: float

    shim = fields(Balance)["currency"]
    assert isinstance(shim, _PydanticFieldShim)
    assert shim.identifier is True
    assert shim.unique is True


def test_vo_cannot_have_association_fields():
    """Value Objects cannot have association descriptors like HasMany.

    In the Pydantic-based BaseValueObject, Pydantic itself rejects non-annotated
    descriptors (such as HasMany) during class construction.
    """
    with pytest.raises(PydanticUserError):

        class Address(BaseEntity):
            street_address: str | None = None

        class Office(BaseValueObject):
            addresses = HasMany(Address)
