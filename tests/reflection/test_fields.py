import pytest

from protean import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String
from protean.reflection import fields


class Person(BaseAggregate):
    name = String(max_length=50, required=True)
    age = Integer()


def test_fields():
    assert len(fields(Person)) == 4
    assert all(key in fields(Person) for key in ["name", "age", "id", "_version"])


def test_fields_on_non_element():
    class Dummy:
        pass

    with pytest.raises(IncorrectUsageError) as exception:
        fields(Dummy)

    assert exception.value.messages == {
        "field": [
            "<class 'test_fields.test_fields_on_non_element.<locals>.Dummy'> "
            "does not have fields"
        ]
    }
