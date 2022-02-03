from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.core.event_sourced_aggregate import apply
from protean.fields import String
from protean.fields.basic import Identifier


class Registered(BaseEvent):
    id = Identifier()
    name = String()
    email = String()


class Activated(BaseEvent):
    id = Identifier()


class Renamed(BaseEvent):
    id = Identifier()
    name = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    status = String(default="INACTIVE")

    @apply(Registered)
    def registered(self, _: Registered) -> None:
        self.status = "INACTIVE"

    @apply(Activated)
    def activated(self, _: Activated) -> None:
        self.status = "ACTIVE"

    @apply(Renamed)
    def renamed(self, event: Renamed) -> None:
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)


@pytest.mark.eventstore
def test_appending_messages_to_aggregate(test_domain):
    identifier = str(uuid4())
    event = Registered(id=identifier, email="john.doe@example.com")
    user = User(id=identifier, email="john.doe@example.com")
    test_domain.event_store.store.append_aggregate_event(user, event)

    messages = test_domain.event_store.store._read("user")

    assert len(messages) == 1


@pytest.mark.eventstore
def test_version_increment_on_new_event(test_domain):
    identifier = str(uuid4())
    event1 = Registered(id=identifier, email="john.doe@example.com")

    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    events = test_domain.event_store.store._read(f"user-{identifier}")
    assert events[0]["position"] == 0

    event2 = Activated(id=identifier)
    test_domain.event_store.store.append_aggregate_event(user, event2)

    events = test_domain.event_store.store._read(f"user-{identifier}")
    assert events[-1]["position"] == 1

    event3 = Renamed(id=identifier, name="Jane Doe")
    test_domain.event_store.store.append_aggregate_event(user, event3)

    events = test_domain.event_store.store._read(f"user-{identifier}")
    assert events[-1]["position"] == 2
