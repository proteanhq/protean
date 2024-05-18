from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventHandler, BaseEventSourcedAggregate, handle
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import fqn


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

    class Meta:
        part_of = User


class Activated(BaseEvent):
    id = Identifier()
    activated_at = DateTime()

    class Meta:
        part_of = User


class Sent(BaseEvent):
    email = String()
    sent_at = DateTime()

    class Meta:
        stream_name = "email"


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
    test_domain.register(Email)
    test_domain.register(Registered)
    test_domain.register(Activated)
    test_domain.register(Sent)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(EmailEventHandler, stream_name="email")


@pytest.mark.asyncio
async def test_initial_read_position(test_domain):
    engine = Engine(test_domain, test_mode=True)
    email_event_handler_subscription = engine._subscriptions[fqn(EmailEventHandler)]

    assert email_event_handler_subscription.current_position == -1

    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert last_written_position == -1


@pytest.mark.asyncio
async def test_write_position_after_interval(test_domain):
    engine = Engine(test_domain, test_mode=True)
    email_event_handler_subscription = engine._subscriptions[fqn(EmailEventHandler)]

    await email_event_handler_subscription.load_position_on_start()
    await email_event_handler_subscription.update_current_position_to_store()

    email_address = "john.doe@gmail.com"
    sent_at = datetime.now(UTC)
    email = Email(id=str(uuid4()), email=email_address, sent_at=sent_at)
    event = Sent(email=email_address, sent_at=sent_at)

    # ASSERT Initial state
    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert last_written_position == -1  # Default value

    test_domain.event_store.store.append_aggregate_event(email, event)

    await email_event_handler_subscription.tick()

    # ASSERT Positions after reading 1 message
    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert email_event_handler_subscription.current_position == 1
    assert last_written_position == -1  # Remains -1 because interval is not reached

    # Populate 15 messages (5 more than default interval)
    for _ in range(15):
        test_domain.event_store.store.append_aggregate_event(email, event)

    await email_event_handler_subscription.tick()
    last_written_position = await email_event_handler_subscription.fetch_last_position()

    # ASSERT Positions after reading 10 messages
    # Current position should be 12 because even though read 10 messages
    #   there is a position update message in the middle
    assert email_event_handler_subscription.current_position == 12
    assert last_written_position == 11  # We just completed reading 10 messages

    # ASSERT Positions after reading to end of messages
    await email_event_handler_subscription.tick()
    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert (
        email_event_handler_subscription.current_position == 16
    )  # Continued reading until end
    assert last_written_position == 11  # Remains 11 because interval is not reached


@pytest.mark.asyncio
async def test_that_positions_are_not_written_when_already_in_sync(test_domain):
    engine = Engine(test_domain, test_mode=True)
    email_event_handler_subscription = engine._subscriptions[fqn(EmailEventHandler)]

    await email_event_handler_subscription.load_position_on_start()

    email_address = "john.doe@gmail.com"
    sent_at = datetime.now(UTC)
    email = Email(id=str(uuid4()), email=email_address, sent_at=sent_at)
    event = Sent(email=email_address, sent_at=sent_at)

    # Populate 15 messages (5 more than default interval)
    for _ in range(15):
        test_domain.event_store.store.append_aggregate_event(email, event)

    # Consume messages (By default, 10 messages per tick)
    await email_event_handler_subscription.tick()

    # Fetch the current event store state
    # total_no_of_messages should be 16, including the position update message
    total_no_of_messages = len(test_domain.event_store.store.read("$all"))
    assert total_no_of_messages == 16

    # Simulating server shutdown
    # Try to manually update the position to the store
    await email_event_handler_subscription.update_current_position_to_store()

    # Ensure that the event store state did not change
    #   This means that we did not add duplicate position update messages
    assert len(test_domain.event_store.store.read("$all")) == total_no_of_messages
    # Ensure last read message remains at 10
    assert await email_event_handler_subscription.fetch_last_position() == 10
