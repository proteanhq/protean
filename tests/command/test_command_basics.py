import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.fields import Identifier, String


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Register(BaseCommand):
    user_id: Identifier(identifier=True)
    email: String()
    name: String()


def test_domain_stores_command_type_for_easy_retrieval(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    assert Register.__type__ in test_domain._events_and_commands


def test_template_dict_and_kwargs_merge(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    command = Register({"user_id": "1", "name": "John"}, name="Jane")
    assert command.user_id == "1"
    assert command.name == "Jane"


def test_non_dict_positional_arg_raises_type_error(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    with pytest.raises(TypeError) as exc:
        Register("not-a-dict")
    assert str(exc.value) == (
        "Positional argument not-a-dict passed must be a dict. "
        "This argument serves as a template for loading common values."
    )
