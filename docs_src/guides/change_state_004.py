from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    name: Annotated[str, Field(max_length=50)]
    email: Annotated[str, Field(max_length=254)]
    age: int = 21


@domain.repository(part_of=Person)  # (1)
class CustomPersonRepository:
    def find_by_email(self, email: str) -> Person:
        return self._dao.find_by(email=email)
