import pytest

from protean import BaseCommand, BaseEventSourcedAggregate, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import NotSupportedError
from protean.fields import Identifier, String, Text


class UnknownCommand(BaseCommand):
    foo = String()


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)  # FIXME Auto-associate ID
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


class ChangeAddress(BaseCommand):
    user_id = Identifier()
    full_address = String()


class UserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, _: Register) -> None:
        pass


class AdminUserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, _: Register) -> None:
        pass


class Post(BaseEventSourcedAggregate):
    topic = String()
    content = Text()


class Create(BaseCommand):
    id = Identifier()
    topic = String()
    content = Text()


class PostCommandHandler(BaseCommandHandler):
    @handle(Create)
    def create_new_post(self, _: Create):
        pass


def test_retrieving_handler_by_command(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(ChangeAddress, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.register(Post)
    test_domain.register(Create, part_of=Post)
    test_domain.register(PostCommandHandler, part_of=Post)

    assert test_domain.command_handler_for(Register()) == UserCommandHandlers
    assert test_domain.command_handler_for(Create()) == PostCommandHandler


def test_for_no_errors_when_no_handler_method_has_not_been_defined_for_a_command(
    test_domain,
):
    assert test_domain.command_handler_for(ChangeAddress) is None


def test_retrieving_handlers_for_unknown_command(test_domain):
    assert test_domain.command_handler_for(UnknownCommand) is None


def test_error_on_defining_multiple_handlers_for_a_command(test_domain):
    test_domain.register(User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.register(AdminUserCommandHandlers, part_of=User)

    with pytest.raises(NotSupportedError) as exc:
        test_domain.command_handler_for(Register())

    assert (
        exc.value.args[0] == "Command Register cannot be handled by multiple handlers"
    )
