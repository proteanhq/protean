import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.field.basic import Integer, String
from protean.globals import current_domain
from protean.utils import CommandProcessingType


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


class TestCommandHandlerInvocation:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(AddPersonCommand)
        test_domain.register(AddNewPersonCommandHandler)

    def test_async_command_handler_invocation(self, test_domain):
        # COMMAND_PROCESSING is ASYNC by default
        assert (
            test_domain.config["COMMAND_PROCESSING"]
            == CommandProcessingType.ASYNC.value
        )

        result = test_domain.handle(
            AddPersonCommand(first_name="John", last_name="Doe")
        )

        # Verify that no result was returned
        assert result is None

        # Verify there is no side-effect of the command handler yet
        people = current_domain.get_dao(Person).query.all().items
        assert len(people) == 0

    def test_synchronous_command_handler_invocation(self, test_domain):
        test_domain.config["COMMAND_PROCESSING"] = CommandProcessingType.SYNC.value

        result = test_domain.handle(
            AddPersonCommand(first_name="John", last_name="Doe")
        )

        # Verify that no result was returned
        assert result is not None
        assert result.first_name == "John"

    def test_overridden_sync_or_async_behavior(self, test_domain):
        # COMMAND_PROCESSING is ASYNC by default
        assert (
            test_domain.config["COMMAND_PROCESSING"]
            == CommandProcessingType.ASYNC.value
        )

        result = test_domain.handle(
            AddPersonCommand(first_name="John", last_name="Doe"), asynchronous=False,
        )

        # Verify that no result was returned
        assert result is not None
        assert result.first_name == "John"
