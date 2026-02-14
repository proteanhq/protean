from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.utils.globals import current_domain


class PersonCommand(BaseCommand):
    first_name: str
    last_name: str
    age: int = 21


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21

    @classmethod
    def add_newcomer(cls, person_dict):
        """Factory method to add a new Person to the system"""
        newcomer = Person(
            first_name=person_dict["first_name"],
            last_name=person_dict["last_name"],
            age=person_dict["age"],
        )

        # Publish Event via the domain
        current_domain.publish(PersonAdded(**newcomer.to_dict()))

        return newcomer


class PersonAdded(BaseEvent):
    id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str
    age: int = 21


class PersonService(BaseApplicationService):
    @classmethod
    def add(cls, command: PersonCommand):
        with UnitOfWork():
            newcomer = Person.add_newcomer(command.to_dict())

            person_repo = current_domain.repository_for(Person)
            person_repo.add(newcomer)

        return newcomer
