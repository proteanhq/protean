"""Tests for Outbox aggregate behavior and state transitions."""

import pytest
from datetime import datetime, timezone, timedelta

from protean.utils.outbox import Outbox, OutboxStatus, ProcessingResult
from protean.utils.eventing import Metadata


@pytest.fixture(autouse=True)
def setup_outbox_domain(test_domain):
    """Set up the domain with Outbox aggregate registered."""
    test_domain.register(Outbox)
    test_domain.init(traverse=False)


@pytest.fixture
def sample_metadata():
    """Create sample metadata for testing."""
    return Metadata(
        id="test-id",
        type="TestEvent",
        fqn="test.TestEvent",
        kind="event",
        stream="test-stream",
        origin_stream="test-message-123",
        timestamp=datetime.now(timezone.utc),
        version="1.0",
        sequence_id="1",
        payload_hash=12345,
    )


@pytest.fixture
def sample_outbox(sample_metadata):
    """Create a sample outbox message for testing."""
    return Outbox.create_message(
        message_id="message-123",
        stream_name="test-stream",
        message_type="TestEvent",
        data={"key": "value"},
        metadata=sample_metadata,
        priority=1,
        correlation_id="corr-123",
        trace_id="trace-456",
        max_retries=3,
    )


@pytest.mark.database
class TestOutboxCreation:
    """Test outbox message creation."""

    def test_create_message_with_all_fields(self, sample_metadata):
        """Test creating an outbox message with all fields."""
        outbox = Outbox.create_message(
            message_id="message-123",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"key": "value"},
            metadata=sample_metadata,
            priority=5,
            correlation_id="corr-123",
            trace_id="trace-456",
            max_retries=5,
            sequence_number=10,
        )

        assert outbox.message_id == "message-123"
        assert outbox.stream_name == "test-stream"
        assert outbox.type == "TestEvent"
        assert outbox.data == {"key": "value"}
        assert outbox.metadata == sample_metadata
        assert outbox.priority == 5
        assert outbox.correlation_id == "corr-123"
        assert outbox.trace_id == "trace-456"
        assert outbox.max_retries == 5
        assert outbox.sequence_number == 10
        assert outbox.status == OutboxStatus.PENDING.value
        assert outbox.retry_count == 0
        assert outbox.published_at is None
        assert outbox.last_error is None

    def test_create_message_with_defaults(self, sample_metadata):
        """Test creating an outbox message with default values."""
        outbox = Outbox.create_message(
            message_id="message-123",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"key": "value"},
            metadata=sample_metadata,
        )

        assert outbox.priority == 0
        assert outbox.correlation_id is None
        assert outbox.trace_id is None
        assert outbox.max_retries == 3
        assert outbox.sequence_number is None
        assert outbox.status == OutboxStatus.PENDING.value

    def test_created_at_is_set(self, sample_metadata):
        """Test that created_at is automatically set."""
        before_creation = datetime.now(timezone.utc)
        outbox = Outbox.create_message(
            message_id="message-123",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"key": "value"},
            metadata=sample_metadata,
        )
        after_creation = datetime.now(timezone.utc)

        assert before_creation <= outbox.created_at <= after_creation


class TestStartProcessing:
    """Test start_processing method."""

    def test_start_processing_success(self, sample_outbox):
        """Test successfully starting to process a pending message."""
        worker_id = "worker-1"
        success, result = sample_outbox.start_processing(
            worker_id, lock_duration_minutes=10
        )

        assert success is True
        assert result == ProcessingResult.SUCCESS
        assert sample_outbox.status == OutboxStatus.PROCESSING.value
        assert sample_outbox.locked_by == worker_id
        assert sample_outbox.locked_until is not None
        assert sample_outbox.last_processed_at is not None

    def test_start_processing_already_published(self, sample_outbox):
        """Test starting to process an already published message fails."""
        sample_outbox.status = OutboxStatus.PUBLISHED.value

        success, result = sample_outbox.start_processing("worker-1")

        assert success is False
        assert result == ProcessingResult.NOT_ELIGIBLE
        assert sample_outbox.locked_by is None

    def test_start_processing_already_processing(self, sample_outbox):
        """Test starting to process an already processing message fails."""
        sample_outbox.status = OutboxStatus.PROCESSING.value

        success, result = sample_outbox.start_processing("worker-1")

        assert success is False
        assert result == ProcessingResult.NOT_ELIGIBLE

    def test_start_processing_already_abandoned(self, sample_outbox):
        """Test starting to process an abandoned message fails."""
        sample_outbox.status = OutboxStatus.ABANDONED.value

        success, result = sample_outbox.start_processing("worker-1")

        assert success is False
        assert result == ProcessingResult.NOT_ELIGIBLE

    def test_start_processing_max_retries_exceeded(self, sample_outbox):
        """Test starting to process when max retries exceeded fails."""
        sample_outbox.retry_count = sample_outbox.max_retries

        success, result = sample_outbox.start_processing("worker-1")

        assert success is False
        assert result == ProcessingResult.MAX_RETRIES_EXCEEDED

    def test_start_processing_too_early_for_retry(self, sample_outbox):
        """Test starting to process before retry time fails."""
        sample_outbox.status = OutboxStatus.FAILED.value
        sample_outbox.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        success, result = sample_outbox.start_processing("worker-1")

        assert success is False
        assert result == ProcessingResult.RETRY_NOT_DUE

    def test_start_processing_ready_for_retry(self, sample_outbox):
        """Test starting to process a failed message that's ready for retry."""
        sample_outbox.status = OutboxStatus.FAILED.value
        sample_outbox.retry_count = 1
        sample_outbox.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        success, result = sample_outbox.start_processing("worker-1")

        assert success is True
        assert result == ProcessingResult.SUCCESS
        assert sample_outbox.status == OutboxStatus.PROCESSING.value

    def test_start_processing_sets_lock_duration(self, sample_outbox):
        """Test that start_processing sets correct lock duration."""
        lock_duration = 15
        before_lock = datetime.now(timezone.utc)

        success, result = sample_outbox.start_processing(
            "worker-1", lock_duration_minutes=lock_duration
        )

        assert success is True
        assert result == ProcessingResult.SUCCESS
        expected_unlock_time = before_lock + timedelta(minutes=lock_duration)
        # Allow small time difference due to execution time
        time_diff = abs(
            (sample_outbox.locked_until - expected_unlock_time).total_seconds()
        )
        assert time_diff < 1  # Less than 1 second difference


class TestMarkPublished:
    """Test mark_published method."""

    def test_mark_published_success(self, sample_outbox):
        """Test marking a processing message as published."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        sample_outbox.locked_by = "worker-1"
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)

        before_publish = datetime.now(timezone.utc)
        sample_outbox.mark_published()
        after_publish = datetime.now(timezone.utc)

        assert sample_outbox.status == OutboxStatus.PUBLISHED.value
        assert before_publish <= sample_outbox.published_at <= after_publish
        assert before_publish <= sample_outbox.last_processed_at <= after_publish
        assert sample_outbox.last_error is None
        assert sample_outbox.locked_by is None
        assert sample_outbox.locked_until is None

    def test_mark_published_clears_previous_error(self, sample_outbox):
        """Test that mark_published clears any previous error."""
        sample_outbox.last_error = {"message": "Previous error"}

        sample_outbox.mark_published()

        assert sample_outbox.last_error is None


class TestMarkFailed:
    """Test mark_failed method."""

    def test_mark_failed_with_retries_available(self, sample_outbox):
        """Test marking a message as failed when retries are available."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        sample_outbox.locked_by = "worker-1"
        error = ValueError("Test error")

        before_fail = datetime.now(timezone.utc)
        sample_outbox.mark_failed(error, base_delay_seconds=30)
        after_fail = datetime.now(timezone.utc)

        assert sample_outbox.status == OutboxStatus.FAILED.value
        assert sample_outbox.retry_count == 1
        assert before_fail <= sample_outbox.last_processed_at <= after_fail
        assert sample_outbox.last_error["message"] == "Test error"
        assert "traceback" in sample_outbox.last_error
        assert sample_outbox.next_retry_at is not None
        assert sample_outbox.locked_by is None
        assert sample_outbox.locked_until is None

    def test_mark_failed_max_retries_exceeded(self, sample_outbox):
        """Test marking as failed when max retries exceeded leads to abandonment."""
        sample_outbox.retry_count = sample_outbox.max_retries - 1  # One retry left
        error = ValueError("Final error")

        sample_outbox.mark_failed(error)

        assert sample_outbox.status == OutboxStatus.ABANDONED.value
        assert sample_outbox.retry_count == sample_outbox.max_retries
        assert sample_outbox.last_error["reason"] == "Max retries exceeded"

    def test_mark_failed_exponential_backoff(self, sample_outbox):
        """Test that exponential backoff is applied correctly."""
        base_delay = 60
        sample_outbox.retry_count = 0
        error = ValueError("Test error")

        before_fail = datetime.now(timezone.utc)
        sample_outbox.mark_failed(error, base_delay_seconds=base_delay)

        # Expected delay = base_delay * (2 ^ retry_count) = 60 * (2 ^ 1) = 120 seconds
        expected_retry_time = before_fail + timedelta(seconds=120)
        time_diff = abs(
            (sample_outbox.next_retry_at - expected_retry_time).total_seconds()
        )
        assert time_diff < 1  # Less than 1 second difference

    def test_mark_failed_multiple_times(self, sample_outbox):
        """Test marking as failed multiple times increments retry count correctly."""
        error1 = ValueError("First error")
        error2 = ValueError("Second error")

        sample_outbox.mark_failed(error1)
        assert sample_outbox.retry_count == 1
        assert sample_outbox.status == OutboxStatus.FAILED.value

        sample_outbox.mark_failed(error2)
        assert sample_outbox.retry_count == 2
        assert sample_outbox.last_error["message"] == "Second error"


class TestMarkAbandoned:
    """Test mark_abandoned method."""

    def test_mark_abandoned(self, sample_outbox):
        """Test marking a message as abandoned."""
        sample_outbox.locked_by = "worker-1"
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        reason = "Manual abandonment"

        sample_outbox.mark_abandoned(reason)

        assert sample_outbox.status == OutboxStatus.ABANDONED.value
        assert sample_outbox.last_error["message"] == reason
        assert sample_outbox.last_error["reason"] == "Manually abandoned"
        assert "abandoned_at" in sample_outbox.last_error
        assert sample_outbox.locked_by is None
        assert sample_outbox.locked_until is None

    def test_mark_abandoned_preserves_retry_count(self, sample_outbox):
        """Test that mark_abandoned preserves the current retry count."""
        sample_outbox.retry_count = 2

        sample_outbox.mark_abandoned("Test reason")

        assert sample_outbox.last_error["retry_count"] == 2


class TestResetForRetry:
    """Test reset_for_retry method."""

    def test_reset_failed_message(self, sample_outbox):
        """Test resetting a failed message for retry."""
        sample_outbox.status = OutboxStatus.FAILED.value
        sample_outbox.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        sample_outbox.locked_by = "worker-1"
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=2)

        result = sample_outbox.reset_for_retry()

        assert result is True
        assert sample_outbox.status == OutboxStatus.PENDING.value
        assert sample_outbox.next_retry_at is None
        assert sample_outbox.locked_by is None
        assert sample_outbox.locked_until is None

    def test_reset_abandoned_message(self, sample_outbox):
        """Test resetting an abandoned message for retry."""
        sample_outbox.status = OutboxStatus.ABANDONED.value

        result = sample_outbox.reset_for_retry()

        assert result is True
        assert sample_outbox.status == OutboxStatus.PENDING.value

    def test_reset_pending_message_fails(self, sample_outbox):
        """Test resetting a pending message fails."""
        assert sample_outbox.status == OutboxStatus.PENDING.value

        result = sample_outbox.reset_for_retry()

        assert result is False
        assert sample_outbox.status == OutboxStatus.PENDING.value

    def test_reset_published_message_fails(self, sample_outbox):
        """Test resetting a published message fails."""
        sample_outbox.status = OutboxStatus.PUBLISHED.value

        result = sample_outbox.reset_for_retry()

        assert result is False
        assert sample_outbox.status == OutboxStatus.PUBLISHED.value

    def test_reset_processing_message_fails(self, sample_outbox):
        """Test resetting a processing message fails."""
        sample_outbox.status = OutboxStatus.PROCESSING.value

        result = sample_outbox.reset_for_retry()

        assert result is False
        assert sample_outbox.status == OutboxStatus.PROCESSING.value


class TestUpdatePriority:
    """Test update_priority method."""

    def test_update_priority_pending_message(self, sample_outbox):
        """Test updating priority of a pending message."""
        assert sample_outbox.status == OutboxStatus.PENDING.value
        original_priority = sample_outbox.priority
        new_priority = original_priority + 10

        sample_outbox.update_priority(new_priority)

        assert sample_outbox.priority == new_priority

    def test_update_priority_failed_message(self, sample_outbox):
        """Test updating priority of a failed message."""
        sample_outbox.status = OutboxStatus.FAILED.value
        new_priority = 99

        sample_outbox.update_priority(new_priority)

        assert sample_outbox.priority == new_priority

    def test_update_priority_published_message_ignored(self, sample_outbox):
        """Test updating priority of a published message is ignored."""
        sample_outbox.status = OutboxStatus.PUBLISHED.value
        original_priority = sample_outbox.priority

        sample_outbox.update_priority(99)

        assert sample_outbox.priority == original_priority

    def test_update_priority_processing_message_ignored(self, sample_outbox):
        """Test updating priority of a processing message is ignored."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        original_priority = sample_outbox.priority

        sample_outbox.update_priority(99)

        assert sample_outbox.priority == original_priority

    def test_update_priority_abandoned_message_ignored(self, sample_outbox):
        """Test updating priority of an abandoned message is ignored."""
        sample_outbox.status = OutboxStatus.ABANDONED.value
        original_priority = sample_outbox.priority

        sample_outbox.update_priority(99)

        assert sample_outbox.priority == original_priority


class TestIsReadyForProcessing:
    """Test is_ready_for_processing method."""

    def test_pending_message_is_ready(self, sample_outbox):
        """Test that a pending message is ready for processing."""
        assert sample_outbox.status == OutboxStatus.PENDING.value
        assert sample_outbox.is_ready_for_processing() is True

    def test_published_message_not_ready(self, sample_outbox):
        """Test that a published message is not ready for processing."""
        sample_outbox.status = OutboxStatus.PUBLISHED.value
        assert sample_outbox.is_ready_for_processing() is False

    def test_processing_message_not_ready(self, sample_outbox):
        """Test that a processing message is not ready for processing."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        assert sample_outbox.is_ready_for_processing() is False

    def test_abandoned_message_not_ready(self, sample_outbox):
        """Test that an abandoned message is not ready for processing."""
        sample_outbox.status = OutboxStatus.ABANDONED.value
        assert sample_outbox.is_ready_for_processing() is False

    def test_failed_message_ready_after_retry_time(self, sample_outbox):
        """Test that a failed message is ready after retry time has passed."""
        sample_outbox.status = OutboxStatus.FAILED.value
        sample_outbox.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        assert sample_outbox.is_ready_for_processing() is True

    def test_failed_message_not_ready_before_retry_time(self, sample_outbox):
        """Test that a failed message is not ready before retry time."""
        sample_outbox.status = OutboxStatus.FAILED.value
        sample_outbox.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        assert sample_outbox.is_ready_for_processing() is False

    def test_max_retries_exceeded_not_ready(self, sample_outbox):
        """Test that a message with max retries exceeded is not ready."""
        sample_outbox.status = OutboxStatus.FAILED.value
        sample_outbox.retry_count = sample_outbox.max_retries

        assert sample_outbox.is_ready_for_processing() is False

    def test_locked_message_not_ready(self, sample_outbox):
        """Test that a locked message is not ready for processing."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)

        assert sample_outbox.is_ready_for_processing() is False


class TestPrivateHelperMethods:
    """Test private helper methods."""

    def test_is_locked_with_valid_lock(self, sample_outbox):
        """Test _is_locked with a valid lock."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)

        assert sample_outbox._is_locked() is True

    def test_is_locked_with_expired_lock(self, sample_outbox):
        """Test _is_locked with an expired lock."""
        sample_outbox.status = OutboxStatus.PROCESSING.value
        sample_outbox.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)

        assert sample_outbox._is_locked() is False

    def test_is_locked_without_processing_status(self, sample_outbox):
        """Test _is_locked when status is not PROCESSING."""
        sample_outbox.status = OutboxStatus.PENDING.value
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)

        assert sample_outbox._is_locked() is False

    def test_can_retry_under_limit(self, sample_outbox):
        """Test _can_retry when under retry limit."""
        sample_outbox.retry_count = 1
        sample_outbox.max_retries = 3

        assert sample_outbox._can_retry() is True

    def test_can_retry_at_limit(self, sample_outbox):
        """Test _can_retry when at retry limit."""
        sample_outbox.retry_count = 3
        sample_outbox.max_retries = 3

        assert sample_outbox._can_retry() is False

    def test_clear_lock(self, sample_outbox):
        """Test _clear_lock clears lock fields."""
        sample_outbox.locked_by = "worker-1"
        sample_outbox.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)

        sample_outbox._clear_lock()

        assert sample_outbox.locked_by is None
        assert sample_outbox.locked_until is None

    def test_calculate_next_retry_exponential_backoff(self, sample_outbox):
        """Test _calculate_next_retry implements exponential backoff."""
        base_delay = 30
        sample_outbox.retry_count = 2

        before_calc = datetime.now(timezone.utc)
        sample_outbox._calculate_next_retry(base_delay)

        # Expected delay = 30 * (2 ^ 2) = 120 seconds
        expected_time = before_calc + timedelta(seconds=120)
        time_diff = abs((sample_outbox.next_retry_at - expected_time).total_seconds())
        assert time_diff < 1  # Less than 1 second difference


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_max_retries(self, sample_metadata):
        """Test behavior with zero max retries."""
        outbox = Outbox.create_message(
            message_id="message-123",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"key": "value"},
            metadata=sample_metadata,
            max_retries=0,
        )

        # Should not be able to start processing after first failure
        error = ValueError("Test error")
        outbox.mark_failed(error)

        assert outbox.status == OutboxStatus.ABANDONED.value
        assert not outbox._can_retry()

    def test_negative_priority(self, sample_metadata):
        """Test handling of negative priority values."""
        outbox = Outbox.create_message(
            message_id="message-123",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"key": "value"},
            metadata=sample_metadata,
            priority=-5,
        )

        assert outbox.priority == -5

        outbox.update_priority(-10)
        assert outbox.priority == -10

    def test_very_long_lock_duration(self, sample_outbox):
        """Test very long lock duration."""
        lock_duration = 1440  # 24 hours

        success, result = sample_outbox.start_processing(
            "worker-1", lock_duration_minutes=lock_duration
        )

        assert success is True
        assert result == ProcessingResult.SUCCESS
        expected_unlock = datetime.now(timezone.utc) + timedelta(minutes=lock_duration)
        time_diff = abs((sample_outbox.locked_until - expected_unlock).total_seconds())
        assert time_diff < 1

    def test_concurrent_processing_attempts(self, sample_outbox):
        """Test concurrent processing attempts on same message."""
        # First worker acquires lock
        success1, result1 = sample_outbox.start_processing("worker-1")
        assert success1 is True
        assert result1 == ProcessingResult.SUCCESS

        # Second worker should fail to acquire lock
        success2, result2 = sample_outbox.start_processing("worker-2")
        assert success2 is False
        assert result2 == ProcessingResult.ALREADY_LOCKED
        assert sample_outbox.locked_by == "worker-1"

    def test_state_transitions_integrity(self, sample_outbox):
        """Test that state transitions maintain data integrity."""
        # Start with pending
        assert sample_outbox.status == OutboxStatus.PENDING.value
        assert sample_outbox.retry_count == 0

        # Start processing
        success, result = sample_outbox.start_processing("worker-1")
        assert success is True
        assert result == ProcessingResult.SUCCESS
        assert sample_outbox.status == OutboxStatus.PROCESSING.value
        assert sample_outbox.locked_by == "worker-1"

        # Fail processing
        error = ValueError("Test error")
        sample_outbox.mark_failed(error)
        assert sample_outbox.status == OutboxStatus.FAILED.value
        assert sample_outbox.retry_count == 1
        assert sample_outbox.locked_by is None

        # Reset for retry
        sample_outbox.reset_for_retry()
        assert sample_outbox.status == OutboxStatus.PENDING.value
        assert sample_outbox.next_retry_at is None

    def test_minimal_data_and_metadata(self, sample_metadata):
        """Test handling of minimal data."""
        outbox = Outbox.create_message(
            message_id="message-123",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"minimal": "data"},  # Minimal data
            metadata=sample_metadata,
        )

        assert outbox.data == {"minimal": "data"}
        assert outbox.metadata == sample_metadata
