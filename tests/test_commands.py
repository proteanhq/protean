import pytest

from protean.core.command import BaseCommand
from protean.core.field.basic import Integer, String
from protean.exceptions import (
    InvalidDataError,
    InvalidOperationError,
    NotSupportedError,
)
from protean.utils import fully_qualified_name


class UserRegistrationCommand(BaseCommand):
    email = String(required=True, max_length=250)
    username = String(required=True, max_length=50)
    password = String(required=True, max_length=255)
    age = Integer(default=21)


class TestCommandInitialization:
    def test_that_command_object_class_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseCommand()

    def test_that_a_concrete_dto_can_be_instantiated(self):
        command = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!",
        )
        assert command is not None

    def test_that_invalid_data_input_throws_an_exception(self):
        with pytest.raises(InvalidDataError) as exception1:
            UserRegistrationCommand(
                foo="bar", username="john.doe", password="secret1!",
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
        test_domain.register(UserRegistrationCommand)

        assert (
            fully_qualified_name(UserRegistrationCommand)
            in test_domain.registry.commands
        )

    def test_that_command_can_be_registered_via_annotations(self, test_domain):
        @test_domain.command
        class ChangePasswordCommand:
            old_password = String(required=True, max_length=255)
            new_password = String(required=True, max_length=255)

        assert (
            fully_qualified_name(ChangePasswordCommand) in test_domain.registry.commands
        )


class TestCommandProperties:
    def test_two_commands_with_equal_values_are_considered_equal(self):
        command1 = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        command2 = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )

        assert command1 == command2

    @pytest.mark.xfail
    def test_that_commands_are_immutable(self):
        command = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        with pytest.raises(InvalidOperationError):
            command.username = "jane.doe"

    def test_output_to_dict(self):
        command = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        assert command.to_dict() == {
            "email": "john.doe@gmail.com",
            "username": "john.doe",
            "password": "secret1!",
            "age": 21,
        }

    def test_different_commands_are_distinct(self):
        command1 = UserRegistrationCommand(
            email="john.doe@gmail.com", username="john.doe", password="secret1!"
        )
        command2 = UserRegistrationCommand(
            email="jane.doe@gmail.com", username="jane.doe", password="not-so-secret!"
        )

        assert command1 != command2
