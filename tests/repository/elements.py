# Standard Library Imports
from typing import List

# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Integer, String
from protean.core.repository.base import BaseRepository
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.get_dao(Person).filter(age__gte=minimum_age)

    class Meta:
        aggregate_cls = Person
