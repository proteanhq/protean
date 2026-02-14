import json

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils.reflection import id_field


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    email: String()
    name: String()


class Registered(BaseEvent):
    user_id: Identifier(identifier=True)
    email: String()
    name: String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


def test_that_events_are_immutable():
    event = Registered(email="john.doe@gmail.com", name="John Doe", user_id="1234")
    with pytest.raises(IncorrectUsageError):
        event.name = "Jane Doe"


def test_that_no_id_field_is_assigned_if_event_is_marked_as_abstract(test_domain):
    @test_domain.event(abstract=True)
    class AbstractEvent:
        foo: String(identifier=True)

    assert id_field(AbstractEvent) is None


def test_event_hash(test_domain):
    user = User(user_id="1234", name="John Doe", email="john.doe@gmail.com")
    user.raise_(Registered(email="john.doe@gmail.com", name="John Doe", user_id="1234"))

    event = user._events[0]
    payload_hash = hash(json.dumps(event.payload, sort_keys=True))
    assert hash(event) == payload_hash
