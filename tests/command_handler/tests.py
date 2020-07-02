# Protean
import pytest

from mock import patch
from protean.core.command_handler import BaseCommandHandler
from protean.utils import fully_qualified_name

# Local/Relative Imports
from .elements import AddNewPersonCommandHandler, AddPersonCommand


class TestCommandHandlerInitialization:
    def test_that_base_command_handler_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseCommandHandler()

    def test_that_command_handler_can_be_instantiated(self, test_domain):
        service = AddNewPersonCommandHandler(
            test_domain, AddPersonCommand(first_name="John", last_name="Doe", age=21)
        )
        assert service is not None


class TestCommandHandlerRegistration:
    def test_that_command_handler_can_be_registered_with_domain(self, test_domain):
        test_domain.register(AddNewPersonCommandHandler)

        assert (
            fully_qualified_name(AddNewPersonCommandHandler)
            in test_domain.command_handlers
        )

    def test_that_domain_event_can_be_registered_via_annotations(self, test_domain):
        @test_domain.command_handler(command=AddPersonCommand)
        class AnnotatedCommandHandler:
            def special_method(self):
                pass

        assert (
            fully_qualified_name(AnnotatedCommandHandler)
            in test_domain.command_handlers
        )


class TestDomainEventNotification:
    @patch.object(AddNewPersonCommandHandler, "notify")
    def test_that_domain_event_is_received_from_aggregate_command_method(
        self, mock, test_domain
    ):
        test_domain.register(AddNewPersonCommandHandler)

        command = AddPersonCommand(first_name="John", last_name="Doe", age=21)
        test_domain.publish_command(command)
        mock.assert_called_once_with(command.to_dict())
