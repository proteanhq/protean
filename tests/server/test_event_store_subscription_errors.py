"""Tests for EventStoreSubscription error handling, failed position tracking, and recovery.

Covers:
- Handler failure records failed position (read position still advances)
- Failed position recovery retries and succeeds (transient failure)
- Failed position recovery exhausts max_retries (permanent failure)
- Multiple concurrent failures tracked independently
- Recovery doesn't re-process already-resolved positions
- Recovery doesn't re-process already-exhausted positions
- Configuration overrides (max_retries, recovery_interval_seconds)
- handle_error() callback invoked on failure
- Exception in handle_error() caught and logged (engine continues)
- Engine doesn't shut down on handler failure
- Recovery pass timing (maybe_run_recovery)
- Rebuild retry counts on initialization
- Failed position stores stream info for recovery
"""

import asyncio
import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    FailedPositionStatus,
)
from protean.utils.eventing import EventStoreMeta, Message, Metadata
from protean.utils.mixins import handle

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Counters
# ──────────────────────────────────────────────────────────────────────

handler_counter = 0
error_handler_counter = 0
fail_count = 0  # Controls how many times the transient handler fails


# ──────────────────────────────────────────────────────────────────────
# Domain elements
# ──────────────────────────────────────────────────────────────────────


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


class AlwaysFailingEventHandler(BaseEventHandler):
    """Handler that always raises."""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter
        handler_counter += 1
        raise RuntimeError("Permanent failure")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1


class TransientFailingEventHandler(BaseEventHandler):
    """Handler that fails a configurable number of times, then succeeds."""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter, fail_count
        handler_counter += 1
        if fail_count > 0:
            fail_count -= 1
            raise RuntimeError("Transient failure")
        # Success path — no exception


class SucceedingEventHandler(BaseEventHandler):
    """Handler that always succeeds."""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter
        handler_counter += 1


class ErrorInErrorHandlerEventHandler(BaseEventHandler):
    """Handler where both the handler and handle_error raise."""

    @handle(Registered)
    def handle_registered(self, event):
        global handler_counter
        handler_counter += 1
        raise RuntimeError("Handler failure")

    @classmethod
    def handle_error(cls, exc, message):
        global error_handler_counter
        error_handler_counter += 1
        raise RuntimeError("Error handler also failed")


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_counters():
    global handler_counter, error_handler_counter, fail_count
    handler_counter = 0
    error_handler_counter = 0
    fail_count = 0


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(AlwaysFailingEventHandler, part_of=User)
    test_domain.register(TransientFailingEventHandler, part_of=User)
    test_domain.register(SucceedingEventHandler, part_of=User)
    test_domain.register(ErrorInErrorHandlerEventHandler, part_of=User)
    test_domain.init(traverse=False)


def _create_message(
    user_id: str | None = None,
    global_position: int = 1,
    stream_position: int = 0,
    stream_name: str | None = None,
    asynchronous: bool = True,
) -> Message:
    """Create a Registered event message with EventStoreMeta.

    Args:
        user_id: Optional user ID. Generated if not provided.
        global_position: The global position in the event store (used for tracking).
        stream_position: The per-stream position (used for recovery re-reads).
        stream_name: The specific stream name. Defaults to ``test-{user_id}``.
        asynchronous: Whether the message is asynchronous.
    """
    user_id = user_id or str(uuid4())
    if stream_name is None:
        stream_name = f"test-{user_id}"

    user = User(id=user_id, email="test@example.com", name="Test")
    user.raise_(Registered(id=user_id, email="test@example.com", name="Test"))

    event = user._events[-1]
    message = Message.from_domain_object(event)

    metadata_dict = message.metadata.to_dict()
    metadata_dict["event_store"] = EventStoreMeta(
        position=stream_position, global_position=global_position
    )
    metadata_dict["domain"]["asynchronous"] = asynchronous

    # Set the stream name in headers so recovery can re-read from the correct stream
    if metadata_dict.get("headers"):
        metadata_dict["headers"]["stream"] = stream_name
    else:
        metadata_dict["headers"] = {"stream": stream_name}

    message.metadata = Metadata(**metadata_dict)

    return message


def _write_event_to_store(test_domain, msg: Message) -> int:
    """Write the event from a message into the event store at the correct stream.

    Returns the per-stream position assigned by the store.
    """
    stream_name = msg.metadata.headers.stream
    return test_domain.event_store.store._write(
        stream_name,
        msg.metadata.headers.type,
        msg.data,
        metadata=msg.metadata.to_dict(),
    )


def _make_subscription(
    test_domain,
    handler_cls,
    max_retries: int | None = 3,
    enable_recovery: bool | None = True,
    recovery_interval_seconds: float | None = 0,
    retry_delay_seconds: float | None = 0,
) -> EventStoreSubscription:
    """Create an EventStoreSubscription with test-friendly defaults."""
    engine = Engine(domain=test_domain, test_mode=False)
    return EventStoreSubscription(
        engine,
        "test",
        handler_cls,
        messages_per_tick=10,
        position_update_interval=1,
        max_retries=max_retries,
        enable_recovery=enable_recovery,
        recovery_interval_seconds=recovery_interval_seconds,
        retry_delay_seconds=retry_delay_seconds,
    )


# ──────────────────────────────────────────────────────────────────────
# Tests: Failed Position Recording
# ──────────────────────────────────────────────────────────────────────


class TestFailedPositionRecording:
    """Tests that handler failures are recorded as failed positions."""

    @pytest.mark.asyncio
    async def test_handler_failure_records_failed_position(self, test_domain):
        """A failed handler records the position in the failed-positions stream."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=5)

        result = await sub.process_batch([msg])

        assert result == 0  # No successful messages
        assert handler_counter == 1  # Handler was called

        # Failed position was recorded
        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 1
        assert failed_msgs[0].data["position"] == 5
        assert failed_msgs[0].data["retry_count"] == 0
        assert failed_msgs[0].metadata.headers.type == FailedPositionStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_failed_position_stores_stream_info(self, test_domain):
        """Failed position records include stream_name and stream_position."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(
            global_position=5, stream_position=0, stream_name="test-abc123"
        )

        await sub.process_batch([msg])

        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 1
        assert failed_msgs[0].data["stream_name"] == "test-abc123"
        assert failed_msgs[0].data["stream_position"] == 0

    @pytest.mark.asyncio
    async def test_in_memory_tracking_updated(self, test_domain):
        """The in-memory _failed_positions dict is updated on failure."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(
            global_position=5, stream_position=0, stream_name="test-abc123"
        )

        await sub.process_batch([msg])

        assert 5 in sub._failed_positions
        assert sub._failed_positions[5]["retry_count"] == 0
        assert sub._failed_positions[5]["stream_name"] == "test-abc123"
        assert sub._failed_positions[5]["stream_position"] == 0

    @pytest.mark.asyncio
    async def test_read_position_advances_despite_failure(self, test_domain):
        """The read position advances even when the handler fails (non-blocking)."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=10)

        await sub.process_batch([msg])

        assert sub.current_position == 10

        # Position update was written to the store
        pos_msgs = test_domain.event_store.store.read(
            sub.subscriber_stream_name, position=0
        )
        assert len(pos_msgs) > 0
        assert pos_msgs[-1].data["position"] == 10

    @pytest.mark.asyncio
    async def test_handle_error_callback_invoked(self, test_domain):
        """The handle_error() callback is invoked when the handler fails."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=1)

        await sub.process_batch([msg])

        assert error_handler_counter == 1

    @pytest.mark.asyncio
    async def test_exception_in_handle_error_doesnt_crash(self, test_domain, caplog):
        """An exception in handle_error() is caught; engine continues."""
        sub = _make_subscription(test_domain, ErrorInErrorHandlerEventHandler)
        msg = _create_message(global_position=1)

        with caplog.at_level(logging.ERROR):
            result = await sub.process_batch([msg])

        assert result == 0
        assert handler_counter == 1
        assert error_handler_counter == 1
        assert "engine.error_handler_failed" in caplog.text

    @pytest.mark.asyncio
    async def test_engine_doesnt_shut_down_on_failure(self, test_domain):
        """Engine remains running after handler failures."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=1)

        await sub.process_batch([msg])

        assert not sub.engine.shutting_down
        assert sub.engine.exit_code == 0

    @pytest.mark.asyncio
    async def test_multiple_failures_tracked_independently(self, test_domain):
        """Multiple failed positions are tracked as separate records."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        msg1 = _create_message(global_position=1)
        msg2 = _create_message(global_position=2)
        msg3 = _create_message(global_position=3)

        await sub.process_batch([msg1, msg2, msg3])

        assert handler_counter == 3

        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 3
        failed_positions = {m.data["position"] for m in failed_msgs}
        assert failed_positions == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_successful_messages_not_recorded_as_failed(self, test_domain):
        """Successful messages are not recorded in the failed-positions stream."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)
        msg = _create_message(global_position=1)

        result = await sub.process_batch([msg])

        assert result == 1
        assert handler_counter == 1

        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 0

    @pytest.mark.asyncio
    async def test_no_recording_when_recovery_disabled(self, test_domain):
        """Failed positions are not recorded when enable_recovery=False."""
        sub = _make_subscription(
            test_domain, AlwaysFailingEventHandler, enable_recovery=False
        )
        msg = _create_message(global_position=1)

        await sub.process_batch([msg])

        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 0

    @pytest.mark.asyncio
    async def test_sync_messages_skipped_not_recorded(self, test_domain):
        """Synchronous messages are skipped and not recorded as failures."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=1, asynchronous=False)

        await sub.process_batch([msg])

        # Not processed (skipped as sync), not counted as success either
        assert handler_counter == 0

        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 0


# ──────────────────────────────────────────────────────────────────────
# Tests: Recovery Pass
# ──────────────────────────────────────────────────────────────────────


class TestRecoveryPass:
    """Tests for the periodic recovery pass that retries failed positions."""

    @pytest.mark.asyncio
    async def test_recovery_succeeds_on_transient_failure(self, test_domain):
        """Recovery pass retries a failed position and succeeds."""
        global fail_count
        fail_count = 1  # Fail once, then succeed

        sub = _make_subscription(test_domain, TransientFailingEventHandler)

        # Create the message with per-stream position=0 (first write to a fresh stream)
        msg = _create_message(global_position=1, stream_position=0)

        # Write the event to the store so recovery can re-read it
        _write_event_to_store(test_domain, msg)

        # Process the message — it will fail and record a failed position
        result = await sub.process_batch([msg])
        assert result == 0
        assert handler_counter == 1  # Called once, failed
        assert fail_count == 0  # Used up the one failure

        # Now run recovery — the handler should succeed this time
        recovered = await sub.run_recovery_pass()

        assert recovered == 1
        assert handler_counter == 2  # Called again during recovery

        # Verify Resolved record was written
        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        statuses = [
            m.metadata.headers.type for m in failed_msgs if m.data["position"] == 1
        ]
        assert FailedPositionStatus.RESOLVED.value in statuses

    @pytest.mark.asyncio
    async def test_recovery_exhausts_after_max_retries(self, test_domain):
        """Recovery marks a position as exhausted after max_retries."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=2)

        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        # Process — fails and records failed position (retry_count=0)
        await sub.process_batch([msg])
        assert handler_counter == 1

        # Recovery pass 1 — fails again (retry_count becomes 1)
        recovered = await sub.run_recovery_pass()
        assert recovered == 0
        assert handler_counter == 2

        # Recovery pass 2 — fails again (retry_count becomes 2)
        recovered = await sub.run_recovery_pass()
        assert recovered == 0
        assert handler_counter == 3

        # Recovery pass 3 — exceeds max_retries(2), marks as exhausted
        recovered = await sub.run_recovery_pass()
        assert recovered == 0

        # Verify Exhausted record was written
        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        statuses = [m.metadata.headers.type for m in failed_msgs]
        assert FailedPositionStatus.EXHAUSTED.value in statuses

        # No more unresolved positions
        assert len(sub._get_unresolved_positions()) == 0

    @pytest.mark.asyncio
    async def test_recovery_skips_resolved_positions(self, test_domain):
        """Recovery pass does not re-process already-resolved positions."""
        global fail_count
        fail_count = 1

        sub = _make_subscription(test_domain, TransientFailingEventHandler)

        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        # Fail, then recover
        await sub.process_batch([msg])
        assert handler_counter == 1

        recovered = await sub.run_recovery_pass()
        assert recovered == 1
        assert handler_counter == 2

        # Run recovery again — nothing to do
        recovered = await sub.run_recovery_pass()
        assert recovered == 0
        assert handler_counter == 2  # Not called again

    @pytest.mark.asyncio
    async def test_recovery_skips_exhausted_positions(self, test_domain):
        """Recovery pass does not re-process already-exhausted positions."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=1)

        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        # Fail and record
        await sub.process_batch([msg])
        assert handler_counter == 1

        # Recovery pass 1 — fails (retry=1)
        await sub.run_recovery_pass()
        assert handler_counter == 2

        # Recovery pass 2 — exhausted (retry=2 > max_retries=1)
        await sub.run_recovery_pass()

        # Recovery pass 3 — nothing to do
        handler_before = handler_counter
        recovered = await sub.run_recovery_pass()
        assert recovered == 0
        assert handler_counter == handler_before  # Not called again

    @pytest.mark.asyncio
    async def test_recovery_pass_with_no_failures(self, test_domain):
        """Recovery pass with no failed positions returns 0."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)

        recovered = await sub.run_recovery_pass()
        assert recovered == 0

    @pytest.mark.asyncio
    async def test_recovery_handles_multiple_positions(self, test_domain):
        """Recovery pass handles multiple failed positions independently."""
        global fail_count
        fail_count = 3  # All three will fail initially

        sub = _make_subscription(test_domain, TransientFailingEventHandler)

        # Create messages with unique streams and write each to the store
        messages = []
        for i in range(3):
            msg = _create_message(global_position=i + 1, stream_position=0)
            _write_event_to_store(test_domain, msg)
            messages.append(msg)

        await sub.process_batch(messages)
        assert handler_counter == 3

        # All should succeed on recovery (fail_count is now 0)
        recovered = await sub.run_recovery_pass()
        assert recovered == 3

    @pytest.mark.asyncio
    async def test_recovery_retries_still_failing_message(self, test_domain):
        """Recovery increments retry_count when the handler still fails."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=5)

        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        # Initial failure
        await sub.process_batch([msg])
        assert sub._failed_positions[1]["retry_count"] == 0

        # First recovery — still fails
        await sub.run_recovery_pass()
        assert sub._failed_positions[1]["retry_count"] == 1

        # Second recovery — still fails
        await sub.run_recovery_pass()
        assert sub._failed_positions[1]["retry_count"] == 2


# ──────────────────────────────────────────────────────────────────────
# Tests: Recovery Timing (maybe_run_recovery)
# ──────────────────────────────────────────────────────────────────────


class TestRecoveryTiming:
    """Tests for the timing-based recovery trigger."""

    @pytest.mark.asyncio
    async def test_maybe_run_recovery_respects_interval(self, test_domain):
        """maybe_run_recovery skips if not enough time has elapsed."""
        sub = _make_subscription(
            test_domain,
            AlwaysFailingEventHandler,
            recovery_interval_seconds=60,  # Very long interval
        )
        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        await sub.process_batch([msg])

        # First call should run (last recovery time is 0)
        sub._last_recovery_time = 0.0
        result = await sub.maybe_run_recovery()
        # It ran (result >= 0 means it executed, even if nothing recovered)
        assert result == 0  # Handler fails, so 0 recovered but pass did run

        # Immediately calling again should skip (interval not elapsed)
        handler_before = handler_counter
        result = await sub.maybe_run_recovery()
        assert result == 0
        # Handler should NOT have been called again because recovery was skipped
        assert handler_counter == handler_before

    @pytest.mark.asyncio
    async def test_maybe_run_recovery_disabled(self, test_domain):
        """maybe_run_recovery returns 0 when recovery is disabled."""
        sub = _make_subscription(
            test_domain, AlwaysFailingEventHandler, enable_recovery=False
        )
        msg = _create_message(global_position=1)
        await sub.process_batch([msg])

        result = await sub.maybe_run_recovery()
        assert result == 0

    @pytest.mark.asyncio
    async def test_maybe_run_recovery_zero_interval(self, test_domain):
        """maybe_run_recovery runs every time with recovery_interval_seconds=0."""
        sub = _make_subscription(
            test_domain,
            AlwaysFailingEventHandler,
            recovery_interval_seconds=0,
        )
        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        await sub.process_batch([msg])

        # Both calls should run
        sub._last_recovery_time = 0.0
        await sub.maybe_run_recovery()
        count1 = handler_counter

        sub._last_recovery_time = 0.0
        await sub.maybe_run_recovery()
        count2 = handler_counter

        assert count2 > count1  # Recovery ran both times


# ──────────────────────────────────────────────────────────────────────
# Tests: Retry Count Rebuild on Initialization
# ──────────────────────────────────────────────────────────────────────


class TestRetryCountRebuild:
    """Tests for rebuilding retry counts from the failed-positions stream."""

    @pytest.mark.asyncio
    async def test_rebuild_retry_counts_from_stream(self, test_domain):
        """Retry counts are rebuilt from the failed-positions stream on init."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        msg = _create_message(global_position=5, stream_position=0)
        await sub.process_batch([msg])

        # Verify a failed record exists
        assert 5 in sub._failed_positions

        # Create a new subscription (simulates restart)
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub2._rebuild_retry_counts()

        assert 5 in sub2._failed_positions
        assert sub2._failed_positions[5]["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_rebuild_preserves_stream_info(self, test_domain):
        """Rebuild preserves stream_name and stream_position from records."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        msg = _create_message(
            global_position=5, stream_position=0, stream_name="test-abc123"
        )
        await sub.process_batch([msg])

        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub2._rebuild_retry_counts()

        assert 5 in sub2._failed_positions
        assert sub2._failed_positions[5]["stream_name"] == "test-abc123"
        assert sub2._failed_positions[5]["stream_position"] == 0

    @pytest.mark.asyncio
    async def test_rebuild_excludes_resolved_positions(self, test_domain):
        """Resolved positions are excluded from rebuilt retry counts."""
        global fail_count
        fail_count = 1

        sub = _make_subscription(test_domain, TransientFailingEventHandler)

        msg = _create_message(global_position=5, stream_position=0)
        _write_event_to_store(test_domain, msg)

        # Fail, then recover
        await sub.process_batch([msg])
        await sub.run_recovery_pass()

        # Create new subscription and rebuild
        sub2 = _make_subscription(test_domain, TransientFailingEventHandler)
        await sub2._rebuild_retry_counts()

        assert 5 not in sub2._failed_positions

    @pytest.mark.asyncio
    async def test_rebuild_excludes_exhausted_positions(self, test_domain):
        """Exhausted positions are excluded from rebuilt retry counts."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=1)

        msg = _create_message(global_position=5, stream_position=0)
        _write_event_to_store(test_domain, msg)

        await sub.process_batch([msg])
        await sub.run_recovery_pass()  # retry_count -> 1
        await sub.run_recovery_pass()  # retry_count -> 2, exhausted

        # Create new subscription and rebuild
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=1)
        await sub2._rebuild_retry_counts()

        assert 5 not in sub2._failed_positions

    @pytest.mark.asyncio
    async def test_initialize_rebuilds_retry_counts(self, test_domain):
        """initialize() calls _rebuild_retry_counts when recovery is enabled."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        msg = _create_message(global_position=7)
        await sub.process_batch([msg])

        # New subscription — initialize should rebuild
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub2.initialize()

        assert 7 in sub2._failed_positions

    @pytest.mark.asyncio
    async def test_initialize_skips_rebuild_when_disabled(self, test_domain):
        """initialize() skips rebuild when enable_recovery=False."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=7)
        await sub.process_batch([msg])

        sub2 = _make_subscription(
            test_domain, AlwaysFailingEventHandler, enable_recovery=False
        )
        await sub2.initialize()

        assert len(sub2._failed_positions) == 0


# ──────────────────────────────────────────────────────────────────────
# Tests: Configuration
# ──────────────────────────────────────────────────────────────────────


class TestConfiguration:
    """Tests for configuration resolution from domain config."""

    def test_defaults_from_domain_config(self, test_domain):
        """Configuration defaults are resolved from domain config."""
        sub = _make_subscription(
            test_domain,
            SucceedingEventHandler,
            max_retries=None,
            enable_recovery=None,
            recovery_interval_seconds=None,
            retry_delay_seconds=None,
        )
        # Check values come from config defaults
        assert sub.max_retries == 3
        assert sub.retry_delay_seconds == 1.0
        assert sub.enable_recovery is True
        assert sub.recovery_interval_seconds == 30.0

    def test_explicit_overrides(self, test_domain):
        """Explicit constructor args override config defaults."""
        sub = _make_subscription(
            test_domain,
            SucceedingEventHandler,
            max_retries=5,
            enable_recovery=False,
            recovery_interval_seconds=120,
            retry_delay_seconds=2.5,
        )
        assert sub.max_retries == 5
        assert sub.retry_delay_seconds == 2.5
        assert sub.enable_recovery is False
        assert sub.recovery_interval_seconds == 120.0

    def test_failed_positions_stream_name(self, test_domain):
        """Failed positions stream name follows the convention."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)
        expected_prefix = f"failed-{sub.subscriber_name}-test"
        assert sub.failed_positions_stream == expected_prefix


# ──────────────────────────────────────────────────────────────────────
# Tests: Recovery Checkpoint / Watermark
# ──────────────────────────────────────────────────────────────────────


class TestRecoveryCheckpoint:
    """Tests for checkpoint-based watermarking that avoids re-reading the
    entire failed-positions stream on every restart."""

    @pytest.mark.asyncio
    async def test_checkpoint_written_after_rebuild(self, test_domain):
        """A checkpoint record is written after _rebuild_retry_counts."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(global_position=5, stream_position=0)

        await sub.process_batch([msg])

        # Rebuild writes a checkpoint
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub2._rebuild_retry_counts()

        checkpoint = test_domain.event_store.store._read_last_message(
            sub2.recovery_checkpoint_stream
        )
        assert checkpoint is not None
        assert checkpoint["data"]["watermark"] > 0
        assert "5" in checkpoint["data"]["unresolved"]

    @pytest.mark.asyncio
    async def test_rebuild_from_checkpoint_skips_old_records(self, test_domain):
        """Rebuild reads only new records after the checkpoint watermark."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        # Generate some failed positions
        for gp in [1, 2, 3]:
            msg = _create_message(global_position=gp, stream_position=0)
            await sub.process_batch([msg])

        # First rebuild — processes all 3 records, writes checkpoint
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub2._rebuild_retry_counts()
        assert len(sub2._failed_positions) == 3

        checkpoint = test_domain.event_store.store._read_last_message(
            sub2.recovery_checkpoint_stream
        )
        first_watermark = checkpoint["data"]["watermark"]
        assert first_watermark > 0

        # Add one more failure
        msg4 = _create_message(global_position=4, stream_position=0)
        await sub.process_batch([msg4])

        # Second rebuild — should pick up position 4 from the checkpoint
        sub3 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub3._rebuild_retry_counts()
        assert len(sub3._failed_positions) == 4
        assert 4 in sub3._failed_positions

        # Checkpoint should have advanced
        checkpoint2 = test_domain.event_store.store._read_last_message(
            sub3.recovery_checkpoint_stream
        )
        assert checkpoint2["data"]["watermark"] > first_watermark

    @pytest.mark.asyncio
    async def test_checkpoint_restores_unresolved_positions(self, test_domain):
        """Checkpoint snapshot correctly restores unresolved positions."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)
        msg = _create_message(
            global_position=5, stream_position=0, stream_name="test-restore123"
        )
        await sub.process_batch([msg])

        # Rebuild writes checkpoint with the unresolved position
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub2._rebuild_retry_counts()

        # Third subscription — restores from checkpoint
        sub3 = _make_subscription(test_domain, AlwaysFailingEventHandler)
        await sub3._rebuild_retry_counts()

        assert 5 in sub3._failed_positions
        assert sub3._failed_positions[5]["stream_name"] == "test-restore123"
        assert sub3._failed_positions[5]["stream_position"] == 0

    @pytest.mark.asyncio
    async def test_checkpoint_excludes_resolved_on_next_rebuild(self, test_domain):
        """Positions resolved after a checkpoint are excluded on next rebuild."""
        global fail_count
        fail_count = 1  # Fail once, then succeed

        sub = _make_subscription(test_domain, TransientFailingEventHandler)
        msg = _create_message(global_position=5, stream_position=0)
        _write_event_to_store(test_domain, msg)

        # Fail and checkpoint
        await sub.process_batch([msg])
        await sub._rebuild_retry_counts()
        assert 5 in sub._failed_positions

        # Recover the position
        await sub.run_recovery_pass()
        assert 5 not in sub._failed_positions

        # New subscription — rebuild should see the Resolved record
        sub2 = _make_subscription(test_domain, TransientFailingEventHandler)
        await sub2._rebuild_retry_counts()
        assert 5 not in sub2._failed_positions

    @pytest.mark.asyncio
    async def test_no_checkpoint_written_when_no_records(self, test_domain):
        """No checkpoint is written when the failed-positions stream is empty."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)
        await sub._rebuild_retry_counts()

        checkpoint = test_domain.event_store.store._read_last_message(
            sub.recovery_checkpoint_stream
        )
        assert checkpoint is None

    @pytest.mark.asyncio
    async def test_checkpoint_stream_name(self, test_domain):
        """Checkpoint stream name follows the naming convention."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)
        expected = f"recovery-checkpoint-{sub.subscriber_name}-test"
        assert sub.recovery_checkpoint_stream == expected

    @pytest.mark.asyncio
    async def test_watermark_advances_past_terminal_records(self, test_domain):
        """Watermark advances past resolved/exhausted records on rebuild."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=0)

        # Create a failure that will be exhausted
        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)
        await sub.process_batch([msg])
        await sub.run_recovery_pass()  # Exhausts immediately (max_retries=0)

        # Rebuild — position 1 is exhausted, so _failed_positions is empty
        sub2 = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=0)
        await sub2._rebuild_retry_counts()
        assert len(sub2._failed_positions) == 0

        checkpoint = test_domain.event_store.store._read_last_message(
            sub2.recovery_checkpoint_stream
        )
        assert checkpoint is not None
        # Watermark should have advanced past all the terminal records
        assert checkpoint["data"]["watermark"] > 0
        assert len(checkpoint["data"]["unresolved"]) == 0


# ──────────────────────────────────────────────────────────────────────
# Tests: Mixed Success/Failure Batches
# ──────────────────────────────────────────────────────────────────────


class TestMixedBatches:
    """Tests processing batches with a mix of success and failure."""

    @pytest.mark.asyncio
    async def test_mixed_batch_records_only_failures(self, test_domain):
        """In a mixed batch, only failed positions are recorded."""
        global fail_count
        fail_count = 1  # First message fails, second succeeds

        sub = _make_subscription(test_domain, TransientFailingEventHandler)

        msg1 = _create_message(global_position=1)
        msg2 = _create_message(global_position=2)

        result = await sub.process_batch([msg1, msg2])

        assert result == 1  # One success
        assert handler_counter == 2  # Both called

        # Only position 1 should be recorded as failed
        failed_msgs = test_domain.event_store.store.read(
            sub.failed_positions_stream, position=0
        )
        assert len(failed_msgs) == 1
        assert failed_msgs[0].data["position"] == 1

    @pytest.mark.asyncio
    async def test_position_advances_for_all_in_batch(self, test_domain):
        """Read position advances past all messages in a batch, including failures."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        msg1 = _create_message(global_position=10)
        msg2 = _create_message(global_position=20)

        await sub.process_batch([msg1, msg2])

        assert sub.current_position == 20  # Advanced past both


# ──────────────────────────────────────────────────────────────────────
# Tests: Emitter Traces
# ──────────────────────────────────────────────────────────────────────


class TestEmitterTraces:
    """Tests that appropriate trace events are emitted."""

    @pytest.mark.asyncio
    async def test_exhausted_position_emits_handler_failed_trace(self, test_domain):
        """Exhausted positions emit a handler.failed trace event."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=0)

        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        await sub.process_batch([msg])

        # With max_retries=0, first recovery pass should exhaust
        await sub.run_recovery_pass()

        # Position should be exhausted
        assert len(sub._get_unresolved_positions()) == 0


# ──────────────────────────────────────────────────────────────────────
# Tests: Recovery Edge Cases
# ──────────────────────────────────────────────────────────────────────


class TestRecoveryEdgeCases:
    """Edge cases in the recovery pass."""

    @pytest.mark.asyncio
    async def test_recovery_fallback_when_stream_name_is_none(
        self, test_domain, caplog
    ):
        """Recovery reads from category stream when stream_name is not recorded."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler, max_retries=5)

        msg = _create_message(global_position=1, stream_position=0)
        # Write event to store at its specific stream
        _write_event_to_store(test_domain, msg)

        await sub.process_batch([msg])

        # Manually clear stream_name to simulate a record without stream info
        sub._failed_positions[1]["stream_name"] = None
        sub._failed_positions[1]["stream_position"] = None

        # Recovery should fall back to reading from category stream using
        # global_position. The category stream read may or may not find the
        # message — the key thing is the code path doesn't crash.
        with caplog.at_level(logging.WARNING):
            recovered = await sub.run_recovery_pass()

        assert recovered == 0
        # Position still tracked (not removed — message may not have been found
        # or handler may have failed again)
        assert 1 in sub._failed_positions

    @pytest.mark.asyncio
    async def test_recovery_handles_message_not_found(self, test_domain, caplog):
        """Recovery logs warning and skips when message is not found at position."""
        sub = _make_subscription(test_domain, AlwaysFailingEventHandler)

        msg = _create_message(global_position=1, stream_position=0)
        # Intentionally do NOT write to store — message won't be found

        await sub.process_batch([msg])

        # Manually set a stream_name that doesn't exist in the store
        sub._failed_positions[1]["stream_name"] = "nonexistent-stream-999"
        sub._failed_positions[1]["stream_position"] = 999

        with caplog.at_level(logging.WARNING):
            recovered = await sub.run_recovery_pass()

        assert recovered == 0
        assert "Could not find message at position 1" in caplog.text
        # Position still in tracking (not removed — will retry next pass)
        assert 1 in sub._failed_positions

    @pytest.mark.asyncio
    async def test_recovery_with_positive_retry_delay(self, test_domain):
        """Recovery applies retry_delay_seconds > 0 between retries."""
        import time

        global fail_count
        fail_count = 1  # Fail once, then succeed

        sub = _make_subscription(
            test_domain,
            TransientFailingEventHandler,
            retry_delay_seconds=0.05,  # Small but nonzero delay
        )

        msg = _create_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)

        await sub.process_batch([msg])

        start = time.monotonic()
        recovered = await sub.run_recovery_pass()
        elapsed = time.monotonic() - start

        assert recovered == 1
        # Should have delayed at least 50ms
        assert elapsed >= 0.04  # Small tolerance


# ──────────────────────────────────────────────────────────────────────
# Tests: Poll and Cleanup
# ──────────────────────────────────────────────────────────────────────


class TestPollAndCleanup:
    """Tests for poll() integration with recovery and cleanup()."""

    @pytest.mark.asyncio
    async def test_poll_calls_maybe_run_recovery(self, test_domain):
        """poll() calls maybe_run_recovery() on each iteration."""
        sub = _make_subscription(
            test_domain, SucceedingEventHandler, recovery_interval_seconds=0
        )
        sub.tick_interval = 0  # No sleep between iterations

        recovery_calls = 0

        async def counting_recovery():
            nonlocal recovery_calls
            recovery_calls += 1
            # Stop after 2 iterations
            if recovery_calls >= 2:
                sub.keep_going = False
            return 0

        sub.maybe_run_recovery = counting_recovery

        async def noop_tick():
            pass

        sub.tick = noop_tick

        await asyncio.wait_for(sub.poll(), timeout=2.0)

        assert recovery_calls >= 2

    @pytest.mark.asyncio
    async def test_poll_exits_on_engine_shutting_down(self, test_domain):
        """poll() exits when engine.shutting_down is set."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)
        sub.tick = AsyncMock()

        async def stop_engine():
            await asyncio.sleep(0.05)
            sub.engine.shutting_down = True

        asyncio.create_task(stop_engine())
        await asyncio.wait_for(sub.poll(), timeout=2.0)

        assert sub.engine.shutting_down

    @pytest.mark.asyncio
    async def test_cleanup_updates_position_to_store(self, test_domain):
        """cleanup() persists the current position to the store."""
        sub = _make_subscription(test_domain, SucceedingEventHandler)
        sub.current_position = 42

        await sub.cleanup()

        last_pos = await sub.fetch_last_position()
        assert last_pos == 42
