import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String
from protean.utils.eventing import Message


class User(BaseAggregate):
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=["ACTIVE", "ARCHIVED"])


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, fact_events=True)
    test_domain.init(traverse=False)


@pytest.fixture
def event(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    # Read event from event store
    event_messages = test_domain.event_store.store.read(f"test::user-fact-{user.id}")
    assert len(event_messages) == 1

    # Deserialize event
    event = Message.to_object(event_messages[0])

    return event


def test_generation_of_first_fact_event_on_persistence(event):
    assert event is not None
    assert event.__class__.__name__ == "UserFactEvent"
    assert event.name == "John Doe"
    assert event.email == "john.doe@example.com"


def test_fact_event_version_metadata(event):
    assert event._metadata.headers.id.endswith("-0.1")
    assert event._metadata.domain.sequence_id == "0.1"
    assert event._version == 0


def test_fact_event_version_metadata_after_second_edit(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    refreshed_user = test_domain.repository_for(User).get(user.id)
    refreshed_user.name = "Jane Doe"
    test_domain.repository_for(User).add(refreshed_user)

    # Read event from event store
    event_messages = test_domain.event_store.store.read(f"test::user-fact-{user.id}")
    assert len(event_messages) == 2

    # Deserialize event
    event = Message.to_object(event_messages[1])

    assert event._metadata.headers.id.endswith("-1.1")
    assert event._metadata.domain.sequence_id == "1.1"
    assert event._version == 1
