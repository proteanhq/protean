# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.domain_event import BaseDomainEvent
from protean.core.field.basic import Integer, String
from protean.core.field.embedded import AggregateField
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)

    @classmethod
    def add_newcomer(cls, person_dict):
        """Factory method to add a new Person to the system"""
        newcomer = Person(
            first_name=person_dict['first_name'],
            last_name=person_dict['last_name'],
            age=person_dict['age'],
            )

        # Publish Event via the domain
        current_domain.publish(PersonAdded(person=newcomer))

        return newcomer


class PersonAdded(BaseDomainEvent):
    person = AggregateField(Person)
