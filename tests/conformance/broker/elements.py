from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Auto, Integer, String


class Person(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)

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
    id: Auto(identifier=True)
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    age: Integer(default=21)
