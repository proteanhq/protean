
# Standard Library Imports
from typing import List

# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Integer, String
from protean.core.repository.base import BaseRepository


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, age: int = 21) -> List[Person]:
        pass  # FIXME Implement filter method


class User(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    password = String(max_length=3026)
