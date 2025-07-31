"""Test OutboxProcessor functionality"""

import asyncio
import pytest
from unittest.mock import Mock, patch

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import String, Integer
from protean.server import Engine
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.outbox import Outbox, OutboxStatus, ProcessingResult
from protean.utils.eventing import Metadata


class MockEngine:
    """Simple mock engine that provides only the necessary interface for testing"""

    def __init__(self, domain):
        self.domain = domain
        self.loop = None


class DummyAggregate(BaseAggregate):
    """Test aggregate for outbox testing"""

    name = String(max_length=50, required=True)
    count = Integer(default=0)

    def increment(self):
        self.count += 1
        self.raise_(DummyEvent(aggregate_id=self.id, name=self.name, count=self.count))


class DummyEvent(BaseEvent):
    """Test event for outbox testing"""

    aggregate_id = String(required=True)
    name = String(required=True)
    count = Integer(required=True)


@pytest.fixture
def outbox_test_domain(test_domain):
    """`test_domain` fixture recreated to enable outbox for testing."""

    test_domain.config["enable_outbox"] = True

    # Register test elements
    test_domain.register(DummyAggregate)
    test_domain.register(DummyEvent, part_of=DummyAggregate)
    test_domain.init(traverse=False)

    return test_domain


def persist_outbox_messages(outbox_test_domain):
    """Create test outbox messages"""
    outbox_repo = outbox_test_domain._get_outbox_repo("default")

    messages = []
    for i in range(3):
        metadata = Metadata()
        message = Outbox.create_message(
            message_id=f"msg-{i}",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"name": f"Test {i}", "count": i},
            metadata=metadata,
            priority=i,
            correlation_id=f"corr-{i}",
            trace_id=f"trace-{i}",
        )
        outbox_repo.add(message)
        messages.append(message)

    return messages


@pytest.mark.database
class TestOutboxProcessor:
    """Test the OutboxProcessor functionality"""

    def test_outbox_processor_initialization(self, outbox_test_domain):
        """Test that OutboxProcessor can be initialized correctly"""
        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(
            engine=engine,
            database_provider_name="default",
            broker_provider_name="default",
            messages_per_tick=5,
            tick_interval=2,
        )

        assert processor.database_provider_name == "default"
        assert processor.broker_provider_name == "default"
        assert processor.messages_per_tick == 5
        assert processor.tick_interval == 2
        assert processor.worker_id is not None
        assert processor.broker is None  # Not initialized yet
        assert processor.outbox_repo is None  # Not initialized yet

    def test_outbox_processor_initialization_with_invalid_broker_provider(
        self, outbox_test_domain
    ):
        """Test OutboxProcessor initialization with invalid broker provider raises error"""
        # Create a domain with limited broker configuration
        from protean.domain import Domain

        domain = Domain(name="TestInvalidProvider")
        domain.config["brokers"]["default"] = {"provider": "inline"}
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "nonexistent")

            with pytest.raises(
                ValueError, match="Broker provider 'nonexistent' not configured"
            ):
                asyncio.run(processor.initialize())

    def test_outbox_processor_initialization_with_missing_outbox_repository(
        self, outbox_test_domain
    ):
        """Test OutboxProcessor initialization when outbox repository is not found raises error"""
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "nonexistent_db", "default")

        # Mock _get_outbox_repo to return None to simulate missing repository
        with patch.object(outbox_test_domain, "_get_outbox_repo", return_value=None):
            with pytest.raises(
                ValueError,
                match="Outbox repository for database provider 'nonexistent_db' not found",
            ):
                asyncio.run(processor.initialize())

    @pytest.mark.asyncio
    async def test_outbox_processor_async_initialization(self, outbox_test_domain):
        """Test OutboxProcessor async initialization"""
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        assert processor.broker is not None
        assert processor.outbox_repo is not None
        assert processor.broker == outbox_test_domain.brokers["default"]

    @pytest.mark.asyncio
    async def test_get_next_batch_of_messages_empty(self, outbox_test_domain):
        """Test getting messages when outbox is empty"""
        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default", messages_per_tick=5)
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        assert messages == []

    @pytest.mark.asyncio
    async def test_get_next_batch_of_messages_when_repo_not_initialized(self):
        """Test getting messages when outbox_repo is None"""
        engine = MockEngine(None)

        processor = OutboxProcessor(engine, "default", "default", messages_per_tick=5)
        # Don't call initialize() so outbox_repo remains None

        messages = await processor.get_next_batch_of_messages()
        assert messages == []

    @pytest.mark.asyncio
    async def test_get_next_batch_of_messages_with_data(self, outbox_test_domain):
        """Test getting messages when outbox has data"""
        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default", messages_per_tick=2)
        await processor.initialize()

        messages = await processor.get_next_batch_of_messages()
        assert len(messages) <= 2  # Limited by messages_per_tick
        assert all(msg.status == OutboxStatus.PENDING.value for msg in messages)

    @pytest.mark.asyncio
    async def test_publish_message_success(self, outbox_test_domain):
        """Test successful message publishing"""
        messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker publish to return success
        with patch.object(processor.broker, "publish", return_value="broker-msg-id"):
            success = await processor._publish_message(messages[0])
            assert success is True

    @pytest.mark.asyncio
    async def test_publish_message_failure(self, outbox_test_domain):
        """Test message publishing failure"""
        messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker publish to raise exception
        with patch.object(
            processor.broker, "publish", side_effect=Exception("Broker error")
        ):
            success = await processor._publish_message(messages[0])
            assert success is False

    @pytest.mark.asyncio
    async def test_process_batch_success(self, outbox_test_domain):
        """Test successful batch processing"""
        messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker publish to always succeed
        with patch.object(processor.broker, "publish", return_value="broker-msg-id"):
            successful_count = await processor.process_batch(messages[:2])
            assert successful_count == 2

            # Verify messages are marked as published
            outbox_repo = outbox_test_domain._get_outbox_repo("default")
            for i in range(2):
                updated_msg = outbox_repo.get(messages[i].id)
                assert updated_msg.status == OutboxStatus.PUBLISHED.value
                assert updated_msg.published_at is not None

    @pytest.mark.asyncio
    async def test_process_batch_failure(self, outbox_test_domain):
        """Test batch processing with failures"""
        messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker publish to always fail
        with patch.object(
            processor.broker, "publish", side_effect=Exception("Broker error")
        ):
            successful_count = await processor.process_batch(messages[:2])
            assert successful_count == 0

            # Verify messages are marked as failed
            outbox_repo = outbox_test_domain._get_outbox_repo("default")
            for i in range(2):
                updated_msg = outbox_repo.get(messages[i].id)
                assert updated_msg.status == OutboxStatus.FAILED.value
                assert updated_msg.retry_count == 1
                assert updated_msg.last_error is not None

    @pytest.mark.asyncio
    async def test_process_batch_mixed_results(self, outbox_test_domain):
        """Test batch processing with mixed success/failure results"""
        outbox_messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker publish to succeed for first message, fail for second
        def mock_publish(stream_name, message_payload):
            if message_payload["id"] == "msg-0":
                return "broker-msg-id"
            else:
                raise Exception("Broker error")

        with patch.object(processor.broker, "publish", side_effect=mock_publish):
            successful_count = await processor.process_batch(outbox_messages[:2])
            assert successful_count == 1

            # Verify first message is published, second is failed
            outbox_repo = outbox_test_domain._get_outbox_repo("default")

            msg_0 = outbox_repo.get(outbox_messages[0].id)
            assert msg_0.status == OutboxStatus.PUBLISHED.value

            msg_1 = outbox_repo.get(outbox_messages[1].id)
            assert msg_1.status == OutboxStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_process_batch_concurrent_processing_protection(
        self, outbox_test_domain
    ):
        """Test that messages are protected from concurrent processing"""
        outbox_messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Manually mark first message as processing by another worker
        message = outbox_messages[0]
        message.start_processing("other-worker")
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        outbox_repo.add(message)

        # Processing should skip locked messages
        with patch.object(processor.broker, "publish", return_value="broker-msg-id"):
            successful_count = await processor.process_batch([message])
            assert successful_count == 0  # Message was locked, so not processed

    @pytest.mark.asyncio
    async def test_process_batch_save_failure_during_error_handling(
        self, outbox_test_domain
    ):
        """Test exception handling when saving failed message status fails"""
        outbox_messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = outbox_messages[0]

        # Mock broker to raise exception during publish
        with patch.object(
            processor.broker, "publish", side_effect=Exception("Broker error")
        ):
            # Mock the outbox_repo.add to raise exception when saving failed status
            original_add = processor.outbox_repo.add
            call_count = 0

            def failing_add(msg):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First call (saving processing status) succeeds
                    return original_add(msg)
                else:
                    # Second call (saving failed status) fails
                    raise Exception("Database save error")

            with patch.object(processor.outbox_repo, "add", side_effect=failing_add):
                # This should handle the exception gracefully
                successful_count = await processor.process_batch([message])
                assert successful_count == 0  # No messages processed successfully

    @pytest.mark.asyncio
    async def test_process_batch_exception_during_processing_and_nested_save_failure(
        self, outbox_test_domain
    ):
        """Test exception handling when an exception during processing and nested save failure occur"""
        outbox_messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = outbox_messages[0]

        # Create a scenario where _publish_message throws an exception (triggering the outer except)
        # and then add() in the nested try/catch also throws an exception
        with patch.object(
            processor, "_publish_message", side_effect=Exception("Publish error")
        ):
            # Track calls to add() to make the second one fail
            original_add = processor.outbox_repo.add
            add_call_count = 0

            def track_and_fail_add(msg):
                nonlocal add_call_count
                add_call_count += 1
                if add_call_count == 2:  # Second call (in nested try/catch) should fail
                    raise Exception("Save error in nested handler")
                return original_add(msg)

            with patch.object(
                processor.outbox_repo, "add", side_effect=track_and_fail_add
            ):
                # This should trigger the nested exception handler on lines 156-157
                successful_count = await processor.process_batch([message])
                assert successful_count == 0

    @pytest.mark.asyncio
    async def test_process_batch_nested_exception_handler_coverage(
        self, outbox_test_domain
    ):
        """Test that covers the nested exception handler when both mark_failed and save fail"""
        engine = MockEngine(outbox_test_domain)

        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Create a broken message that will fail during processing
        broken_message = Mock()
        broken_message.message_id = "broken-msg"
        broken_message.start_processing = Mock(
            return_value=(True, ProcessingResult.SUCCESS)
        )
        broken_message.mark_failed = Mock()  # mark_failed should succeed

        # Make _publish_message fail to trigger the outer exception handler
        with patch.object(
            processor, "_publish_message", side_effect=Exception("Publish error")
        ):
            # Also make the repository add fail in the nested try/catch (after mark_failed succeeds)
            with patch.object(
                processor.outbox_repo, "add", side_effect=Exception("Repository error")
            ):
                # This should trigger lines 156-157: mark_failed succeeds but add fails
                successful_count = await processor.process_batch([broken_message])
                assert successful_count == 0
                # Verify mark_failed was called and succeeded
                broken_message.mark_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_message_payload_format(self, outbox_test_domain):
        """Test that message payload is formatted correctly for broker"""
        outbox_messages = persist_outbox_messages(outbox_test_domain)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        message = outbox_messages[0]

        # Mock broker to capture the payload - this mock is necessary to intercept the payload
        mock_broker = Mock()
        mock_broker.publish = Mock(return_value="broker-msg-id")
        processor.broker = mock_broker

        await processor._publish_message(message)

        # Verify the publish call was made with correct payload
        mock_broker.publish.assert_called_once()
        call_args = mock_broker.publish.call_args
        stream_name, payload = call_args[0]

        assert stream_name == message.stream_name
        assert payload["id"] == message.message_id
        assert payload["type"] == message.type
        assert payload["data"] == message.data
        assert payload["correlation_id"] == message.correlation_id
        assert payload["trace_id"] == message.trace_id
        assert "created_at" in payload


@pytest.mark.database
class TestEngineIntegration:
    """Test OutboxProcessor integration with Engine"""

    def test_engine_initializes_outbox_processors(self, outbox_test_domain):
        """Test that Engine initializes outbox processors for all database-broker provider combinations"""
        engine = Engine(outbox_test_domain, test_mode=True)

        # Engine should create outbox processors for each database-broker provider combination
        assert hasattr(engine, "_outbox_processors")

        # Dynamically calculate the expected number of outbox processors
        database_providers = outbox_test_domain.config.get("databases", [])
        broker_providers = outbox_test_domain.config.get("brokers", [])
        expected_combinations = [
            f"outbox-processor-{db}-to-{broker}"
            for db in database_providers
            for broker in broker_providers
        ]

        # Assert the number of outbox processors matches the expected combinations
        assert len(engine._outbox_processors) == len(expected_combinations)

        # Assert that all expected processor names are present
        processor_names = list(engine._outbox_processors.keys())
        for expected in expected_combinations:
            assert expected in processor_names

    def test_engine_starts_outbox_processors(self, outbox_test_domain):
        """Test that Engine starts outbox processors during run"""
        engine = Engine(outbox_test_domain, test_mode=True)

        # Track call counts instead of using mocks - this is necessary to verify start was called
        call_counts = {}
        original_starts = {}

        async def mock_start(processor_name):
            call_counts[processor_name] = call_counts.get(processor_name, 0) + 1

        for name, processor in engine._outbox_processors.items():
            original_starts[name] = processor.start
            processor.start = lambda p=name: mock_start(p)

        # Run engine (in test mode it exits immediately)
        engine.run()

        # Verify all processors were started
        assert len(call_counts) == len(engine._outbox_processors)
        for count in call_counts.values():
            assert count == 1

    @pytest.mark.asyncio
    async def test_engine_shuts_down_outbox_processors(self, outbox_test_domain):
        """Test that Engine properly shuts down outbox processors"""
        engine = Engine(outbox_test_domain, test_mode=True)

        # Track shutdown calls without using Mock objects
        shutdown_counts = {}

        async def track_shutdown(processor_name):
            shutdown_counts[processor_name] = shutdown_counts.get(processor_name, 0) + 1

        for name, processor in engine._outbox_processors.items():
            processor.shutdown = lambda p=name: track_shutdown(p)

        # Trigger shutdown
        await engine.shutdown()

        # Verify all processors were shut down
        assert len(shutdown_counts) == len(engine._outbox_processors)
        for count in shutdown_counts.values():
            assert count == 1

    def test_engine_no_crash_when_no_brokers_configured(self):
        """Test Engine doesn't crash when no brokers are configured"""
        from protean.domain import Domain

        domain = Domain(name="NoBrokerTest")
        # Keep default inline broker but create empty brokers dict after init
        domain.init(traverse=False)

        with domain.domain_context():
            # Temporarily clear brokers after initialization
            original_brokers = domain.brokers._brokers.copy()
            domain.brokers._brokers.clear()

            engine = Engine(domain, test_mode=True)
            assert len(engine._outbox_processors) == 0

            # Restore brokers
            domain.brokers._brokers.update(original_brokers)


@pytest.mark.database
class TestOutboxProcessorEndToEnd:
    """End-to-end tests with real outbox processing"""

    def test_full_outbox_processing_cycle(self, outbox_test_domain):
        """Test the full cycle of outbox message processing"""
        # Create test aggregate and trigger event
        aggregate = DummyAggregate(name="Test Aggregate", count=0)

        # Use UnitOfWork to trigger outbox storage
        with UnitOfWork():
            repo = outbox_test_domain.repository_for(DummyAggregate)
            repo.add(aggregate)
            aggregate.increment()  # This raises an event

        # Verify event was stored in outbox
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        unprocessed_messages = outbox_repo.find_unprocessed()
        assert len(unprocessed_messages) == 1

        message = unprocessed_messages[0]
        assert message.status == OutboxStatus.PENDING.value
        assert "DummyEvent" in message.type  # Type includes domain name and version

        # Run engine to process outbox messages
        engine = Engine(outbox_test_domain, test_mode=True)
        engine.run()

        # Verify message was processed and published
        updated_message = outbox_repo.get(message.id)
        assert updated_message.status == OutboxStatus.PUBLISHED.value
        assert updated_message.published_at is not None

    def test_outbox_processor_respects_message_per_tick_limit(self, outbox_test_domain):
        """Test that processor respects the messages_per_tick limit"""
        # Create multiple outbox messages
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        for i in range(5):
            metadata = Metadata()
            message = Outbox.create_message(
                message_id=f"batch-msg-{i}",
                stream_name="test-stream",
                message_type="DummyEvent",
                data={"name": f"Test {i}"},
                metadata=metadata,
            )
            outbox_repo.add(message)

        # Create processor with low messages_per_tick
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default", messages_per_tick=2)

        asyncio.run(processor.initialize())

        # Get batch should respect limit
        messages = asyncio.run(processor.get_next_batch_of_messages())
        assert len(messages) <= 2

    def test_outbox_processor_handles_message_priorities(self, outbox_test_domain):
        """Test that processor handles message priorities correctly"""
        # Create outbox messages with different priorities
        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        # Create low priority message first
        metadata_low = Metadata()
        message_low = Outbox.create_message(
            message_id="low-priority",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"priority": "low"},
            metadata=metadata_low,
            priority=1,
        )
        outbox_repo.add(message_low)

        # Create high priority message second
        metadata_high = Metadata()
        message_high = Outbox.create_message(
            message_id="high-priority",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"priority": "high"},
            metadata=metadata_high,
            priority=10,
        )
        outbox_repo.add(message_high)

        # Get next batch - should return high priority first
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default", messages_per_tick=1)
        asyncio.run(processor.initialize())

        messages = asyncio.run(processor.get_next_batch_of_messages())
        assert len(messages) == 1
        assert messages[0].message_id == "high-priority"  # Higher priority comes first
