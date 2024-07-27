import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.core.view import BaseView
from protean.exceptions import IncorrectUsageError
from protean.fields import HasOne, Identifier, Reference, String, ValueObject


class User(BaseAggregate):
    name = String()


class Email(BaseValueObject):
    address = String()


class Role(BaseEntity):
    name = String(max_length=50)


def test_that_views_should_have_at_least_one_identifier_field(test_domain):
    class User(BaseView):
        first_name = String()

    with pytest.raises(IncorrectUsageError) as exception:
        test_domain.register(User)

    assert (
        exception.value.args[0] == "View `User` needs to have at least one identifier"
    )


def test_that_views_cannot_have_value_object_fields():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseView):
            user_id = Identifier(identifier=True)
            email = ValueObject(Email)

    assert (
        exception.value.args[0]
        == "Views can only contain basic field types. Remove email (ValueObject) from class User"
    )


def test_that_views_cannot_have_references():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseView):
            user_id = Identifier(identifier=True)
            role = Reference(Role)

    assert (
        exception.value.args[0]
        == "Views can only contain basic field types. Remove role (Reference) from class User"
    )


def test_that_views_cannot_have_associations():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseView):
            user_id = Identifier(identifier=True)
            role = HasOne(Role)

    assert (
        exception.value.args[0]
        == "Views can only contain basic field types. Remove role (HasOne) from class User"
    )
