import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.exceptions import IncorrectUsageError, InvalidDataError, NotSupportedError
from protean.fields import Integer, String
from protean.utils import fully_qualified_name
from protean.utils.reflection import fields


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()
    address = String()


class UserRegistrationCommand(BaseCommand):
    email = String(required=True, identifier=True, max_length=250)
    username = String(required=True, max_length=50)
    password = String(required=True, max_length=255)
    age = Integer(default=21)


class TestCommandInitialization:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User)
        test_domain.register(UserRegistrationCommand, part_of=User)
        test_domain.init(traverse=False)

    def test_that_command_object_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseCommand()

    def test_that_a_concrete_dto_can_be_instantiated(self):
        command = UserRegistrationCommand(
            email="john.doe@gmail.com",
            username="john.doe",
            password="secret1!",
        )
        assert command is not None

    def test_that_invalid_data_input_throws_an_exception(self):
        with pytest.raises(InvalidDataError) as exception1:
            UserRegistrationCommand(
                foo="bar",
                username="john.doe",
                password="secret1!",
            )
        assert exception1.value.messages == {"foo": ["is invalid"]}

        with pytest.raises(InvalidDataError) as exception2:
            UserRegistrationCommand(
                email="john.doe@gmail.com",
                username="123456789012345678901234567890123456789012345678901234567890",
                password="secret1!",
            )
        assert exception2.value.messages == {
            "username": ["value has more than 50 characters"]
        }


class TestCommandRegistration:
    def test_that_command_can_be_registered_with_domain(self, test_domain):
        test_domain.register(UserRegistrationCommand, part_of=User)

        assert (
            fully_qualified_name(UserRegistrationCommand)
            in test_domain.registry.commands
        )

    def test_that_command_can_be_registered_via_annotations(self, test_domain):
        @test_domain.command(part_of=User)
        class ChangePasswordCommand:
            old_password = String(required=True, max_length=255)
            new_password = String(required=True, max_length=255)

        assert (
            fully_qualified_name(ChangePasswordCommand) in test_domain.registry.commands
        )


class TestCommandProperties:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User)
        test_domain.register(UserRegistrationCommand, part_of=User)
        test_domain.init(traverse=False)

    def test_two_commands_with_equal_values_are_considered_equal(self):
        command1 = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        command2 = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )

        # The commands themselves will not be equal because their metadata, like
        #   timestamp, can differ. But their payloads should be equal
        assert command1.payload == command2.payload

    def test_that_commands_are_immutable(self):
        command = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        with pytest.raises(IncorrectUsageError):
            command.username = "jane.doe"

    def test_output_to_dict(self):
        command = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        assert command.payload == {
            "email": "john.doe@gmail.com",
            "username": "john.doe",
            "password": "secret1!",
            "age": 21,
        }

    def test_different_commands_are_distinct(self, test_domain):
        command1 = test_domain._enrich_command(
            UserRegistrationCommand(
                email="john.doe@gmail.com", username="john.doe", password="secret1!"
            )
        )
        command2 = test_domain._enrich_command(
            UserRegistrationCommand(
                email="jane.doe@gmail.com",
                username="jane.doe",
                password="not-so-secret!",
            )
        )

        assert command1 != command2


class TestCommandInheritance:
    class AbstractCommand(BaseCommand):
        foo = String()

    class ConcreteCommand(AbstractCommand):
        bar = String()

    def test_inheritance_of_parent_fields(self):
        assert all(
            field_name in fields(TestCommandInheritance.ConcreteCommand)
            for field_name in ["foo", "bar"]
        )

    def test_inheritance_of_parent_fields_with_annotations(self, test_domain):
        @test_domain.command(abstract=True)
        class AbstractCommand2:
            foo = String()

        @test_domain.command(part_of=User)
        class ConcreteCommand2(AbstractCommand2):
            bar = String()

        assert all(
            field_name in fields(ConcreteCommand2) for field_name in ["foo", "bar"]
        )

    def test_inheritance_of_parent_fields_with_child_annotation_alone(
        self, test_domain
    ):
        @test_domain.command(part_of=User)
        class ConcreteCommand3(TestCommandInheritance.AbstractCommand):
            bar = String()

        assert all(
            field_name in fields(ConcreteCommand3) for field_name in ["foo", "bar"]
        )
