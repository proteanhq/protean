import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Identifier, String


class User(BaseAggregate):
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=["ACTIVE", "ARCHIVED"])


class Member(BaseAggregate):
    name: String(max_length=50, required=True)


class MemberJoined(BaseEvent):
    member_id: Identifier(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, fact_events=True)
    test_domain.register(Member, fact_events=True)
    test_domain.register(MemberJoined, part_of=Member)
    test_domain.init(traverse=False)


@pytest.fixture
def event(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    # Read event from event store
    event_messages = test_domain.event_store.store.read(f"test::user-fact-{user.id}")
    assert len(event_messages) == 1

    # Deserialize event
    event = event_messages[0].to_domain_object()

    return event


def test_generation_of_first_fact_event_on_persistence(event):
    assert event is not None
    assert event.__class__.__name__ == "UserFactEvent"
    assert event.name == "John Doe"
    assert event.email == "john.doe@example.com"


def test_fact_event_version_metadata(event):
    assert event._metadata.headers.id.endswith("-0.1")
    assert event._metadata.domain.sequence_id == "0.1"


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
    event = event_messages[1].to_domain_object()

    assert event._metadata.headers.id.endswith("-1.1")
    assert event._metadata.domain.sequence_id == "1.1"


def test_fact_events_on_same_instance_carry_the_saved_version(test_domain):
    repo = test_domain.repository_for(User)
    user = User(name="John Doe", email="john.doe@example.com")
    repo.add(user)

    user.name = "Jane Doe"
    repo.add(user)

    event_messages = test_domain.event_store.store.read(f"test::user-fact-{user.id}")
    assert len(event_messages) == 2

    events = [message.to_domain_object() for message in event_messages]
    assert [event._metadata.domain.sequence_id for event in events] == ["0.1", "1.1"]
    assert events[0]._metadata.headers.id.endswith("-0.1")
    assert events[1]._metadata.headers.id.endswith("-1.1")
    assert events[1].name == "Jane Doe"


def test_fact_event_follows_a_regular_event_raised_in_the_same_save(test_domain):
    member = Member(name="John Doe")
    member.raise_(MemberJoined(member_id=member.id))
    test_domain.repository_for(Member).add(member)

    own = test_domain.event_store.store.read(f"test::member-{member.id}")
    fact = test_domain.event_store.store.read(f"test::member-fact-{member.id}")
    assert len(own) == 1
    assert len(fact) == 1

    assert own[0].to_domain_object()._metadata.headers.id == (
        f"test::member-{member.id}-0.1"
    )
    assert fact[0].to_domain_object()._metadata.headers.id == (
        f"test::member-fact-{member.id}-0.2"
    )
