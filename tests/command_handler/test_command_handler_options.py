import pytest

from protean import BaseAggregate, BaseCommand, BaseCommandHandler
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


def test_part_of_is_mandatory(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        pass

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(UserCommandHandlers)

    assert exc.value.messages == {
        "_entity": [
            "Command Handler `UserCommandHandlers` needs to be associated with an Aggregate"
        ]
    }


def test_part_of_specified_as_a_meta_attribute(test_domain):
    class UserCommandHandlers(BaseCommandHandler):
        pass

    test_domain.register(UserCommandHandlers, part_of=User)
    assert UserCommandHandlers.meta_.part_of == User


def test_part_of_defined_via_annotation(
    test_domain,
):
    @test_domain.command_handler(part_of=User)
    class UserCommandHandlers(BaseCommandHandler):
        pass

    assert UserCommandHandlers.meta_.part_of == User
