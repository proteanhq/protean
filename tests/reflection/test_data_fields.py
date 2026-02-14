import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String
from protean.utils.reflection import data_fields


class Person(BaseAggregate):
    name: String(max_length=50, required=True)
    age: Integer()


def test_data_fields():
    assert len(data_fields(Person)) == 4
    assert all(key in data_fields(Person) for key in ["name", "age", "id", "_version"])


def test_data_fields_on_non_element():
    class Dummy:
        pass

    with pytest.raises(IncorrectUsageError) as exception:
        data_fields(Dummy)

    assert exception.value.args[0] == (
        "<class 'test_data_fields.test_data_fields_on_non_element.<locals>.Dummy'> "
        "does not have fields"
    )
