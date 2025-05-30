import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Auto, Integer, String


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)

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
    id = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.init(traverse=False)


@pytest.mark.broker
def test_message_push_after_uow_exit(test_domain):
    with UnitOfWork():
        person = Person.add_newcomer(
            {"id": "1", "first_name": "John", "last_name": "Doe", "age": 25}
        )

        test_domain.repository_for(Person).add(person)
        test_domain.publish("person_added", person._events[0].to_dict())

        assert test_domain.brokers["default"].get_next("person_added") is None

    message = test_domain.brokers["default"].get_next("person_added")
    assert message is not None
    assert message["id"] == "1"
    assert message["first_name"] == "John"
    assert message["last_name"] == "Doe"
    assert message["age"] == 25
    assert "_metadata" in message
