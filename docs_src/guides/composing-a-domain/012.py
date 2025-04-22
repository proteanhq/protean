from typing import List

from protean import Domain
from protean.fields import Integer, String
from protean.utils.globals import current_domain

domain = Domain()


@domain.aggregate
class Person:
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


@domain.repository(part_of=Person)
class PersonCustomRepository:
    def adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)
