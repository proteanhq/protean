from datetime import UTC, datetime
from uuid import uuid4

import mock
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent, Metadata
from protean.core.event_handler import BaseEventHandler

from protean.server import Engine
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.mixins import handle


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class Email(BaseAggregate):
    email: str | None = None
    sent_at: datetime | None = None


def dummy(*args):
    pass


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class Activated(BaseEvent):
    id: str | None = None
    activated_at: datetime | None = None


class Sent(BaseEvent):
    email: str | None = None
    sent_at: datetime | None = None


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
    test_domain.register(EmailEventHandler, stream_category="email")
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
        Message.from_domain_object(user._events[0]),
        Message.from_domain_object(user._events[1]),
        Message.from_domain_object(email._events[0]),
    ]

    # Create a new Metadata with updated origin_stream in domain metadata
    from protean.utils.eventing import DomainMeta

    messages[2].metadata = Metadata(
        headers=messages[2].metadata.headers,
        envelope=messages[2].metadata.envelope,
        domain=DomainMeta(
            fqn=messages[2].metadata.domain.fqn,
            kind=messages[2].metadata.domain.kind,
            origin_stream=f"user-{identifier}",
            version=messages[2].metadata.domain.version,
            sequence_id=messages[2].metadata.domain.sequence_id,
            asynchronous=messages[2].metadata.domain.asynchronous,
        ),
    )

    # Mock `read` method and have it return the 3 messages
    mock_store_read = mock.Mock()
    mock_store_read.return_value = messages
    email_event_handler_subscription.store.read = mock_store_read

    filtered_messages = (
        await email_event_handler_subscription.get_next_batch_of_messages()
    )

    assert len(filtered_messages) == 3
    assert filtered_messages[0].metadata.headers.type == Registered.__type__
    assert filtered_messages[2].metadata.headers.type == Sent.__type__
