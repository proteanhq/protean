from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import mock
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent, Metadata
from protean.core.event_handler import BaseEventHandler
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.mixins import handle


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()


class Email(BaseAggregate):
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
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)

    test_domain.register(Email, is_event_sourced=True)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(
        EmailEventHandler, stream_category="email", source_stream="user"
    )
    test_domain.init(traverse=False)


@pytest.mark.asyncio
async def test_message_filtering_for_event_handlers_with_defined_origin_stream(
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
        messages[2].metadata.to_dict(), origin_stream=f"user-{identifier}"
    )  # Metadata is a VO and immutable, so creating a copy with updated value

    # Mock `read` method and have it return the 3 messages
    mock_store_read = mock.Mock()
    mock_store_read.return_value = messages
    email_event_handler_subscription.store.read = mock_store_read

    filtered_messages = (
        await email_event_handler_subscription.get_next_batch_of_messages()
    )

    assert len(filtered_messages) == 1
    assert filtered_messages[0].headers.type == Sent.__type__
