from logging import exception
import pytest
from protean.core.entity import BaseEntity

from protean.core.exceptions import IncorrectUsageError
from protean.core.field.association import HasOne, Reference
from protean.core.field.basic import String
from protean.core.field.embedded import ValueObjectField
from protean.core.value_object import BaseValueObject
from protean.core.view import BaseView


class Email(BaseValueObject):
    address = String()


class Role(BaseEntity):
    name = String(max_length=50)


def test_that_views_cannot_have_value_object_fields():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseView):
            email = ValueObjectField(Email)

    assert (
        exception.value.messages
        == "Views can only contain basic field types. Remove email (ValueObjectField) from class User"
    )


def test_that_views_cannot_have_references():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseView):
            role = Reference(Role)

    assert (
        exception.value.messages
        == "Views can only contain basic field types. Remove role (Reference) from class User"
    )


def test_that_views_cannot_have_associations():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseView):
            role = HasOne(Role)

    assert (
        exception.value.messages
        == "Views can only contain basic field types. Remove role (HasOne) from class User"
    )
