from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of=User)
    test_domain.init(traverse=False)


def test_event_definition_without_aggregate_or_stream(test_domain):
    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.register(UserLoggedIn)

    assert exc.value.messages == {
        "_event": [
            "Event `UserLoggedIn` needs to be associated with an aggregate or a stream"
        ]
    }


def test_event_definition_with_just_part_of(test_domain):
    try:
        identifier = str(uuid4())
        test_domain.raise_(UserLoggedIn(user_id=identifier))
    except IncorrectUsageError:
        pytest.fail("Failed raising event when associated with Aggregate")


def test_event_definition_with_just_stream(test_domain):
    try:
        identifier = str(uuid4())
        test_domain.raise_(UserLoggedIn(user_id=identifier))
    except IncorrectUsageError:
        pytest.fail("Failed raising event when associated with Stream")


def test_that_abstract_events_can_be_defined_without_aggregate_or_stream(test_domain):
    class AbstractEvent(BaseEvent):
        foo = String()

    try:
        test_domain.register(AbstractEvent, abstract=True)
    except Exception:
        pytest.fail(
            "Abstract events should be definable without being associated with an aggregate or a stream"
        )


def test_that_part_of_is_resolved_correctly():
    assert UserLoggedIn.meta_.part_of == User


def test_aggregate_cluster_of_event():
    assert UserLoggedIn.meta_.aggregate_cluster == User


def test_no_aggregate_cluster_for_command_with_stream(test_domain):
    class EmailSent(BaseEvent):
        email = String()

    test_domain.register(EmailSent, stream_name="email")

    assert EmailSent.meta_.aggregate_cluster is None
