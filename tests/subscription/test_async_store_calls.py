"""Tests for Bucket E: Async/Sync Consistency in EventStoreSubscription.

Finding #13: write_position() and fetch_last_position() must not block the event loop.
Finding #14: get_next_batch_of_messages() must not block the event loop.

All three methods wrap their synchronous event store calls in asyncio.to_thread().
"""

import asyncio
import inspect
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import DateTime, String
from protean.server import Engine
from protean.utils import Processing, fqn
from protean.utils.mixins import handle


def dummy(*args):
    pass


class Sent(BaseEvent):
    email = String()
    sent_at = DateTime()


class Email(BaseAggregate):
    email = String()
    sent_at = DateTime()

    @apply
    def on_sent(self, event: Sent) -> None:
        self.email = event.email
        self.sent_at = event.sent_at


class EmailEventHandler(BaseEventHandler):
    @handle(Sent)
    def record_sent_email(self, event: Sent) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value

    test_domain.register(Email, is_event_sourced=True)
    test_domain.register(Sent, part_of=Email)
    test_domain.register(EmailEventHandler, stream_category="email")
    test_domain.init(traverse=False)


@pytest.fixture
def subscription(test_domain):
    engine = Engine(test_domain, test_mode=True)
    return engine._subscriptions[fqn(EmailEventHandler)]


# ---------------------------------------------------------------------------
# Finding #13: write_position() dispatches to thread
# ---------------------------------------------------------------------------
class TestWritePositionAsync:
    @pytest.mark.asyncio
    async def test_write_position_is_coroutine(self, subscription):
        """write_position() must be a coroutine (awaitable)."""
        assert inspect.iscoroutinefunction(subscription.write_position)

    @pytest.mark.asyncio
    async def test_write_position_uses_to_thread(self, subscription):
        """write_position() wraps store._write() in asyncio.to_thread()."""
        with patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
            await subscription.write_position(5)

        # Verify to_thread was called with store._write
        mock_to_thread.assert_called_once()
        args = mock_to_thread.call_args
        assert args[0][0] == subscription.store._write

    @pytest.mark.asyncio
    async def test_write_position_resets_counter(self, subscription):
        """write_position() resets messages_since_last_position_write."""
        subscription.messages_since_last_position_write = 15
        await subscription.write_position(10)
        assert subscription.messages_since_last_position_write == 0

    @pytest.mark.asyncio
    async def test_write_position_persists(self, subscription):
        """write_position() actually writes to the event store."""
        await subscription.write_position(42)
        position = await subscription.fetch_last_position()
        assert position == 42


# ---------------------------------------------------------------------------
# Finding #13: fetch_last_position() dispatches to thread
# ---------------------------------------------------------------------------
class TestFetchLastPositionAsync:
    @pytest.mark.asyncio
    async def test_fetch_last_position_is_coroutine(self, subscription):
        """fetch_last_position() must be a coroutine (awaitable)."""
        assert inspect.iscoroutinefunction(subscription.fetch_last_position)

    @pytest.mark.asyncio
    async def test_fetch_last_position_uses_to_thread(self, subscription):
        """fetch_last_position() wraps store._read_last_message() in asyncio.to_thread()."""
        with patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
            await subscription.fetch_last_position()

        mock_to_thread.assert_called_once()
        args = mock_to_thread.call_args
        assert args[0][0] == subscription.store._read_last_message

    @pytest.mark.asyncio
    async def test_fetch_last_position_returns_minus_one_initially(self, subscription):
        """With no prior writes, fetch_last_position() returns -1."""
        position = await subscription.fetch_last_position()
        assert position == -1

    @pytest.mark.asyncio
    async def test_fetch_last_position_returns_written_value(self, subscription):
        """After write_position(), fetch_last_position() returns the written value."""
        await subscription.write_position(99)
        position = await subscription.fetch_last_position()
        assert position == 99


# ---------------------------------------------------------------------------
# Finding #14: get_next_batch_of_messages() dispatches to thread
# ---------------------------------------------------------------------------
class TestGetNextBatchAsync:
    @pytest.mark.asyncio
    async def test_get_next_batch_is_coroutine(self, subscription):
        """get_next_batch_of_messages() must be a coroutine (awaitable)."""
        assert inspect.iscoroutinefunction(subscription.get_next_batch_of_messages)

    @pytest.mark.asyncio
    async def test_get_next_batch_uses_to_thread(self, subscription):
        """get_next_batch_of_messages() wraps store.read() in asyncio.to_thread()."""
        with patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
            await subscription.get_next_batch_of_messages()

        mock_to_thread.assert_called_once()
        args = mock_to_thread.call_args
        assert args[0][0] == subscription.store.read

    @pytest.mark.asyncio
    async def test_get_next_batch_returns_empty_when_no_messages(self, subscription):
        """With an empty store, get_next_batch_of_messages() returns an empty list."""
        messages = await subscription.get_next_batch_of_messages()
        assert messages == []

    @pytest.mark.asyncio
    async def test_get_next_batch_returns_messages(self, test_domain, subscription):
        """get_next_batch_of_messages() returns messages from the event store."""
        email = Email(
            id=str(uuid4()), email="test@example.com", sent_at=datetime.now(UTC)
        )
        event = Sent(email="test@example.com", sent_at=datetime.now(UTC))
        email.raise_(event)
        test_domain.event_store.store.append(email._events[0])

        messages = await subscription.get_next_batch_of_messages()
        assert len(messages) == 1


# ---------------------------------------------------------------------------
# Integration: concurrent tasks are not blocked
# ---------------------------------------------------------------------------
class TestConcurrentExecution:
    @pytest.mark.asyncio
    async def test_store_calls_do_not_block_event_loop(self, test_domain, subscription):
        """Verify that store calls yield control to other coroutines.

        We run a fetch + write alongside a fast coroutine and confirm
        both complete without the fast task starving.
        """
        fast_task_ran = False

        async def fast_task():
            nonlocal fast_task_ran
            fast_task_ran = True

        # Run both concurrently
        await asyncio.gather(
            subscription.fetch_last_position(),
            subscription.write_position(1),
            fast_task(),
        )

        assert fast_task_ran
