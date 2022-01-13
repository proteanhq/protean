import pytest

from protean import BaseAggregate, BaseCommand, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import NotSupportedError
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


class ChangeAddress(BaseCommand):
    user_id = Identifier()
    full_address = String()


def test_that_a_handler_is_recorded_against_command_handler(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def register(self, command: Register) -> None:
            pass

    test_domain.register(User)
    test_domain.register(UserCommandHandlers, aggregate_cls=User)

    assert fully_qualified_name(Register) in UserCommandHandlers._handlers


def test_that_multiple_handlers_can_be_recorded_against_command_handler(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def register(self, event: Register) -> None:
            pass

        @handle(ChangeAddress)
        def update_billing_address(self, event: ChangeAddress) -> None:
            pass

    test_domain.register(User)
    test_domain.register(UserCommandHandlers, aggregate_cls=User)

    assert len(UserCommandHandlers._handlers) == 2
    assert all(
        handle_name in UserCommandHandlers._handlers
        for handle_name in [
            fully_qualified_name(Register),
            fully_qualified_name(ChangeAddress),
        ]
    )

    assert len(UserCommandHandlers._handlers[fully_qualified_name(Register)]) == 1
    assert len(UserCommandHandlers._handlers[fully_qualified_name(ChangeAddress)]) == 1
    assert (
        next(iter(UserCommandHandlers._handlers[fully_qualified_name(Register)]))
        == UserCommandHandlers.register
    )
    assert (
        next(iter(UserCommandHandlers._handlers[fully_qualified_name(ChangeAddress)]))
        == UserCommandHandlers.update_billing_address
    )


def test_that_multiple_handlers_cannot_be_recorded_against_the_same_command(
    test_domain,
):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def register(self, event: Register) -> None:
            pass

        @handle(Register)
        def provision_user_account(self, event: Register) -> None:
            pass

    with pytest.raises(NotSupportedError) as exc:
        test_domain.register(User)
        test_domain.register(UserCommandHandlers, aggregate_cls=User)

    assert (
        exc.value.args[0] == "Command Register cannot be handled by multiple handlers"
    )
