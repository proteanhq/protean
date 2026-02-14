from typing import List, Annotated

from protean import Domain
from protean.utils.globals import current_domain
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)]
    age: int = 21


@domain.repository(part_of=Person)
class PersonCustomRepository:
    def adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)
