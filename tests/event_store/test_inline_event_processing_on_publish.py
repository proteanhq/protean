"""
For tests related to inline processing of events raised in event-sourced aggregates,
check tests/unit_of_work/test_inline_event_processing.py
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventHandler, handle
from protean.fields import Identifier, String
from protean.globals import current_domain

counter = 0


def count_up():
    global counter
    counter += 1


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()

    class Meta:
        stream_name = "user"


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def registered(self, _: Registered) -> None:
        count_up()


@pytest.mark.eventstore
def test_inline_event_processing_on_publish_in_sync_mode(test_domain):
    test_domain.register(Registered)
    test_domain.register(UserEventHandler, stream_name="user")

    current_domain.publish(
        Registered(
            user_id=str(uuid4()),
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    global counter
    assert counter == 1
