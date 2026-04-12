"""Tests for structured logging in OutboxProcessor.

Verifies that:
- outbox.batch_completed is logged at INFO with total, successful, failed counts
- outbox.publish_failed is logged at WARNING with message_id, error_type, error
- outbox.processing_error is logged at ERROR with exc_info
"""

import asyncio
import logging
from unittest.mock import Mock

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Integer, String
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox


class DummyAggregate(BaseAggregate):
    name = String(max_length=50, required=True)
    count = Integer(default=0)


class DummyEvent(BaseEvent):
    aggregate_id = String(required=True)
    name = String(required=True)
    count = Integer(required=True)


class MockEngine:
    """Minimal mock engine for outbox processor testing."""

    def __init__(self, domain):
        self.domain = domain
        self.loop = None
        self.shutting_down = False
        self.emitter = Mock()


def _make_outbox_message(msg_id: str) -> Outbox:
    """Create a test outbox message."""
    headers = MessageHeaders(id=msg_id, type="DummyEvent", stream="test-stream")
    domain_meta = DomainMeta(stream_category="test-stream")
    metadata = Metadata(headers=headers, domain=domain_meta)

    return Outbox.create_message(
        message_id=msg_id,
        stream_name="test-stream",
        message_type="DummyEvent",
        data={"aggregate_id": "1", "name": "test", "count": 1},
        metadata=metadata,
        priority=100,
    )


@pytest.fixture
def outbox_domain(test_domain):
    """Domain with outbox enabled."""
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.register(DummyAggregate)
    test_domain.register(DummyEvent, part_of=DummyAggregate)
    test_domain.init(traverse=False)
    return test_domain


class TestOutboxBatchCompletedLog:
    """outbox.batch_completed is logged at INFO."""

    @pytest.fixture
    def processor(self, outbox_domain):
        engine = MockEngine(outbox_domain)
        return OutboxProcessor(
            engine,
            database_provider_name="default",
            broker_provider_name="default",
        )

    def test_batch_completed_log(self, outbox_domain, processor, caplog):
        """Processing a batch logs 'outbox.batch_completed' at INFO with counts."""
        messages = [_make_outbox_message("msg-1"), _make_outbox_message("msg-2")]

        # Mock the _process_single_message to simulate one success and one failure
        results = iter([True, False])

        async def mock_process(msg):
            return next(results)

        processor._process_single_message = mock_process

        with caplog.at_level(logging.DEBUG, logger="protean.server.outbox_processor"):
            asyncio.run(processor.process_batch(messages))

        batch_records = [
            r for r in caplog.records if "outbox.batch_completed" in r.getMessage()
        ]
        assert len(batch_records) >= 1, (
            f"Expected 'outbox.batch_completed' in log records, "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )
        record = batch_records[0]
        assert record.levelno == logging.INFO
        assert record.total == 2
        assert record.successful == 1
        assert record.failed == 1


class TestOutboxPublishFailedLog:
    """outbox.publish_failed is logged at WARNING."""

    @pytest.fixture
    def processor(self, outbox_domain):
        engine = MockEngine(outbox_domain)
        proc = OutboxProcessor(
            engine,
            database_provider_name="default",
            broker_provider_name="default",
        )
        proc.broker = outbox_domain.brokers["default"]
        proc.outbox_repo = outbox_domain._get_outbox_repo("default")
        return proc

    def test_publish_failed_log(self, outbox_domain, processor, caplog):
        """A publish failure logs 'outbox.publish_failed' at WARNING."""
        message = _make_outbox_message("msg-fail")

        # Mock the publish to fail
        async def mock_publish(msg):
            return False, RuntimeError("connection refused")

        # Mock claim_for_processing to succeed
        processor.outbox_repo.claim_for_processing = Mock(return_value=True)
        processor.outbox_repo.get = Mock(return_value=message)
        processor.outbox_repo.add = Mock()
        processor._publish_message = mock_publish

        with caplog.at_level(logging.DEBUG, logger="protean.server.outbox_processor"):
            asyncio.run(
                processor._process_single_message(message)
            )

        publish_failed_records = [
            r for r in caplog.records if "outbox.publish_failed" in r.getMessage()
        ]
        assert len(publish_failed_records) >= 1, (
            f"Expected 'outbox.publish_failed' in log records, "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )
        record = publish_failed_records[0]
        assert record.levelno == logging.WARNING


class TestOutboxProcessingErrorLog:
    """outbox.processing_error is logged at ERROR with exc_info."""

    @pytest.fixture
    def processor(self, outbox_domain):
        engine = MockEngine(outbox_domain)
        proc = OutboxProcessor(
            engine,
            database_provider_name="default",
            broker_provider_name="default",
        )
        proc.broker = outbox_domain.brokers["default"]
        proc.outbox_repo = outbox_domain._get_outbox_repo("default")
        return proc

    def test_processing_error_log(self, outbox_domain, processor, caplog):
        """An unhandled processing error logs 'outbox.processing_error' at ERROR
        with exc_info populated."""
        message = _make_outbox_message("msg-crash")

        # Mock claim to raise an unexpected error
        processor.outbox_repo.claim_for_processing = Mock(
            side_effect=RuntimeError("database connection lost")
        )

        with caplog.at_level(logging.DEBUG, logger="protean.server.outbox_processor"):
            result = asyncio.get_event_loop().run_until_complete(
                processor._process_single_message(message)
            )

        assert result is False

        error_records = [
            r for r in caplog.records if "outbox.processing_error" in r.getMessage()
        ]
        assert len(error_records) >= 1, (
            f"Expected 'outbox.processing_error' in log records, "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )
        record = error_records[0]
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None, "exc_info must be populated for stack trace"
