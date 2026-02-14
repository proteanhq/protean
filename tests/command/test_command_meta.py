from uuid import uuid4

import pytest

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.exceptions import IncorrectUsageError


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class Register(BaseCommand):
    user_id: str = Field(json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None


def test_command_definition_without_aggregate_or_stream(test_domain):
    test_domain.register(User, is_event_sourced=True)

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(Register)

    assert (
        exc.value.args[0]
        == "Command `Register` needs to be associated with an aggregate or a stream"
    )


def test_that_abstract_commands_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractCommand(BaseCommand):
        foo: str | None = None

    try:
        test_domain.register(AbstractCommand, abstract=True)
    except Exception:
        pytest.fail(
            "Abstract commands should be definable without being associated with an aggregate or a stream"
        )


@pytest.mark.eventstore
def test_command_associated_with_aggregate(test_domain):
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
    assert messages[0].metadata.headers.stream == f"test::user:command-{identifier}"


@pytest.mark.eventstore
def test_command_associated_with_aggregate_with_custom_stream_name(test_domain):
    test_domain.register(User, is_event_sourced=True, stream_category="foo")
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

    messages = test_domain.event_store.store.read("test::foo:command")

    assert len(messages) == 1
    assert messages[0].metadata.headers.stream == f"test::foo:command-{identifier}"


def test_aggregate_cluster_of_event(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.init(traverse=False)

    assert Register.meta_.aggregate_cluster == User
