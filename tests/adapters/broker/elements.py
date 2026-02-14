from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21

    @classmethod
    def add_newcomer(cls, person_dict):
        """Factory method to add a new Person to the system"""
        newcomer = Person(
            id=person_dict["id"],
            first_name=person_dict["first_name"],
            last_name=person_dict["last_name"],
            age=person_dict["age"],
        )

        newcomer.raise_(
            PersonAdded(
                id=newcomer.id,
                first_name=newcomer.first_name,
                last_name=newcomer.last_name,
                age=newcomer.age,
            )
        )
        return newcomer


class PersonAdded(BaseEvent):
    id: str | None = None
    first_name: str
    last_name: str
    age: int = 21
