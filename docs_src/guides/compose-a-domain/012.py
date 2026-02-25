# --8<-- [start:full]
from typing import List

from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Person:
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)


@domain.repository(part_of=Person)
class PersonCustomRepository:
    def adults(self, minimum_age: int = 21) -> List[Person]:
        return self.query.filter(age__gte=minimum_age).all().items


# --8<-- [end:full]
