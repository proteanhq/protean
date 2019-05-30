from datetime import datetime
from typing import List

from protean.core.aggregate import BaseAggregate
from protean.core.repository.base import BaseRepository
from protean.core.field.basic import DateTime, Integer, String


class Role(BaseAggregate):
    name = String(max_length=15, required=True)
    created_on = DateTime(default=datetime.today())


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
