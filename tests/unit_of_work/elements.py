from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean.fields import Integer, String


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)


class PersonRepository(BaseRepository):
    pass
