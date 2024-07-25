"""
For tests related to inline processing of events raised in event-sourced aggregates,
check tests/unit_of_work/test_inline_event_processing.py
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

counter = 0


def count_up():
    global counter
    counter += 1


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def registered(self, _: Registered) -> None:
        count_up()


@pytest.mark.eventstore
def test_inline_event_processing_on_publish_in_sync_mode(test_domain):
    test_domain.register(User, is_event_sourced=True, stream_category="user")
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, stream_category="test::user")
    test_domain.init(traverse=False)

    user = User(
        user_id=str(uuid4()),
        email="john.doe@example.com",
        name="John Doe",
        password_hash="hash",
    )
    user.raise_(
        Registered(
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            password_hash=user.password_hash,
        )
    )
    current_domain.publish(user._events[0])

    global counter
    assert counter == 1
