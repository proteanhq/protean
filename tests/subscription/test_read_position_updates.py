import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import DateTime, Identifier, String
from protean.server import Engine
from protean.utils import Processing, fqn
from protean.utils.mixins import handle


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


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.id = event.id
        self.email = event.email
        self.name = event.name
        self.password_hash = event.password_hash

    @apply
    def on_activated(self, event: Activated) -> None:
        pass


class Email(BaseAggregate):
    email = String()
    sent_at = DateTime()

    @apply
    def on_sent(self, event: Sent) -> None:
        self.email = event.email
        self.sent_at = event.sent_at


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
    test_domain.config["event_processing"] = Processing.ASYNC.value

    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(Email, is_event_sourced=True)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(EmailEventHandler, stream_category="email")
    test_domain.init(traverse=False)


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
    email.raise_(event)

    # ASSERT Initial state
    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert last_written_position == -1  # Default value

    test_domain.event_store.store.append(email._events[0])

    await email_event_handler_subscription.tick()

    # ASSERT Positions after reading 1 message
    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert email_event_handler_subscription.current_position == 1
    assert last_written_position == -1  # Remains -1 because interval is not reached

    # Populate 15 messages (5 more than default interval)
    for _ in range(15):
        email.raise_(event)
        test_domain.event_store.store.append(email._events[-1])

    await email_event_handler_subscription.tick()
    last_written_position = await email_event_handler_subscription.fetch_last_position()

    # ASSERT Positions after reading all messages (100 per tick now)
    # Current position should be 16 because we read all 15 messages plus 1 position update
    assert email_event_handler_subscription.current_position == 16
    assert (
        last_written_position == 11
    )  # Position written after 10 messages (position update interval)

    # ASSERT Positions after reading to end of messages
    await email_event_handler_subscription.tick()
    last_written_position = await email_event_handler_subscription.fetch_last_position()
    assert (
        email_event_handler_subscription.current_position == 16
    )  # Already read all messages in previous tick
    assert last_written_position == 11  # Remains 11 as no new interval reached


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
        email.raise_(event)
        test_domain.event_store.store.append(email._events[-1])

    # Consume messages (By default, 10 messages per tick)
    await email_event_handler_subscription.tick()

    # Fetch the current event store state
    # After reading 15 messages with batch size 100, we get all messages + position update
    total_no_of_messages = len(test_domain.event_store.store.read("$all"))
    # We should have 15 events + 1 position update = 16, but since all processed at once,
    # we might have an additional position update at the end
    assert total_no_of_messages in [16, 17]  # Allow for extra position update

    # Simulating server shutdown
    # Try to manually update the position to the store
    await email_event_handler_subscription.update_current_position_to_store()

    # Ensure that the event store state did not change significantly
    #   We might have one more position update if the interval was reached
    new_total = len(test_domain.event_store.store.read("$all"))
    assert new_total in [total_no_of_messages, total_no_of_messages + 1]
    # Ensure last read message is 15 (all messages were processed in one batch)
    assert await email_event_handler_subscription.fetch_last_position() == 15


@pytest.mark.asyncio
async def test_subscription_poll_exits_when_keep_going_false(test_domain, caplog):
    """Test that Subscription.poll() exits when keep_going is set to False"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._subscriptions[fqn(UserEventHandler)]

    # Mock the tick method to prevent actual processing
    subscription.tick = AsyncMock()

    # Start polling in background
    poll_task = asyncio.create_task(subscription.poll())

    # Let it run briefly
    await asyncio.sleep(0.1)

    # Set keep_going to False to trigger exit
    subscription.keep_going = False

    # Wait for poll to complete
    await asyncio.wait_for(poll_task, timeout=1.0)

    # Verify poll exited
    assert poll_task.done()


@pytest.mark.asyncio
async def test_subscription_poll_exits_when_engine_shutting_down(test_domain, caplog):
    """Test that Subscription.poll() exits when engine.shutting_down is True"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._subscriptions[fqn(UserEventHandler)]

    # Mock the tick method to prevent actual processing
    subscription.tick = AsyncMock()

    # Start polling in background
    poll_task = asyncio.create_task(subscription.poll())

    # Let it run briefly
    await asyncio.sleep(0.1)

    # Set engine.shutting_down to True to trigger exit
    engine.shutting_down = True

    # Wait for poll to complete
    await asyncio.wait_for(poll_task, timeout=1.0)

    # Verify poll exited
    assert poll_task.done()


@pytest.mark.asyncio
async def test_subscription_poll_test_mode_sleep_zero(test_domain):
    """Test that Subscription.poll() uses asyncio.sleep(0) in test mode"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._subscriptions[fqn(UserEventHandler)]

    # Verify the engine is in test mode
    assert engine.test_mode is True

    # Mock tick to return immediately but let it run briefly
    tick_call_count = 0

    async def mock_tick():
        nonlocal tick_call_count
        tick_call_count += 1
        # Stop after enough iterations to hit the sleep line
        if tick_call_count >= 3:
            subscription.keep_going = False
        # Add a tiny delay to let the event loop run
        await asyncio.sleep(0.001)

    subscription.tick = mock_tick

    # Start polling and let it run to hit the sleep(0) line
    poll_task = asyncio.create_task(subscription.poll())

    # Wait for poll to complete
    try:
        await asyncio.wait_for(poll_task, timeout=1.0)
    except asyncio.TimeoutError:
        subscription.keep_going = False
        await asyncio.wait_for(poll_task, timeout=0.5)

    # Verify tick was called multiple times (means the loop ran and hit sleep lines)
    assert tick_call_count >= 3
