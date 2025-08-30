import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.utils.eventing import Message


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class Renamed(BaseEvent):
    id = Identifier()
    name = String()


class User(BaseAggregate):
    email = String()
    name = String()

    @apply
    def registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name

    @apply
    def renamed(self, event: Renamed) -> None:
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True, fact_events=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


def test_event_sourced_aggregate_can_be_marked_for_fact_event_generation(test_domain):
    assert User.meta_.fact_events is True


def test_generation_of_first_fact_event_on_persistence(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    user.raise_(Registered(id=user.id, email=user.email, name=user.name))

    test_domain.repository_for(User).add(user)

    # Read event from event store
    event_messages = test_domain.event_store.store.read(f"test::user-{user.id}")
    assert len(event_messages) == 1

    # Read fact events from event store
    fact_event_messages = test_domain.event_store.store.read(
        f"test::user-fact-{user.id}"
    )
    assert len(fact_event_messages) == 1

    # Deserialize event
    event = Message.to_object(fact_event_messages[0])
    assert event is not None
    assert event.__class__.__name__ == "UserFactEvent"
    assert event.name == "John Doe"
    assert event.email == "john.doe@example.com"

    # Check event versions
    assert event._metadata.id.endswith("-0")
    assert event._metadata.sequence_id == "0"
    assert event._version == 0


def test_generation_of_subsequent_fact_events_after_fetch(test_domain):
    # Initialize and save
    user = User(name="John Doe", email="john.doe@example.com")
    user.raise_(Registered(id=user.id, email=user.email, name=user.name))

    # Persist the user
    test_domain.repository_for(User).add(user)

    # Fetch the aggregate
    refreshed_user = test_domain.repository_for(User).get(user.id)

    # Simulate a name update
    refreshed_user.name = "Jane Doe"
    refreshed_user.raise_(Renamed(id=refreshed_user.id, name="Jane Doe"))

    # Store the updated user
    test_domain.repository_for(User).add(refreshed_user)

    # Read event from event store
    event_messages = test_domain.event_store.store.read(f"test::user-{user.id}")
    assert len(event_messages) == 2

    # Read fact events from event store
    fact_event_messages = test_domain.event_store.store.read(
        f"test::user-fact-{user.id}"
    )
    assert len(fact_event_messages) == 2

    # Deserialize 1st event and verify
    event = Message.to_object(fact_event_messages[0])
    assert event is not None
    assert event.__class__.__name__ == "UserFactEvent"
    assert event.name == "John Doe"

    assert event._metadata.id.endswith("-0")
    assert event._metadata.sequence_id == "0"
    assert event._version == 0

    # Deserialize 2nd event and verify
    event = Message.to_object(fact_event_messages[1])
    assert event is not None
    assert event.__class__.__name__ == "UserFactEvent"
    assert event.name == "Jane Doe"

    assert event._metadata.id.endswith("-1")
    assert event._metadata.sequence_id == "1"
    assert event._version == 1
