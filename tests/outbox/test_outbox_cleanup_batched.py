"""Tests for batched outbox cleanup.

``cleanup_old_published`` / ``cleanup_old_abandoned`` delete in bounded batches
via ``BaseDAO._delete_top`` instead of one unbounded ``DELETE``. The batch size
comes from the ``batch_size`` argument, falling back to ``[outbox.cleanup]``
config (default 5000).
"""

from datetime import UTC, datetime, timedelta

import pytest

from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxRepository, OutboxStatus


@pytest.fixture(autouse=True)
def setup_outbox_domain(test_domain):
    test_domain.register(Outbox)
    test_domain.register(OutboxRepository, part_of=Outbox)
    test_domain.init(traverse=False)
    return test_domain


@pytest.fixture
def sample_metadata():
    return Metadata(
        headers=MessageHeaders(
            id="test-id",
            type="TestEvent",
            time=datetime.now(UTC),
            stream="test-stream",
        ),
        domain=DomainMeta(
            fqn="test.TestEvent",
            kind="event",
            origin_stream="test-aggregate-123",
            version="1.0",
            sequence_id="1",
        ),
    )


@pytest.fixture
def outbox_repo(test_domain):
    return test_domain.repository_for(Outbox)


@pytest.fixture
def make_messages(outbox_repo, sample_metadata):
    """Factory: add ``count`` messages of ``status`` aged ``hours_old``."""

    def _make(count, status=OutboxStatus.PUBLISHED.value, hours_old=200):
        aged = datetime.now(UTC) - timedelta(hours=hours_old)
        for i in range(count):
            msg = Outbox.create_message(
                message_id=f"msg-{status}-{hours_old}-{i}",
                stream_name="stream",
                message_type="TestEvent",
                data={"i": i},
                metadata=sample_metadata,
            )
            msg.status = status
            if status == OutboxStatus.PUBLISHED.value:
                msg.published_at = aged
            else:  # ABANDONED
                msg.last_processed_at = aged
            outbox_repo.add(msg)

    return _make


@pytest.fixture
def batch_spy(outbox_repo):
    """Wrap ``_delete_top`` to record the size of every batch it deletes."""
    calls = []
    original = outbox_repo._dao._delete_top

    def spy(criteria, limit, order_by=None):
        deleted = original(criteria, limit, order_by)
        calls.append(deleted)
        return deleted

    outbox_repo._dao._delete_top = spy
    return calls


class TestBatchedCleanup:
    def test_backlog_larger_than_batch_runs_multiple_batches(
        self, outbox_repo, make_messages, batch_spy
    ):
        make_messages(5)

        deleted = outbox_repo.cleanup_old_published(older_than_hours=168, batch_size=2)

        assert deleted == 5
        # 5 rows at batch_size 2: two full batches then a short one stops the loop.
        assert batch_spy == [2, 2, 1]
        assert outbox_repo._dao.query.count() == 0

    def test_backlog_smaller_than_batch_runs_single_batch(
        self, outbox_repo, make_messages, batch_spy
    ):
        make_messages(3)

        deleted = outbox_repo.cleanup_old_published(older_than_hours=168, batch_size=10)

        assert deleted == 3
        assert batch_spy == [3]

    def test_batch_size_falls_back_to_config(
        self, test_domain, outbox_repo, make_messages, batch_spy
    ):
        test_domain.config["outbox"]["cleanup"]["batch_size"] = 2
        make_messages(5)

        # No explicit batch_size: the [outbox.cleanup] config value is used.
        deleted = outbox_repo.cleanup_old_published(older_than_hours=168)

        assert deleted == 5
        assert batch_spy == [2, 2, 1]

    def test_only_eligible_rows_are_deleted(self, outbox_repo, make_messages):
        make_messages(3, hours_old=200)  # old → eligible
        make_messages(2, hours_old=24)  # recent → retained

        deleted = outbox_repo.cleanup_old_published(older_than_hours=168, batch_size=2)

        assert deleted == 3
        assert len(outbox_repo.find_published()) == 2

    def test_cleanup_old_abandoned_batches(self, outbox_repo, make_messages, batch_spy):
        make_messages(4, status=OutboxStatus.ABANDONED.value, hours_old=800)

        deleted = outbox_repo.cleanup_old_abandoned(older_than_hours=720, batch_size=2)

        assert deleted == 4
        # 4 rows is an exact multiple of the batch size, so the loop runs one
        # trailing empty batch before it can tell the table is drained.
        assert batch_spy == [2, 2, 0]
        assert outbox_repo._dao.query.count() == 0

    def test_cleanup_old_messages_threads_batch_size(
        self, outbox_repo, make_messages, batch_spy
    ):
        make_messages(3, status=OutboxStatus.PUBLISHED.value, hours_old=200)
        make_messages(3, status=OutboxStatus.ABANDONED.value, hours_old=800)

        result = outbox_repo.cleanup_old_messages(batch_size=2)

        assert result == {"published": 3, "abandoned": 3, "total": 6}
        # Published: [2, 1]; abandoned: [2, 1].
        assert batch_spy == [2, 1, 2, 1]
