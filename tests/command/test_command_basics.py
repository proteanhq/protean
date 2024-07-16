from protean import BaseCommand, BaseEventSourcedAggregate
from protean.fields import Identifier, String


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


def test_domain_stores_command_type_for_easy_retrieval(test_domain):
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    assert Register.__type__ in test_domain._events_and_commands
