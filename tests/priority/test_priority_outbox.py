"""Tests for outbox priority storage — unit tests of the Outbox model"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Integer, String
from protean.utils.eventing import Metadata, MessageHeaders, DomainMeta
from protean.utils.outbox import Outbox, OutboxStatus


class DummyAggregate(BaseAggregate):
    name: String(max_length=50, required=True)
    count: Integer(default=0)


class DummyEvent(BaseEvent):
    aggregate_id: String(required=True)
    name: String(required=True)
    count: Integer(required=True)


def _make_metadata(msg_id, stream_category="test-stream"):
    """Helper to build a minimal Metadata object."""
    headers = MessageHeaders(id=msg_id, type="DummyEvent", stream="test-stream")
    domain_meta = DomainMeta(stream_category=stream_category)
    return Metadata(headers=headers, domain=domain_meta)


def _create_outbox_message(msg_id, priority=0, stream_category="test-stream"):
    """Helper to create an Outbox message with a given priority."""
    return Outbox.create_message(
        message_id=msg_id,
        stream_name="test-stream",
        message_type="DummyEvent",
        data={"name": f"Test {msg_id}", "count": 1},
        metadata=_make_metadata(msg_id, stream_category),
        priority=priority,
        correlation_id=f"corr-{msg_id}",
        trace_id=f"trace-{msg_id}",
    )


@pytest.fixture
def outbox_domain(test_domain):
    """`test_domain` fixture with outbox enabled."""
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"

    test_domain.register(DummyAggregate)
    test_domain.register(DummyEvent, part_of=DummyAggregate)
    test_domain.init(traverse=False)

    return test_domain


@pytest.mark.database
class TestOutboxPriorityStorage:
    """Unit tests for the Outbox model's priority field."""

    def test_outbox_create_message_with_priority(self, outbox_domain):
        """Outbox.create_message(..., priority=-50) stores the priority correctly."""
        message = _create_outbox_message("neg-50", priority=-50)

        assert message.priority == -50
        assert message.status == OutboxStatus.PENDING.value
        assert message.message_id == "neg-50"

        # Persist and re-read to ensure the field round-trips
        outbox_repo = outbox_domain._get_outbox_repo("default")
        outbox_repo.add(message)

        fetched = outbox_repo.get(message.id)
        assert fetched.priority == -50

    def test_outbox_default_priority_is_zero(self, outbox_domain):
        """Without an explicit priority, the default is 0."""
        metadata = _make_metadata("default-prio")
        message = Outbox.create_message(
            message_id="default-prio",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"name": "Default"},
            metadata=metadata,
        )

        assert message.priority == 0

        # Persist and verify
        outbox_repo = outbox_domain._get_outbox_repo("default")
        outbox_repo.add(message)

        fetched = outbox_repo.get(message.id)
        assert fetched.priority == 0

    def test_outbox_find_unprocessed_orders_by_priority(self, outbox_domain):
        """find_unprocessed returns messages ordered by priority descending (higher first)."""
        outbox_repo = outbox_domain._get_outbox_repo("default")

        # Insert low-priority first, then high-priority
        low = _create_outbox_message("low", priority=-10)
        mid = _create_outbox_message("mid", priority=0)
        high = _create_outbox_message("high", priority=50)

        outbox_repo.add(low)
        outbox_repo.add(mid)
        outbox_repo.add(high)

        messages = outbox_repo.find_unprocessed()

        assert len(messages) == 3
        # Highest priority should be returned first
        assert messages[0].message_id == "high"
        assert messages[1].message_id == "mid"
        assert messages[2].message_id == "low"

    def test_outbox_mixed_priorities_processing_order(self, outbox_domain):
        """Insert 5 LOW, 3 NORMAL, 2 HIGH -- find_unprocessed returns HIGH first."""
        outbox_repo = outbox_domain._get_outbox_repo("default")

        # 5 LOW priority messages (priority = -50)
        for i in range(5):
            outbox_repo.add(_create_outbox_message(f"low-{i}", priority=-50))

        # 3 NORMAL priority messages (priority = 0)
        for i in range(3):
            outbox_repo.add(_create_outbox_message(f"normal-{i}", priority=0))

        # 2 HIGH priority messages (priority = 50)
        for i in range(2):
            outbox_repo.add(_create_outbox_message(f"high-{i}", priority=50))

        messages = outbox_repo.find_unprocessed()

        assert len(messages) == 10

        # First 2 should be HIGH
        high_messages = messages[:2]
        for msg in high_messages:
            assert msg.priority == 50
            assert msg.message_id.startswith("high-")

        # Next 3 should be NORMAL
        normal_messages = messages[2:5]
        for msg in normal_messages:
            assert msg.priority == 0
            assert msg.message_id.startswith("normal-")

        # Last 5 should be LOW
        low_messages = messages[5:]
        for msg in low_messages:
            assert msg.priority == -50
            assert msg.message_id.startswith("low-")

    def test_outbox_find_by_priority_filter(self, outbox_domain):
        """find_by_priority(min_priority=50) returns only HIGH and CRITICAL."""
        outbox_repo = outbox_domain._get_outbox_repo("default")

        outbox_repo.add(_create_outbox_message("low", priority=-50))
        outbox_repo.add(_create_outbox_message("normal", priority=0))
        outbox_repo.add(_create_outbox_message("high", priority=50))
        outbox_repo.add(_create_outbox_message("critical", priority=100))

        # Only messages with priority >= 50
        results = outbox_repo.find_by_priority(min_priority=50)

        assert len(results) == 2
        message_ids = {msg.message_id for msg in results}
        assert message_ids == {"high", "critical"}

        # Results should be ordered by priority descending
        assert results[0].priority >= results[1].priority

    def test_outbox_update_priority(self, outbox_domain):
        """update_priority changes priority for PENDING messages."""
        outbox_repo = outbox_domain._get_outbox_repo("default")

        message = _create_outbox_message("updatable", priority=0)
        outbox_repo.add(message)

        assert message.priority == 0

        # Update the priority
        message.update_priority(75)
        outbox_repo.add(message)

        fetched = outbox_repo.get(message.id)
        assert fetched.priority == 75

    def test_outbox_update_priority_ignored_for_published(self, outbox_domain):
        """Cannot change the priority of published messages."""
        outbox_repo = outbox_domain._get_outbox_repo("default")

        message = _create_outbox_message("published-msg", priority=10)
        message.mark_published()  # Transition to PUBLISHED state
        outbox_repo.add(message)

        # Attempt to update priority -- should be silently ignored
        message.update_priority(99)

        assert message.priority == 10  # Priority remains unchanged
