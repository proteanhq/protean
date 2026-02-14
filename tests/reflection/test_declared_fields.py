import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String
from protean.utils.reflection import declared_fields


class Person(BaseAggregate):
    name: String(max_length=50, required=True)
    age: Integer()


def test_declared_fields():
    assert len(declared_fields(Person)) == 3
    assert all(key in declared_fields(Person) for key in ["name", "age", "id"])


def test_declared_fields_on_non_element():
    class Dummy:
        pass

    with pytest.raises(IncorrectUsageError) as exception:
        declared_fields(Dummy)

    assert exception.value.args[0] == (
        "<class 'test_declared_fields.test_declared_fields_on_non_element.<locals>.Dummy'> "
        "does not have fields"
    )
