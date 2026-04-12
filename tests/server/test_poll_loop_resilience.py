"""Tests that subscription poll loops survive errors without crashing the engine.

The poll loop in BaseSubscription.poll() must catch exceptions from tick()
(including get_next_batch_of_messages()) so that transient failures — such as
database connection errors or deserialization issues — don't escape the asyncio
task and trigger the engine's event loop exception handler, which would shut
down the entire engine.

All four subscription types are covered:
- BaseSubscription (used by BrokerSubscription and OutboxProcessor)
- StreamSubscription (own poll() override with priority lanes)
- EventStoreSubscription (own poll() override with recovery passes)
"""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean import apply
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription import BaseSubscription
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.utils import Processing
from protean.utils.mixins import handle


logger = logging.getLogger(__name__)


# ---------- Domain elements for engine setup ----------


class Registered(BaseEvent):
    id: Identifier()
    email: String()
    name: String()


class User(BaseAggregate):
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def process_registered(self, event):
        pass


@pytest.fixture
def domain_setup(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)
    return test_domain


# ---------- Tests ----------


class TestBaseSubscriptionPollResilience:
    """Test that BaseSubscription.poll() catches errors and continues."""

    @pytest.mark.asyncio
    async def test_poll_survives_tick_exception(self, domain_setup, caplog):
        """An exception in tick() should be caught and logged, not crash the loop."""
        engine = Engine(domain=domain_setup, test_mode=True)

        # Create a concrete subscription that raises on tick
        class FailingSubscription(BaseSubscription):
            def __init__(self, engine):
                super().__init__(engine, messages_per_tick=10, tick_interval=0)
                self.subscriber_name = "test-failing-subscription"
                self.tick_count = 0

            async def get_next_batch_of_messages(self):
                return []

            async def process_batch(self, messages):
                return 0

            async def tick(self):
                self.tick_count += 1
                if self.tick_count <= 2:
                    raise RuntimeError("Simulated database connection error")
                # After 2 failures, signal to stop
                self.keep_going = False

        sub = FailingSubscription(engine)

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        # Verify: poll completed without raising, tick ran 3 times
        assert sub.tick_count == 3
        assert not engine.shutting_down
        assert "Simulated database connection error" in caplog.text
        assert "subscription.error" in caplog.text
        # Verify attempt counter is tracked via LogRecord extra attributes
        error_records = [
            r for r in caplog.records if "subscription.error" in r.getMessage()
        ]
        assert len(error_records) >= 2
        assert error_records[0].attempt == 1
        assert error_records[1].attempt == 2

    @pytest.mark.asyncio
    async def test_poll_survives_get_next_batch_exception(self, domain_setup, caplog):
        """An exception in get_next_batch_of_messages() propagates through
        tick() and should be caught by poll()."""
        engine = Engine(domain=domain_setup, test_mode=True)

        class FailingFetchSubscription(BaseSubscription):
            def __init__(self, engine):
                super().__init__(engine, messages_per_tick=10, tick_interval=0)
                self.subscriber_name = "test-failing-fetch"
                self.fetch_count = 0

            async def get_next_batch_of_messages(self):
                self.fetch_count += 1
                if self.fetch_count == 1:
                    # Simulate Pydantic ValidationError during deserialization
                    raise ValueError(
                        "1 validation error for Outbox\nid\n  "
                        "Input should be a valid string [type=string_type]"
                    )
                self.keep_going = False
                return []

            async def process_batch(self, messages):
                return 0

        sub = FailingFetchSubscription(engine)

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        assert sub.fetch_count == 2
        assert not engine.shutting_down
        assert "validation error" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_poll_applies_exponential_backoff(self, domain_setup):
        """Consecutive errors should increase the backoff delay."""
        engine = Engine(domain=domain_setup, test_mode=True)

        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            # Don't actually sleep — just record the duration
            await original_sleep(0)

        class RepeatedFailureSubscription(BaseSubscription):
            def __init__(self, engine):
                super().__init__(engine, messages_per_tick=10, tick_interval=0)
                self.subscriber_name = "test-backoff"
                self.tick_count = 0

            async def get_next_batch_of_messages(self):
                return []

            async def process_batch(self, messages):
                return 0

            async def tick(self):
                self.tick_count += 1
                if self.tick_count <= 4:
                    raise RuntimeError("persistent error")
                self.keep_going = False

        sub = RepeatedFailureSubscription(engine)

        with patch("protean.server.subscription.asyncio.sleep", side_effect=mock_sleep):
            await sub.poll()

        assert sub.tick_count == 5
        # Backoff sequence: 1s, 2s, 4s, 8s (2^0, 2^1, 2^2, 2^3)
        assert sleep_durations[0] == 1
        assert sleep_durations[1] == 2
        assert sleep_durations[2] == 4
        assert sleep_durations[3] == 8

    @pytest.mark.asyncio
    async def test_poll_resets_backoff_on_success(self, domain_setup):
        """A successful tick should reset the consecutive error counter."""
        engine = Engine(domain=domain_setup, test_mode=True)

        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)

        class IntermittentFailureSubscription(BaseSubscription):
            def __init__(self, engine):
                super().__init__(engine, messages_per_tick=10, tick_interval=0)
                self.subscriber_name = "test-reset-backoff"
                self.tick_count = 0

            async def get_next_batch_of_messages(self):
                return []

            async def process_batch(self, messages):
                return 0

            async def tick(self):
                self.tick_count += 1
                # Fail on ticks 1-2, succeed on 3, fail on 4, stop on 5
                if self.tick_count in (1, 2):
                    raise RuntimeError("transient error")
                elif self.tick_count == 4:
                    raise RuntimeError("another transient error")
                elif self.tick_count >= 5:
                    self.keep_going = False

        sub = IntermittentFailureSubscription(engine)

        with patch("protean.server.subscription.asyncio.sleep", side_effect=mock_sleep):
            await sub.poll()

        assert sub.tick_count == 5
        # First two failures: backoff 1s, 2s
        # Then success resets counter
        # Third failure: backoff resets to 1s (not 4s)
        error_sleeps = [d for d in sleep_durations if d >= 1]
        assert error_sleeps == [1, 2, 1]

    @pytest.mark.asyncio
    async def test_poll_backoff_capped_at_30_seconds(self, domain_setup):
        """Backoff should not exceed 30 seconds."""
        engine = Engine(domain=domain_setup, test_mode=True)

        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)

        class PersistentFailureSubscription(BaseSubscription):
            def __init__(self, engine):
                super().__init__(engine, messages_per_tick=10, tick_interval=0)
                self.subscriber_name = "test-max-backoff"
                self.tick_count = 0

            async def get_next_batch_of_messages(self):
                return []

            async def process_batch(self, messages):
                return 0

            async def tick(self):
                self.tick_count += 1
                if self.tick_count <= 7:
                    raise RuntimeError("persistent error")
                self.keep_going = False

        sub = PersistentFailureSubscription(engine)

        with patch("protean.server.subscription.asyncio.sleep", side_effect=mock_sleep):
            await sub.poll()

        # Backoff: 1, 2, 4, 8, 16, 30, 30 (capped)
        assert sleep_durations[4] == 16
        assert sleep_durations[5] == 30
        assert sleep_durations[6] == 30

    @pytest.mark.asyncio
    async def test_poll_handles_cancelled_error(self, domain_setup):
        """CancelledError should break the loop cleanly."""
        engine = Engine(domain=domain_setup, test_mode=True)

        class CancelledSubscription(BaseSubscription):
            def __init__(self, engine):
                super().__init__(engine, messages_per_tick=10, tick_interval=0)
                self.subscriber_name = "test-cancelled"

            async def get_next_batch_of_messages(self):
                return []

            async def process_batch(self, messages):
                return 0

            async def tick(self):
                raise asyncio.CancelledError()

        sub = CancelledSubscription(engine)
        # Should not raise — CancelledError is caught and breaks the loop
        await sub.poll()
        assert not engine.shutting_down


# ---------- Helpers for StreamSubscription tests ----------


class FakeBroker:
    """Minimal broker stub for StreamSubscription tests."""

    def __init__(self):
        self.acked: list[tuple] = []
        self.nacked: list[tuple] = []
        self.published: list[tuple] = []

    def _ensure_group(self, consumer_group, stream):
        pass

    def ack(self, stream, identifier, consumer_group):
        self.acked.append((stream, identifier, consumer_group))
        return True

    def nack(self, stream, identifier, consumer_group):
        self.nacked.append((stream, identifier, consumer_group))
        return True

    def publish(self, stream, message):
        self.published.append((stream, message))
        return "dlq-id"


def _make_stream_subscription(domain_setup) -> StreamSubscription:
    """Create a StreamSubscription with a FakeBroker for testing poll()."""
    engine = Engine(domain_setup, test_mode=True)
    sub = StreamSubscription(
        engine=engine,
        stream_category="test_stream",
        handler=UserEventHandler,
    )
    sub.broker = FakeBroker()
    return sub


class TestStreamSubscriptionPollResilience:
    """Test that StreamSubscription.poll() catches errors and continues.

    StreamSubscription overrides poll() with its own implementation that
    includes priority lanes logic. It must have the same resilience as
    BaseSubscription.poll().
    """

    @pytest.mark.asyncio
    async def test_poll_survives_get_next_batch_exception(self, domain_setup, caplog):
        """Exception in get_next_batch_of_messages should not crash the loop."""
        sub = _make_stream_subscription(domain_setup)
        call_count = 0

        async def failing_get_next_batch():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis connection lost")
            sub.keep_going = False
            return []

        sub.get_next_batch_of_messages = failing_get_next_batch

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        assert call_count == 2
        assert not sub.engine.shutting_down
        assert "Redis connection lost" in caplog.text

    @pytest.mark.asyncio
    async def test_poll_survives_process_batch_exception(self, domain_setup, caplog):
        """Exception in process_batch should not crash the loop."""
        sub = _make_stream_subscription(domain_setup)
        call_count = 0

        async def get_one_message():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [("msg-1", {"data": "test"})]
            sub.keep_going = False
            return []

        async def failing_process_batch(messages, stream=None):
            raise RuntimeError("Handler exploded")

        sub.get_next_batch_of_messages = get_one_message
        sub.process_batch = failing_process_batch

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        assert call_count == 2
        assert not sub.engine.shutting_down
        assert "Handler exploded" in caplog.text

    @pytest.mark.asyncio
    async def test_poll_applies_exponential_backoff(self, domain_setup):
        """Consecutive errors should increase backoff: 1s, 2s, 4s, ... capped at 30s."""
        sub = _make_stream_subscription(domain_setup)
        call_count = 0
        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)

        async def failing_get_next_batch():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise RuntimeError("persistent error")
            sub.keep_going = False
            return []

        sub.get_next_batch_of_messages = failing_get_next_batch

        with patch(
            "protean.server.subscription.stream_subscription.asyncio.sleep",
            side_effect=mock_sleep,
        ):
            await sub.poll()

        # 3 errors → backoff sleeps of 1, 2, 4
        error_sleeps = [d for d in sleep_durations if d >= 1]
        assert error_sleeps == [1, 2, 4]

    @pytest.mark.asyncio
    async def test_poll_resets_backoff_on_success(self, domain_setup):
        """A successful tick should reset the consecutive error counter."""
        sub = _make_stream_subscription(domain_setup)
        call_count = 0
        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)

        async def intermittent_get_next_batch():
            nonlocal call_count
            call_count += 1
            # Fail on 1-2, succeed on 3, fail on 4, stop on 5
            if call_count in (1, 2):
                raise RuntimeError("transient error")
            elif call_count == 4:
                raise RuntimeError("another transient error")
            elif call_count >= 5:
                sub.keep_going = False
            return []

        sub.get_next_batch_of_messages = intermittent_get_next_batch

        with patch(
            "protean.server.subscription.stream_subscription.asyncio.sleep",
            side_effect=mock_sleep,
        ):
            await sub.poll()

        # First two failures: 1s, 2s. Success resets. Third failure: 1s (not 4s).
        error_sleeps = [d for d in sleep_durations if d >= 1]
        assert error_sleeps == [1, 2, 1]

    @pytest.mark.asyncio
    async def test_poll_handles_cancelled_error(self, domain_setup):
        """CancelledError should break the loop cleanly."""
        sub = _make_stream_subscription(domain_setup)

        async def cancel_get_next_batch():
            raise asyncio.CancelledError()

        sub.get_next_batch_of_messages = cancel_get_next_batch
        await sub.poll()
        assert not sub.engine.shutting_down

    @pytest.mark.asyncio
    async def test_poll_survives_error_in_lanes_mode(self, domain_setup, caplog):
        """Error in priority lanes mode should not crash the loop."""
        sub = _make_stream_subscription(domain_setup)
        sub._lanes_enabled = True
        call_count = 0

        async def failing_read_primary():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis connection lost in lanes mode")
            sub.keep_going = False
            return []

        sub._read_primary_nonblocking = failing_read_primary

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        assert call_count == 2
        assert not sub.engine.shutting_down
        assert "Redis connection lost in lanes mode" in caplog.text


class TestEventStoreSubscriptionPollResilience:
    """Test that EventStoreSubscription.poll() catches errors and continues.

    EventStoreSubscription overrides poll() to add periodic recovery passes.
    It must have the same resilience as BaseSubscription.poll().
    """

    @pytest.mark.asyncio
    async def test_poll_survives_tick_exception(self, domain_setup, caplog):
        """Exception in tick() should not crash the loop."""
        engine = Engine(domain=domain_setup, test_mode=True)
        sub = EventStoreSubscription(
            engine=engine,
            stream_category="user",
            handler=UserEventHandler,
            tick_interval=0,
        )
        call_count = 0

        async def failing_tick():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Event store connection lost")
            sub.keep_going = False

        sub.tick = failing_tick
        sub.maybe_run_recovery = AsyncMock()

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        assert call_count == 2
        assert not engine.shutting_down
        assert "Event store connection lost" in caplog.text

    @pytest.mark.asyncio
    async def test_poll_survives_recovery_exception(self, domain_setup, caplog):
        """Exception in maybe_run_recovery() should not crash the loop."""
        engine = Engine(domain=domain_setup, test_mode=True)
        sub = EventStoreSubscription(
            engine=engine,
            stream_category="user",
            handler=UserEventHandler,
            tick_interval=0,
        )
        call_count = 0

        async def noop_tick():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                sub.keep_going = False

        async def failing_recovery():
            if call_count == 1:
                raise RuntimeError("Recovery query failed")

        sub.tick = noop_tick
        sub.maybe_run_recovery = failing_recovery

        with caplog.at_level(logging.ERROR):
            await sub.poll()

        assert call_count == 2
        assert not engine.shutting_down
        assert "Recovery query failed" in caplog.text

    @pytest.mark.asyncio
    async def test_poll_applies_exponential_backoff(self, domain_setup):
        """Consecutive errors should increase backoff."""
        engine = Engine(domain=domain_setup, test_mode=True)
        sub = EventStoreSubscription(
            engine=engine,
            stream_category="user",
            handler=UserEventHandler,
            tick_interval=0,
        )
        call_count = 0
        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)

        async def failing_tick():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise RuntimeError("persistent error")
            sub.keep_going = False

        sub.tick = failing_tick
        sub.maybe_run_recovery = AsyncMock()

        with patch(
            "protean.server.subscription.event_store_subscription.asyncio.sleep",
            side_effect=mock_sleep,
        ):
            await sub.poll()

        error_sleeps = [d for d in sleep_durations if d >= 1]
        assert error_sleeps == [1, 2, 4]

    @pytest.mark.asyncio
    async def test_poll_resets_backoff_on_success(self, domain_setup):
        """A successful tick should reset the consecutive error counter."""
        engine = Engine(domain=domain_setup, test_mode=True)
        sub = EventStoreSubscription(
            engine=engine,
            stream_category="user",
            handler=UserEventHandler,
            tick_interval=0,
        )
        call_count = 0
        sleep_durations: list[float] = []
        original_sleep = asyncio.sleep

        async def mock_sleep(duration):
            sleep_durations.append(duration)
            await original_sleep(0)

        async def intermittent_tick():
            nonlocal call_count
            call_count += 1
            if call_count in (1, 2):
                raise RuntimeError("transient error")
            elif call_count == 4:
                raise RuntimeError("another transient error")
            elif call_count >= 5:
                sub.keep_going = False

        sub.tick = intermittent_tick
        sub.maybe_run_recovery = AsyncMock()

        with patch(
            "protean.server.subscription.event_store_subscription.asyncio.sleep",
            side_effect=mock_sleep,
        ):
            await sub.poll()

        error_sleeps = [d for d in sleep_durations if d >= 1]
        assert error_sleeps == [1, 2, 1]

    @pytest.mark.asyncio
    async def test_poll_handles_cancelled_error(self, domain_setup):
        """CancelledError should break the loop cleanly."""
        engine = Engine(domain=domain_setup, test_mode=True)
        sub = EventStoreSubscription(
            engine=engine,
            stream_category="user",
            handler=UserEventHandler,
            tick_interval=0,
        )

        async def cancel_tick():
            raise asyncio.CancelledError()

        sub.tick = cancel_tick
        sub.maybe_run_recovery = AsyncMock()

        await sub.poll()
        assert not engine.shutting_down
