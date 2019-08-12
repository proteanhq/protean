# Protean
import pytest

from protean.core.command import BaseCommand
from protean.core.exceptions import InvalidOperationError
from protean.core.field.basic import String
from protean.utils import fully_qualified_name

# Local/Relative Imports
from .elements import UserRegistrationCommand


class TestCommandInitialization:
    def test_that_command_object_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseCommand()

    def test_that_a_concrete_dto_can_be_instantiated(self):
        command = UserRegistrationCommand(
            email='john.doe@gmail.com',
            username='john.doe',
            password='secret1!'
        )
        assert command is not None


class TestCommandRegistration:
    def test_that_command_can_be_registered_with_domain(self, test_domain):
        test_domain.register(UserRegistrationCommand)

        assert fully_qualified_name(UserRegistrationCommand) in test_domain.commands

    def test_that_command_can_be_registered_via_annotations(self, test_domain):
        @test_domain.command
        class ChangePasswordCommand:
            old_password = String(required=True, max_length=255)
            new_password = String(required=True, max_length=255)

        assert fully_qualified_name(ChangePasswordCommand) in test_domain.commands


class TestCommandProperties:
    def test_two_commands_with_equal_values_are_considered_equal(self):
        command1 = UserRegistrationCommand(email='john.doe@gmail.com', username='john.doe', password='secret1!')
        command2 = UserRegistrationCommand(email='john.doe@gmail.com', username='john.doe', password='secret1!')

        assert command1 == command2

    @pytest.mark.xfail
    def test_that_commands_are_immutable(self):
        command = UserRegistrationCommand(email='john.doe@gmail.com', username='john.doe', password='secret1!')
        with pytest.raises(InvalidOperationError):
            command.username = 'jane.doe'

    def test_output_to_dict(self):
        command = UserRegistrationCommand(email='john.doe@gmail.com', username='john.doe', password='secret1!')
        assert command.to_dict() == {
            'email': 'john.doe@gmail.com',
            'username': 'john.doe',
            'password': 'secret1!'
        }
