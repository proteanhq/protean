from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import mock
import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()
    password_hash = String()


class Email(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
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


@pytest.mark.asyncio
async def test_message_filtering_for_event_handlers_with_defined_origin_stream(
    test_domain,
):
    test_domain.register(UserEventHandler, aggregate_cls=User)
    test_domain.register(EmailEventHandler, stream_name="email", source_stream="user")

    engine = Engine(test_domain, test_mode=True)
    email_event_handler_subscription = engine._subscriptions[fqn(EmailEventHandler)]

    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@gmail.com", name="John Doe")
    email = Email(id=identifier, email="john.doe@gmail.com")

    # Construct 3 dummy messages and modify Sent message to have originated from the user stream
    messages = [
        Message.to_aggregate_event_message(
            user, Registered(id=identifier, email="john.doe@gmail.com", name="John Doe")
        ),
        Message.to_aggregate_event_message(
            user, Activated(id=identifier, activated_at=datetime.utcnow())
        ),
        Message.to_aggregate_event_message(
            email, Sent(email="john.doe@gmail.com", sent_at=datetime.utcnow())
        ),
    ]
    messages[2].metadata.origin_stream_name = f"user-{identifier}"

    # Mock `read` method and have it return the 3 messages
    mock_store_read = mock.Mock()
    mock_store_read.return_value = messages
    email_event_handler_subscription.store.read = mock_store_read

    filtered_messages = (
        await email_event_handler_subscription.get_next_batch_of_messages()
    )

    assert len(filtered_messages) == 1
    assert filtered_messages[0].type == fqn(Sent)
