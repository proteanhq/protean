from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21


class PersonRepository(BaseRepository):
    pass
