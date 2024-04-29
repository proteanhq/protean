from typing import List

from protean import Domain
from protean.fields import Integer, String
from protean.globals import current_domain

domain = Domain(__file__)


@domain.aggregate
class Person:
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


@domain.repository(aggregate_cls=Person)
class PersonCustomRepository:
    def adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)
