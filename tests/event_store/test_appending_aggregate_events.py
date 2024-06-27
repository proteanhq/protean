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
    email = String()
    name = String()
    status = String(default="INACTIVE")

    @classmethod
    def register(cls, id, email, name):
        user = User(id=id, email=email, name=name)
        user.raise_(Registered(id=id, email=email, name=name))

        return user

    def activate(self):
        self.raise_(Activated(id=self.id))

    def rename(self, name):
        self.name = name
        self.raise_(Renamed(id=self.id, name=name))

    @apply
    def registered(self, _: Registered) -> None:
        self.status = "INACTIVE"

    @apply
    def activated(self, _: Activated) -> None:
        self.status = "ACTIVE"

    @apply
    def renamed(self, event: Renamed) -> None:
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_appending_messages_to_aggregate(test_domain):
    identifier = str(uuid4())
    user = User.register(id=identifier, email="john.doe@example.com", name="John Doe")
    test_domain.event_store.store.append_aggregate_event(user, user._events[0])

    messages = test_domain.event_store.store._read("user")

    assert len(messages) == 1


@pytest.mark.eventstore
def test_version_increment_on_new_event(test_domain):
    identifier = str(uuid4())
    user = User.register(id=identifier, email="john.doe@example.com", name="John Doe")
    test_domain.event_store.store.append_aggregate_event(user, user._events[0])

    events = test_domain.event_store.store._read(f"user-{identifier}")
    assert events[0]["position"] == 0

    user.activate()
    test_domain.event_store.store.append_aggregate_event(user, user._events[1])

    events = test_domain.event_store.store._read(f"user-{identifier}")
    assert events[-1]["position"] == 1

    user.rename(name="John Doe 2")
    test_domain.event_store.store.append_aggregate_event(user, user._events[2])

    events = test_domain.event_store.store._read(f"user-{identifier}")
    assert events[-1]["position"] == 2
