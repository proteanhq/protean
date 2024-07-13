from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import mock
import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.core.event import Metadata
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    email = String()
    name = String()
    password_hash = String()


class Email(BaseEventSourcedAggregate):
    email = String()
    sent_at = DateTime()


def dummy(*args):
    pass


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()


class Sent(BaseEvent):
    email = String()
    sent_at = DateTime()


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def send_activation_email(self, event: Registered) -> None:
        dummy(event)

    @handle(Activated)
    def provision_user(self, event: Activated) -> None:
        dummy(event)

    @handle(Activated)
    def send_welcome_email(self, event: Activated) -> None:
        dummy(event)


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, event: Sent) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(Email)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(EmailEventHandler, stream_name="email")
    test_domain.init(traverse=False)


@pytest.mark.asyncio
async def test_no_filtering_for_event_handlers_without_defined_origin_stream(
    test_domain,
):
    engine = Engine(test_domain, test_mode=True)
    email_event_handler_subscription = engine._subscriptions[fqn(EmailEventHandler)]

    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@gmail.com", name="John Doe")
    email = Email(id=identifier, email="john.doe@gmail.com")

    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))
    user.raise_(Activated(id=identifier, activated_at=datetime.now(UTC)))
    email.raise_(Sent(email="john.doe@gmail.com", sent_at=datetime.now(UTC)))
    # Construct 3 dummy messages and modify Sent message to have originated from the user stream
    messages = [
        Message.to_message(user._events[0]),
        Message.to_message(user._events[1]),
        Message.to_message(email._events[0]),
    ]

    messages[2].metadata = Metadata(
        messages[2].metadata.to_dict(), origin_stream_name=f"user-{identifier}"
    )  # Metadata is a VO and immutable, so creating a copy with updated value

    # Mock `read` method and have it return the 3 messages
    mock_store_read = mock.Mock()
    mock_store_read.return_value = messages
    email_event_handler_subscription.store.read = mock_store_read

    filtered_messages = (
        await email_event_handler_subscription.get_next_batch_of_messages()
    )

    assert len(filtered_messages) == 3
    assert filtered_messages[0].type == Registered.__type__
    assert filtered_messages[2].type == Sent.__type__
