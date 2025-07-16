"""Tests for OutboxRepository query methods."""

import pytest
from datetime import datetime, timezone, timedelta

from protean.utils.outbox import Outbox, OutboxRepository, OutboxStatus
from protean.utils.eventing import Metadata


@pytest.fixture(autouse=True)
def setup_outbox_domain(test_domain):
    """Set up the domain with Outbox aggregate and repository registered."""
    test_domain.register(Outbox)
    test_domain.register(OutboxRepository, part_of=Outbox)
    test_domain.init(traverse=False)
    return test_domain


@pytest.fixture
def sample_metadata():
    """Create sample metadata for testing."""
    return Metadata(
        id="test-id",
        type="TestEvent",
        fqn="test.TestEvent",
        kind="event",
        stream="test-stream",
        origin_stream="test-aggregate-123",
        timestamp=datetime.now(timezone.utc),
        version="1.0",
        sequence_id="1",
        payload_hash=12345,
    )


@pytest.fixture
def outbox_repo(test_domain):
    """Get the outbox repository."""
    return test_domain.repository_for(Outbox)


@pytest.fixture
def create_sample_messages(test_domain, sample_metadata):
    """Create sample outbox messages for testing."""

    def _create_messages():
        messages = []

        # Create PENDING messages
        for i in range(3):
            msg = Outbox.create_message(
                message_id=f"message-{i}",
                stream_name=f"stream-{i}",
                message_type="TestEvent",
                data={"index": i},
                metadata=sample_metadata,
                priority=i,
                correlation_id=f"corr-{i}" if i > 0 else None,
            )
            messages.append(msg)

        # Create FAILED messages
        for i in range(2):
            msg = Outbox.create_message(
                message_id=f"failed-message-{i}",
                stream_name=f"failed-stream-{i}",
                message_type="FailedEvent",
                data={"failed_index": i},
                metadata=sample_metadata,
                priority=i + 10,
            )
            msg.status = OutboxStatus.FAILED.value
            msg.retry_count = i + 1
            msg.next_retry_at = datetime.now(timezone.utc) - timedelta(
                minutes=5
            )  # Ready for retry
            messages.append(msg)

        # Create PUBLISHED messages
        for i in range(2):
            msg = Outbox.create_message(
                message_id=f"published-message-{i}",
                stream_name=f"published-stream-{i}",
                message_type="PublishedEvent",
                data={"published_index": i},
                metadata=sample_metadata,
                priority=i + 20,
            )
            msg.status = OutboxStatus.PUBLISHED.value
            msg.published_at = datetime.now(timezone.utc)
            messages.append(msg)

        # Create PROCESSING messages
        msg = Outbox.create_message(
            message_id="processing-source",
            stream_name="processing-stream",
            message_type="ProcessingEvent",
            data={"processing": True},
            metadata=sample_metadata,
            priority=30,
        )
        msg.status = OutboxStatus.PROCESSING.value
        msg.locked_by = "worker-1"
        msg.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        messages.append(msg)

        # Create ABANDONED message
        msg = Outbox.create_message(
            message_id="abandoned-source",
            stream_name="abandoned-stream",
            message_type="AbandonedEvent",
            data={"abandoned": True},
            metadata=sample_metadata,
            priority=40,
        )
        msg.status = OutboxStatus.ABANDONED.value
        msg.retry_count = 5
        messages.append(msg)

        # Persist all messages
        repo = test_domain.repository_for(Outbox)
        for msg in messages:
            repo.add(msg)

        return messages

    return _create_messages


class TestOutboxRepositoryBasicQueries:
    """Test basic repository query methods."""

    def test_find_unprocessed_returns_pending_messages(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_unprocessed returns PENDING and ready FAILED messages."""
        create_sample_messages()

        unprocessed = outbox_repo.find_unprocessed()

        # Should return 3 PENDING + 2 FAILED (ready for retry) = 5 messages
        assert len(unprocessed) == 5
        for msg in unprocessed:
            assert msg.status in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]
            assert msg.is_ready_for_processing()

    def test_find_unprocessed_includes_retry_ready_failed_messages(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_unprocessed includes FAILED messages ready for retry."""
        create_sample_messages()

        unprocessed = outbox_repo.find_unprocessed()

        # Should return 3 PENDING + 2 FAILED (ready for retry) = 5 messages
        assert len(unprocessed) == 5

        pending_count = sum(
            1 for msg in unprocessed if msg.status == OutboxStatus.PENDING.value
        )
        failed_count = sum(
            1 for msg in unprocessed if msg.status == OutboxStatus.FAILED.value
        )

        assert pending_count == 3
        assert failed_count == 2

    def test_find_unprocessed_respects_limit(self, outbox_repo, create_sample_messages):
        """Test that find_unprocessed respects the limit parameter."""
        create_sample_messages()

        unprocessed = outbox_repo.find_unprocessed(limit=2)

        assert len(unprocessed) == 2

    def test_find_unprocessed_orders_by_priority(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_unprocessed orders by priority (higher first)."""
        create_sample_messages()

        unprocessed = outbox_repo.find_unprocessed()

        # Should be ordered by priority descending
        priorities = [msg.priority for msg in unprocessed]
        assert priorities == sorted(priorities, reverse=True)

    def test_find_failed_returns_only_failed_messages(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_failed returns only FAILED messages."""
        create_sample_messages()

        failed = outbox_repo.find_failed()

        assert len(failed) == 2
        for msg in failed:
            assert msg.status == OutboxStatus.FAILED.value

    def test_find_abandoned_returns_only_abandoned_messages(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_abandoned returns only ABANDONED messages."""
        create_sample_messages()

        abandoned = outbox_repo.find_abandoned()

        assert len(abandoned) == 1
        assert abandoned[0].status == OutboxStatus.ABANDONED.value

    def test_find_published_returns_only_published_messages(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_published returns only PUBLISHED messages."""
        create_sample_messages()

        published = outbox_repo.find_published()

        assert len(published) == 2
        for msg in published:
            assert msg.status == OutboxStatus.PUBLISHED.value

    def test_find_processing_returns_only_processing_messages(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_processing returns only PROCESSING messages."""
        create_sample_messages()

        processing = outbox_repo.find_processing()

        assert len(processing) == 1
        assert processing[0].status == OutboxStatus.PROCESSING.value


class TestOutboxRepositoryFilterQueries:
    """Test repository filter query methods."""

    def test_find_by_stream_filters_correctly(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_stream filters by stream name."""
        create_sample_messages()

        stream_messages = outbox_repo.find_by_stream("stream-1")

        assert len(stream_messages) == 1
        assert stream_messages[0].stream_name == "stream-1"

    def test_find_by_message_id_filters_correctly(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_message_id filters by message ID."""
        create_sample_messages()

        message = outbox_repo.find_by_message_id("message-1")

        assert message is not None
        assert message.message_id == "message-1"

    def test_find_by_message_type_filters_correctly(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_message_type filters by message type."""
        create_sample_messages()

        type_messages = outbox_repo.find_by_message_type("TestEvent")

        assert len(type_messages) == 3
        for msg in type_messages:
            assert msg.type == "TestEvent"

    def test_find_by_priority_filters_correctly(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_priority filters by minimum priority."""
        create_sample_messages()

        high_priority = outbox_repo.find_by_priority(15)

        assert len(high_priority) == 4  # 2 published + 1 processing + 1 abandoned
        for msg in high_priority:
            assert msg.priority >= 15

    def test_find_by_correlation_id_filters_correctly(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_correlation_id filters by correlation ID."""
        create_sample_messages()

        corr_messages = outbox_repo.find_by_correlation_id("corr-1")

        assert len(corr_messages) == 1
        assert corr_messages[0].correlation_id == "corr-1"

    def test_find_by_correlation_id_handles_none(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_correlation_id handles None correlation ID."""
        create_sample_messages()

        # This should return empty list since we're searching for None as string
        corr_messages = outbox_repo.find_by_correlation_id(None)

        assert len(corr_messages) == 0


class TestOutboxRepositoryTimeBasedQueries:
    """Test time-based repository query methods."""

    def test_find_stale_processing_finds_old_processing_messages(
        self, outbox_repo, sample_metadata
    ):
        """Test that find_stale_processing finds messages processing for too long."""
        # Create a stale processing message (older than threshold)
        msg = Outbox.create_message(
            message_id="stale-source",
            stream_name="stale-stream",
            message_type="StaleEvent",
            data={"stale": True},
            metadata=sample_metadata,
        )
        msg.status = OutboxStatus.PROCESSING.value
        msg.locked_by = "worker-1"
        msg.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        msg.last_processed_at = datetime.now(timezone.utc) - timedelta(
            minutes=15
        )  # 15 minutes ago

        outbox_repo.add(msg)

        stale_messages = outbox_repo.find_stale_processing(stale_threshold_minutes=10)

        assert len(stale_messages) == 1
        assert stale_messages[0].status == OutboxStatus.PROCESSING.value

    def test_find_recent_finds_messages_within_timeframe(
        self, outbox_repo, sample_metadata
    ):
        """Test that find_recent finds messages within specified hours."""
        # Create a recent message
        recent_msg = Outbox.create_message(
            message_id="recent-source",
            stream_name="recent-stream",
            message_type="RecentEvent",
            data={"recent": True},
            metadata=sample_metadata,
        )

        # Create an old message
        old_msg = Outbox.create_message(
            message_id="old-source",
            stream_name="old-stream",
            message_type="OldEvent",
            data={"old": True},
            metadata=sample_metadata,
        )
        old_msg.created_at = datetime.now(timezone.utc) - timedelta(
            hours=48
        )  # 48 hours ago

        outbox_repo.add(recent_msg)
        outbox_repo.add(old_msg)

        recent_messages = outbox_repo.find_recent(hours=24)

        assert len(recent_messages) == 1
        assert recent_messages[0].message_id == "recent-source"

    def test_find_retry_ready_finds_failed_messages_past_retry_time(
        self, outbox_repo, sample_metadata
    ):
        """Test that find_retry_ready finds FAILED messages past retry time."""
        # Create a failed message ready for retry
        ready_msg = Outbox.create_message(
            message_id="retry-ready-source",
            stream_name="retry-ready-stream",
            message_type="RetryReadyEvent",
            data={"retry_ready": True},
            metadata=sample_metadata,
        )
        ready_msg.status = OutboxStatus.FAILED.value
        ready_msg.retry_count = 1
        ready_msg.next_retry_at = datetime.now(timezone.utc) - timedelta(
            minutes=5
        )  # 5 minutes ago

        # Create a failed message not ready for retry
        not_ready_msg = Outbox.create_message(
            message_id="retry-not-ready-source",
            stream_name="retry-not-ready-stream",
            message_type="RetryNotReadyEvent",
            data={"retry_not_ready": True},
            metadata=sample_metadata,
        )
        not_ready_msg.status = OutboxStatus.FAILED.value
        not_ready_msg.retry_count = 1
        not_ready_msg.next_retry_at = datetime.now(timezone.utc) + timedelta(
            minutes=5
        )  # 5 minutes from now

        outbox_repo.add(ready_msg)
        outbox_repo.add(not_ready_msg)

        retry_ready = outbox_repo.find_retry_ready()

        assert len(retry_ready) == 1
        assert retry_ready[0].message_id == "retry-ready-source"


class TestOutboxRepositoryAggregateQueries:
    """Test aggregate query methods."""

    def test_count_by_status_returns_correct_counts(
        self, outbox_repo, create_sample_messages
    ):
        """Test that count_by_status returns correct counts for each status."""
        create_sample_messages()

        counts = outbox_repo.count_by_status()

        assert counts[OutboxStatus.PENDING.value] == 3
        assert counts[OutboxStatus.FAILED.value] == 2
        assert counts[OutboxStatus.PUBLISHED.value] == 2
        assert counts[OutboxStatus.PROCESSING.value] == 1
        assert counts[OutboxStatus.ABANDONED.value] == 1

    def test_find_by_priority_default_finds_messages_with_priority_gte_one(
        self, outbox_repo, create_sample_messages
    ):
        """Test that find_by_priority with default min_priority=1 finds messages with priority >= 1."""
        create_sample_messages()

        high_priority = outbox_repo.find_by_priority()

        # Should exclude only the first message which has priority 0
        assert len(high_priority) == 8  # All messages except the first PENDING one
        for msg in high_priority:
            assert msg.priority > 0

    def test_cleanup_old_published_removes_old_published_messages(
        self, outbox_repo, sample_metadata
    ):
        """Test that cleanup_old_published removes old published messages."""
        # Create an old published message
        old_msg = Outbox.create_message(
            message_id="old-published-source",
            stream_name="old-published-stream",
            message_type="OldPublishedEvent",
            data={"old_published": True},
            metadata=sample_metadata,
        )
        old_msg.status = OutboxStatus.PUBLISHED.value
        old_msg.published_at = datetime.now(timezone.utc) - timedelta(
            hours=200
        )  # 200 hours ago

        # Create a recent published message
        recent_msg = Outbox.create_message(
            message_id="recent-published-source",
            stream_name="recent-published-stream",
            message_type="RecentPublishedEvent",
            data={"recent_published": True},
            metadata=sample_metadata,
        )
        recent_msg.status = OutboxStatus.PUBLISHED.value
        recent_msg.published_at = datetime.now(timezone.utc) - timedelta(
            hours=24
        )  # 24 hours ago

        outbox_repo.add(old_msg)
        outbox_repo.add(recent_msg)

        # Clean up messages older than 168 hours (1 week)
        deleted_count = outbox_repo.cleanup_old_published(older_than_hours=168)

        assert deleted_count == 1

        # Verify the old message is gone and recent one remains
        published_messages = outbox_repo.find_published()
        assert len(published_messages) == 1
        assert published_messages[0].message_id == "recent-published-source"


class TestOutboxRepositoryLimitAndOrdering:
    """Test limit and ordering behavior across different query methods."""

    def test_all_methods_respect_limit_parameter(
        self, outbox_repo, create_sample_messages
    ):
        """Test that all query methods respect the limit parameter."""
        create_sample_messages()

        # Test various methods with limit
        assert len(outbox_repo.find_failed(limit=1)) == 1
        assert len(outbox_repo.find_published(limit=1)) == 1
        assert len(outbox_repo.find_by_message_type("TestEvent", limit=1)) == 1
        assert len(outbox_repo.find_by_priority(0, limit=3)) == 3

    def test_queries_have_consistent_ordering(
        self, outbox_repo, create_sample_messages
    ):
        """Test that queries have consistent ordering."""
        create_sample_messages()

        # Test that unprocessed messages are ordered by priority DESC, created_at ASC
        unprocessed = outbox_repo.find_unprocessed()
        assert len(unprocessed) >= 2

        # Higher priority should come first
        for i in range(len(unprocessed) - 1):
            assert unprocessed[i].priority >= unprocessed[i + 1].priority

    def test_find_retry_ready_orders_by_priority_and_retry_time(
        self, outbox_repo, sample_metadata
    ):
        """Test that find_retry_ready orders by priority and retry time."""
        # Create multiple failed messages with different priorities and retry times
        for i in range(3):
            msg = Outbox.create_message(
                message_id=f"retry-message-{i}",
                stream_name=f"retry-stream-{i}",
                message_type="RetryEvent",
                data={"retry_index": i},
                metadata=sample_metadata,
                priority=i * 5,  # 0, 5, 10
            )
            msg.status = OutboxStatus.FAILED.value
            msg.retry_count = 1
            msg.next_retry_at = datetime.now(timezone.utc) - timedelta(
                minutes=i
            )  # Different retry times

            outbox_repo.add(msg)

        retry_ready = outbox_repo.find_retry_ready()

        assert len(retry_ready) == 3
        # Should be ordered by priority DESC first
        priorities = [msg.priority for msg in retry_ready]
        assert priorities == sorted(priorities, reverse=True)


class TestOutboxRepositoryEdgeCases:
    """Test edge cases and error conditions."""

    def test_queries_handle_empty_repository(self, outbox_repo):
        """Test that queries handle empty repository gracefully."""
        assert len(outbox_repo.find_unprocessed()) == 0
        assert len(outbox_repo.find_failed()) == 0
        assert len(outbox_repo.find_published()) == 0
        assert len(outbox_repo.find_abandoned()) == 0
        assert len(outbox_repo.find_processing()) == 0
        assert len(outbox_repo.find_recent()) == 0
        assert len(outbox_repo.find_retry_ready()) == 0
        assert len(outbox_repo.find_by_priority()) == 0

        counts = outbox_repo.count_by_status()
        for status in OutboxStatus:
            assert counts[status.value] == 0

    def test_cleanup_old_published_handles_no_old_messages(self, outbox_repo):
        """Test that cleanup_old_published handles case with no old messages."""
        deleted_count = outbox_repo.cleanup_old_published(older_than_hours=1)
        assert deleted_count == 0

    def test_find_by_stream_handles_non_existent_stream(self, outbox_repo):
        """Test that find_by_stream handles non-existent stream gracefully."""
        messages = outbox_repo.find_by_stream("non-existent-stream")
        assert len(messages) == 0

    def test_queries_with_zero_limit(self, outbox_repo, create_sample_messages):
        """Test that queries handle zero limit."""
        create_sample_messages()

        # Zero limit should return empty list
        assert len(outbox_repo.find_unprocessed(limit=0)) == 0
        assert len(outbox_repo.find_failed(limit=0)) == 0
        assert len(outbox_repo.find_published(limit=0)) == 0

    def test_find_stale_processing_with_zero_threshold(
        self, outbox_repo, sample_metadata
    ):
        """Test find_stale_processing with zero threshold."""
        # Create a processing message
        msg = Outbox.create_message(
            message_id="processing-source",
            stream_name="processing-stream",
            message_type="ProcessingEvent",
            data={"processing": True},
            metadata=sample_metadata,
        )
        msg.status = OutboxStatus.PROCESSING.value
        msg.locked_by = "worker-1"
        msg.last_processed_at = datetime.now(timezone.utc)

        outbox_repo.add(msg)

        # With zero threshold, should find all processing messages
        stale_messages = outbox_repo.find_stale_processing(stale_threshold_minutes=0)
        assert len(stale_messages) >= 1
