import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Identifier, String
from protean.utils.mixins import handle


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier()
    email = String()
    name = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


def test_that_base_command_handler_cannot_be_instantianted():
    with pytest.raises(NotSupportedError):
        BaseCommandHandler()


def test_only_commands_can_be_associated_with_command_handlers(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Registered)
        def something(self, _: Registered):
            pass

    test_domain.register(User)
    test_domain.register(UserCommandHandlers, part_of=User)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert exc.value.messages == {
        "_command_handler": [
            "Method `something` in Command Handler `UserCommandHandlers` is not associated with a command"
        ]
    }


def test_commands_have_to_be_registered_with_an_aggregate(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def something(self, _: Register):
            pass

    test_domain.register(User)
    test_domain.register(UserCommandHandlers, part_of=User)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert exc.value.messages == {
        "_command_handler": [
            "Command `Register` in Command Handler `UserCommandHandlers` is not associated with an aggregate"
        ]
    }


def test_command_and_command_handler_have_to_be_associated_with_same_aggregate(
    test_domain,
):
    class UserCommandHandlers(BaseCommandHandler):
        @handle(Register)
        def something(self, _: Register):
            pass

    class User2(BaseAggregate):
        email = String()
        name = String()

    test_domain.register(User)
    test_domain.register(User2)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User2)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert exc.value.messages == {
        "_command_handler": [
            "Command `Register` in Command Handler `UserCommandHandlers` is not associated with the same aggregate as the Command Handler"
        ]
    }

    test_domain.register(UserCommandHandlers, part_of=User)
