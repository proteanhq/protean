import pytest

from protean import BaseAggregate, BaseCommand, BaseCommandHandler
from protean.fields import Integer, String
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)

    @classmethod
    def add_newcomer(cls, person_dict):
        """Factory method to add a new Person to the system"""
        newcomer = Person(
            first_name=person_dict["first_name"],
            last_name=person_dict["last_name"],
            age=person_dict["age"],
        )

        return newcomer


class AddPersonCommand(BaseCommand):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class AddNewPersonCommandHandler(BaseCommandHandler):
    """CommandHandler that adds a new person into the system"""

    class Meta:
        command_cls = AddPersonCommand

    def __call__(self, command: BaseCommand) -> None:
        person = Person.add_newcomer(command.to_dict())
        return current_domain.repository_for(Person).add(person)


class TestCommandHandlerDefinition:
    def test_that_base_command_handler_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseCommandHandler()

    def test_that_command_handler_can_be_retrieved(self, test_domain):
        test_domain.register(AddNewPersonCommandHandler)

        handler = test_domain.command_handler_for(AddPersonCommand)
        assert handler is not None
        assert handler == AddNewPersonCommandHandler
