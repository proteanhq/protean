import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.entity import _LegacyBaseEntity as BaseEntity
from protean.core.projection import BaseProjection
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import HasOne, Identifier, Reference, String, ValueObject


class User(BaseAggregate):
    name = String()


class Email(BaseValueObject):
    address = String()


class Role(BaseEntity):
    name = String(max_length=50)


def test_that_projections_should_have_at_least_one_identifier_field(test_domain):
    class User(BaseProjection):
        first_name = String()

    with pytest.raises(IncorrectUsageError) as exception:
        test_domain.register(User)

    assert (
        exception.value.args[0]
        == "Projection `User` needs to have at least one identifier"
    )


def test_that_projections_cannot_have_value_object_fields():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseProjection):
            user_id = Identifier(identifier=True)
            email = ValueObject(Email)

    assert (
        exception.value.args[0]
        == "Projections can only contain basic field types. Remove email (ValueObject) from class User"
    )


def test_that_projections_cannot_have_references():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseProjection):
            user_id = Identifier(identifier=True)
            role = Reference(Role)

    assert (
        exception.value.args[0]
        == "Projections can only contain basic field types. Remove role (Reference) from class User"
    )


def test_that_projections_cannot_have_associations():
    with pytest.raises(IncorrectUsageError) as exception:

        class User(BaseProjection):
            user_id = Identifier(identifier=True)
            role = HasOne(Role)

    assert (
        exception.value.args[0]
        == "Projections can only contain basic field types. Remove role (HasOne) from class User"
    )
