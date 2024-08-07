from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


def test_command_submission_without_aggregate(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.init(traverse=False)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(Register)

    assert (
        exc.value.args[0]
        == "Command `Register` needs to be associated with an aggregate or a stream"
    )


@pytest.mark.eventstore
def test_command_submission(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    messages = test_domain.event_store.store.read("test::user:command")

    assert len(messages) == 1
    messages[0].stream_name == f"test::user:command-{identifier}"
