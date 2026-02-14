from datetime import datetime
from typing import List

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21
    created_at: datetime = datetime.now()


class PersonRepository(BaseRepository):
    def find_adults(self, age: int = 21) -> List[Person]:
        pass  # FIXME Implement filter method


class User(BaseAggregate):
    email: str = Field(max_length=255, json_schema_extra={"unique": True})
    password: str = Field(max_length=3026)
