from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.utils.reflection import data_fields


class Person(BaseAggregate):
    name = String(max_length=50, required=True)
    age = Integer()


def test_data_fields():
    assert len(data_fields(Person)) == 4
    assert all(key in data_fields(Person) for key in ["name", "age", "id", "_version"])
