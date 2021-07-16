from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Integer, String
from protean.core.repository import BaseRepository


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    pass
