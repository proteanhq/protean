import pytest

from protean import BaseAggregate, BaseEntity
from protean.fields import HasOne, String
from protean.utils.mixins import Message


class Account(BaseEntity):
    password_hash = String(max_length=512)


class User(BaseAggregate):
    name = String(max_length=50, required=True)
    email = String(required=True)
    status = String(choices=["ACTIVE", "ARCHIVED"])

    account = HasOne(Account)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, fact_events=True)
    test_domain.register(Account, part_of=User)
    test_domain.init(traverse=False)


def test_generation_of_first_fact_event_on_persistence(test_domain):
    user = User(name="John Doe", email="john.doe@example.com")
    test_domain.repository_for(User).add(user)

    # Read event from event store
    event_messages = test_domain.event_store.store.read(f"user-{user.id}")
    assert len(event_messages) == 1

    # Deserialize event
    event = Message.to_object(event_messages[0])
    assert event is not None
    assert event.__class__.__name__ == "UserFactEvent"
    assert event.name == "John Doe"
    assert event.email == "john.doe@example.com"
