import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.utils.reflection import fields


class Person(BaseAggregate):
    name: str
    age: int | None = None


def test_fields():
    assert len(fields(Person)) == 4
    assert all(key in fields(Person) for key in ["_version", "name", "age", "id"])


def test_fields_on_non_element():
    class Dummy:
        pass

    with pytest.raises(IncorrectUsageError) as exception:
        fields(Dummy)  # type: ignore - This is expected to raise an exception.

    assert exception.value.args[0] == (
        "<class 'test_fields.test_fields_on_non_element.<locals>.Dummy'> "
        "does not have fields"
    )
