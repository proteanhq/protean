import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import NotSupportedError
from protean.utils.mixins import handle


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class Register(BaseCommand):
    user_id: str | None = None
    email: str | None = None


class ChangeAddress(BaseCommand):
    user_id: str | None = None
    full_address: str | None = None


def test_that_a_handler_is_recorded_against_command_handler(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def register(self, command: Register) -> None:
            pass

    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)

    assert Register.__type__ in UserCommandHandlers._handlers


def test_that_multiple_handlers_can_be_recorded_against_command_handler(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def register(self, event: Register) -> None:
            pass

        @handle(ChangeAddress)
        def update_billing_address(self, event: ChangeAddress) -> None:
            pass

    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(ChangeAddress, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)

    assert len(UserCommandHandlers._handlers) == 2
    assert all(
        handle_name in UserCommandHandlers._handlers
        for handle_name in [
            Register.__type__,
            ChangeAddress.__type__,
        ]
    )

    assert len(UserCommandHandlers._handlers[Register.__type__]) == 1
    assert len(UserCommandHandlers._handlers[ChangeAddress.__type__]) == 1
    assert (
        next(iter(UserCommandHandlers._handlers[Register.__type__]))
        == UserCommandHandlers.register
    )
    assert (
        next(iter(UserCommandHandlers._handlers[ChangeAddress.__type__]))
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

    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)

    with pytest.raises(NotSupportedError) as exc:
        test_domain.init(traverse=False)

    assert (
        exc.value.args[0] == "Command Register cannot be handled by multiple handlers"
    )
