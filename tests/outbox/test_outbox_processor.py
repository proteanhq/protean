"""Test OutboxProcessor functionality"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.fields import String, Integer
from protean.server import Engine
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.outbox import Outbox, OutboxStatus
from protean.utils.eventing import (
    Metadata,
    MessageHeaders,
    DomainMeta,
    EventStoreMeta,
    TraceParent,
)


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
        # Create metadata with headers containing the message ID
        headers = MessageHeaders(id=f"msg-{i}", type="DummyEvent", stream="test-stream")
        domain_meta = DomainMeta(stream_category="test-stream")
        metadata = Metadata(headers=headers, domain=domain_meta)

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

    def test_outbox_processor_initialization_with_invalid_database_provider(self):
        """Test OutboxProcessor initialization with invalid database provider"""

        domain = Domain(name="TestInvalidDBProvider")
        domain.config["enable_outbox"] = True
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "nonexistent_db", "default")

            # This should fail during initialization when trying to get outbox repository
            # The domain raises a KeyError, which gets wrapped by domain context
            with pytest.raises(KeyError, match="nonexistent_db"):
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

        # Create a minimal domain for the mock engine
        domain = Domain(name="TestMinimalDomain")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)

            processor = OutboxProcessor(
                engine, "default", "default", messages_per_tick=5
            )
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
            success, error = await processor._publish_message(messages[0])
            assert success is True
            assert error is None

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
            success, error = await processor._publish_message(messages[0])
            assert success is False
            assert error is not None
            assert str(error) == "Broker error"

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
            # Extract the message ID from the metadata structure
            msg_id = (
                message_payload["metadata"]["headers"]["id"]
                if "metadata" in message_payload
                and "headers" in message_payload["metadata"]
                else None
            )
            # Also check in data for backward compatibility
            if msg_id is None and "data" in message_payload:
                msg_id = message_payload["data"].get("message_id")

            if msg_id == "msg-0":
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
                # This should trigger the nested exception handler
                successful_count = await processor.process_batch([message])
                assert successful_count == 0

    @pytest.mark.asyncio
    async def test_process_batch_nested_exception_handler_coverage(
        self, outbox_test_domain
    ):
        """Test error handling when saving failed message status fails in separate transaction"""
        # Create a real message that can be persisted
        messages = persist_outbox_messages(outbox_test_domain)
        message = messages[0]

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Make _publish_message fail to trigger the main exception handler
        with patch.object(
            processor, "_publish_message", side_effect=Exception("Publish error")
        ):
            # Make outbox_repo.get fail in the nested error handling to simulate
            # the case where we can't reload the message to mark it as failed
            with patch.object(
                processor.outbox_repo, "get", side_effect=Exception("Repository error")
            ):
                # This should trigger the nested exception handler
                successful_count = await processor.process_batch([message])
                assert successful_count == 0

    @pytest.mark.asyncio
    async def test_publish_message_payload_format(self, outbox_test_domain):
        """Test that message payload is formatted correctly for broker with Message structure"""
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

        assert stream_name == "test-stream"

        # Verify the standard Message structure with 'data' and 'metadata' top-level keys
        assert "data" in payload
        assert "metadata" in payload

        # Data should contain the message payload
        assert payload["data"] == message.data

        # Metadata should be properly structured
        assert payload["metadata"] == message.metadata_.to_dict()


@pytest.mark.database
class TestMessageReconstruction:
    """Test Message reconstruction and publishing functionality"""

    @pytest.mark.asyncio
    async def test_message_reconstruction_with_full_metadata(self, outbox_test_domain):
        """Test that Message is correctly reconstructed with complete metadata"""
        # Create a comprehensive metadata object
        headers = MessageHeaders(
            id="test-msg-id",
            type="TestDomain.DummyEvent.v1",
            stream="test-stream",
            time=datetime.now(timezone.utc),
        )

        domain_meta = DomainMeta(
            fqn="TestDomain.DummyEvent",
            kind="EVENT",
            origin_stream="original-stream",
            stream_category="test-stream",
            version="v1",
            sequence_id="1.0",
            asynchronous=True,
            expected_version=0,
        )

        event_store_meta = EventStoreMeta(global_position=100, position=5)

        metadata = Metadata(
            headers=headers, domain=domain_meta, event_store=event_store_meta
        )

        # Create outbox message with rich metadata
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        message = Outbox.create_message(
            message_id="test-msg-id",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"name": "Test Event", "value": 42},
            metadata=metadata,
            priority=5,
            correlation_id="corr-123",
            trace_id="trace-456",
        )
        outbox_repo.add(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker to capture published message
        published_messages = []

        def capture_message(stream_name, message_dict):
            published_messages.append((stream_name, message_dict))
            return "broker-msg-id"

        with patch.object(processor.broker, "publish", side_effect=capture_message):
            success, error = await processor._publish_message(message)
            assert success is True
            assert error is None

        # Verify the published message structure
        assert len(published_messages) == 1
        stream_name, published_dict = published_messages[0]

        assert stream_name == "test-stream"
        assert "data" in published_dict
        assert "metadata" in published_dict

        # Verify data is preserved
        assert published_dict["data"] == {"name": "Test Event", "value": 42}

        # Verify metadata is preserved
        metadata_dict = published_dict["metadata"]
        assert metadata_dict["headers"]["id"] == "test-msg-id"
        assert metadata_dict["headers"]["type"] == "TestDomain.DummyEvent.v1"
        assert metadata_dict["headers"]["stream"] == "test-stream"
        assert metadata_dict["domain"]["fqn"] == "TestDomain.DummyEvent"
        assert metadata_dict["domain"]["kind"] == "EVENT"
        assert metadata_dict["domain"]["expected_version"] == 0
        assert metadata_dict["event_store"]["global_position"] == 100
        assert metadata_dict["event_store"]["position"] == 5

    @pytest.mark.asyncio
    async def test_message_reconstruction_with_minimal_metadata(
        self, outbox_test_domain
    ):
        """Test Message reconstruction with minimal metadata"""

        # Create minimal metadata
        metadata = Metadata(
            headers=MessageHeaders(
                id="minimal-msg",
                type="DummyEvent",
                time=datetime.now(timezone.utc),
                stream="test-stream",
            )
        )

        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        message = Outbox.create_message(
            message_id="minimal-msg",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"simple": "data"},
            metadata=metadata,
        )
        outbox_repo.add(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker to capture message
        published_messages = []

        def capture_message(stream_name, message_dict):
            published_messages.append(message_dict)
            return "broker-msg-id"

        with patch.object(processor.broker, "publish", side_effect=capture_message):
            success, error = await processor._publish_message(message)
            assert success is True

        # Verify structure
        published_dict = published_messages[0]
        assert "data" in published_dict
        assert "metadata" in published_dict
        assert published_dict["data"] == {"simple": "data"}

    @pytest.mark.asyncio
    async def test_message_reconstruction_preserves_traceparent(
        self, outbox_test_domain
    ):
        """Test that TraceParent information is preserved in Message reconstruction"""
        # Create metadata with traceparent
        traceparent = TraceParent(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            parent_id="b7ad6b7169203331",
            sampled=True,
        )

        headers = MessageHeaders(
            id="trace-test-msg",
            type="TestDomain.DummyEvent.v1",
            stream="test-stream",
            traceparent=traceparent,
        )

        metadata = Metadata(headers=headers)

        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        message = Outbox.create_message(
            message_id="trace-test-msg",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"traced": "event"},
            metadata=metadata,
            correlation_id="corr-789",
            trace_id="trace-789",
        )
        outbox_repo.add(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Capture published message
        published_messages = []

        def capture_message(stream_name, message_dict):
            published_messages.append(message_dict)
            return "broker-msg-id"

        with patch.object(processor.broker, "publish", side_effect=capture_message):
            await processor._publish_message(message)

        # Verify traceparent is preserved
        published_dict = published_messages[0]
        headers_dict = published_dict["metadata"]["headers"]
        traceparent_dict = headers_dict["traceparent"]

        assert traceparent_dict["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
        assert traceparent_dict["parent_id"] == "b7ad6b7169203331"
        assert traceparent_dict["sampled"] is True

    @pytest.mark.asyncio
    async def test_message_reconstruction_handles_complex_data(
        self, outbox_test_domain
    ):
        """Test Message reconstruction with complex nested data structures"""

        complex_data = {
            "nested": {
                "level1": {
                    "level2": {
                        "value": 123,
                        "list": [1, 2, 3],
                        "dict": {"key": "value"},
                    }
                }
            },
            "array": [{"id": 1, "name": "Item 1"}, {"id": 2, "name": "Item 2"}],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "null_value": None,
            "boolean": True,
            "float": 3.14159,
        }

        metadata = Metadata(
            headers=MessageHeaders(
                id="complex-msg",
                type="ComplexEvent",
                time=datetime.now(timezone.utc),
                stream="test-stream",
            )
        )

        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        message = Outbox.create_message(
            message_id="complex-msg",
            stream_name="test-stream",
            message_type="ComplexEvent",
            data=complex_data,
            metadata=metadata,
        )
        outbox_repo.add(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Capture published message
        published_messages = []

        def capture_message(stream_name, message_dict):
            published_messages.append(message_dict)
            return "broker-msg-id"

        with patch.object(processor.broker, "publish", side_effect=capture_message):
            success, error = await processor._publish_message(message)
            assert success is True

        # Verify complex data is preserved
        published_dict = published_messages[0]
        assert published_dict["data"] == complex_data

        # Verify nested structures
        nested_data = published_dict["data"]["nested"]["level1"]["level2"]
        assert nested_data["value"] == 123
        assert nested_data["list"] == [1, 2, 3]
        assert nested_data["dict"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_message_reconstruction_error_handling(self, outbox_test_domain):
        """Test error handling during Message reconstruction"""
        metadata = Metadata(
            headers=MessageHeaders(
                id="error-msg",
                type="DummyEvent",
                time=datetime.now(timezone.utc),
                stream="test-stream",
            )
        )

        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        message = Outbox.create_message(
            message_id="error-test-msg",
            stream_name="test-stream",
            message_type="DummyEvent",
            data={"test": "data"},
            metadata=metadata,
        )
        outbox_repo.add(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock Message class to raise exception during reconstruction
        with patch(
            "protean.server.outbox_processor.Message",
            side_effect=Exception("Message reconstruction error"),
        ):
            success, error = await processor._publish_message(message)

            assert success is False
            assert error is not None
            assert str(error) == "Message reconstruction error"

    @pytest.mark.asyncio
    async def test_batch_processing_with_message_structure(self, outbox_test_domain):
        """Test batch processing publishes all messages with correct Message structure"""

        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        # Create multiple messages with different metadata
        messages = []
        for i in range(3):
            headers = MessageHeaders(
                id=f"batch-msg-{i}", type=f"Event{i}", stream=f"stream-{i}"
            )
            domain_meta = DomainMeta(stream_category=f"stream-{i}")
            metadata = Metadata(headers=headers, domain=domain_meta)

            message = Outbox.create_message(
                message_id=f"batch-msg-{i}",
                stream_name=f"stream-{i}",
                message_type=f"Event{i}",
                data={"index": i, "batch": True},
                metadata=metadata,
            )
            outbox_repo.add(message)
            messages.append(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Capture all published messages
        published_messages = []

        def capture_message(stream_name, message_dict):
            published_messages.append((stream_name, message_dict))
            return f"broker-msg-id-{len(published_messages)}"

        with patch.object(processor.broker, "publish", side_effect=capture_message):
            successful_count = await processor.process_batch(messages)
            assert successful_count == 3

        # Verify all messages were published with correct structure
        assert len(published_messages) == 3

        for i, (stream_name, published_dict) in enumerate(published_messages):
            assert stream_name == f"stream-{i}"
            assert "data" in published_dict
            assert "metadata" in published_dict
            assert published_dict["data"]["index"] == i
            assert published_dict["data"]["batch"] is True
            assert published_dict["metadata"]["headers"]["id"] == f"batch-msg-{i}"
            assert published_dict["metadata"]["headers"]["type"] == f"Event{i}"

    @pytest.mark.asyncio
    async def test_message_dict_structure_validation(self, outbox_test_domain):
        """Test that published message dict has correct top-level structure"""
        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        # Create a message with headers and envelope
        headers = MessageHeaders(
            id="struct-test-msg", type="TestEvent", stream="test-stream"
        )

        metadata = Metadata(headers=headers)

        # Create message
        message = Outbox.create_message(
            message_id="struct-test-msg",
            stream_name="test-stream",
            message_type="TestEvent",
            data={"field1": "value1", "field2": 123},
            metadata=metadata,
        )
        outbox_repo.add(message)

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Capture published message
        published_messages = []

        def capture_message(stream_name, message_dict):
            published_messages.append(message_dict)
            return "broker-msg-id"

        with patch.object(processor.broker, "publish", side_effect=capture_message):
            success, error = await processor._publish_message(message)

        assert success is True
        assert error is None

        # Verify the published dict has exactly the expected top-level keys
        published_dict = published_messages[0]
        assert set(published_dict.keys()) == {"data", "metadata"}

        # Verify data structure
        assert isinstance(published_dict["data"], dict)
        assert published_dict["data"]["field1"] == "value1"
        assert published_dict["data"]["field2"] == 123

        # Verify metadata structure
        assert isinstance(published_dict["metadata"], dict)
        assert "headers" in published_dict["metadata"]
        assert published_dict["metadata"]["headers"]["id"] == "struct-test-msg"


@pytest.mark.database
class TestOutboxConfiguration:
    """Test outbox configuration and validation"""

    def test_default_outbox_configuration(self):
        """Test that default outbox configuration is loaded correctly"""
        domain = Domain(name="TestDefaultConfig")
        domain.init(traverse=False)

        # Default outbox config should be present
        assert "outbox" in domain.config
        assert domain.config["outbox"]["broker"] == "default"
        assert domain.config["outbox"]["messages_per_tick"] == 50
        assert domain.config["outbox"]["tick_interval"] == 0.01

    def test_custom_outbox_configuration(self):
        """Test custom outbox configuration is applied correctly"""

        custom_config = {
            "enable_outbox": True,
            "outbox": {
                "broker": "custom_broker",
                "messages_per_tick": 25,
                "tick_interval": 5,
            },
            "brokers": {
                "default": {"provider": "inline"},
                "custom_broker": {"provider": "inline"},
            },
        }

        domain = Domain(name="TestCustomConfig", config=custom_config)
        domain.init(traverse=False)

        # Custom config should be applied
        assert domain.config["outbox"]["broker"] == "custom_broker"
        assert domain.config["outbox"]["messages_per_tick"] == 25
        assert domain.config["outbox"]["tick_interval"] == 5

    def test_engine_uses_custom_outbox_configuration(self):
        """Test that Engine uses custom outbox configuration for processors"""

        custom_config = {
            "enable_outbox": True,
            "outbox": {
                "broker": "custom_broker",
                "messages_per_tick": 15,
                "tick_interval": 3,
            },
            "brokers": {
                "default": {"provider": "inline"},
                "custom_broker": {"provider": "inline"},
            },
        }

        domain = Domain(name="TestEngineCustomConfig", config=custom_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            # Should create processors with custom configuration
            assert len(engine._outbox_processors) > 0

            # Get a processor and verify its configuration
            processor = list(engine._outbox_processors.values())[0]
            assert processor.broker_provider_name == "custom_broker"
            assert processor.messages_per_tick == 15
            assert processor.tick_interval == 3

    def test_engine_validates_broker_exists_in_config(self):
        """Test that Engine validates broker exists when creating outbox processors"""

        invalid_config = {
            "enable_outbox": True,
            "outbox": {
                "broker": "nonexistent_broker",
                "messages_per_tick": 10,
                "tick_interval": 1,
            },
            "brokers": {
                "default": {"provider": "inline"},
            },
        }

        domain = Domain(name="TestInvalidBroker", config=invalid_config)
        domain.init(traverse=False)

        with domain.domain_context():
            with pytest.raises(
                ValueError,
                match="Broker provider 'nonexistent_broker' not configured in domain",
            ):
                Engine(domain, test_mode=True)

    def test_outbox_disabled_by_default(self):
        """Test that outbox processors are not created when outbox is disabled"""

        domain = Domain(name="TestOutboxDisabled")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            # No outbox processors should be created when outbox is disabled
            assert len(engine._outbox_processors) == 0

    def test_outbox_configuration_with_multiple_brokers(self):
        """Test outbox configuration with multiple brokers but specific broker selection"""

        multi_broker_config = {
            "enable_outbox": True,
            "outbox": {
                "broker": "redis_broker",
                "messages_per_tick": 20,
                "tick_interval": 2,
            },
            "brokers": {
                "default": {"provider": "inline"},
                "redis_broker": {"provider": "inline"},
                "rabbitmq_broker": {"provider": "inline"},
            },
        }

        domain = Domain(name="TestMultiBroker", config=multi_broker_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)

            # Should create processors only for the configured broker
            processor_names = list(engine._outbox_processors.keys())
            for name in processor_names:
                assert "redis_broker" in name
                assert "rabbitmq_broker" not in name

    def test_outbox_processor_custom_worker_id(self):
        """Test OutboxProcessor with custom worker ID"""

        domain = Domain(name="TestCustomWorkerID")
        domain.config["enable_outbox"] = True
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            custom_worker_id = "custom-worker-123"

            processor = OutboxProcessor(
                engine=engine,
                database_provider_name="default",
                broker_provider_name="default",
                worker_id=custom_worker_id,
            )

            assert processor.worker_id == custom_worker_id

    def test_outbox_configuration_partial_override(self):
        """Test that partial outbox configuration overrides work correctly"""

        partial_config = {
            "enable_outbox": True,
            "outbox": {
                "messages_per_tick": 100,  # Only override one parameter
            },
        }

        domain = Domain(name="TestPartialOverride", config=partial_config)
        domain.init(traverse=False)

        # Should use custom messages_per_tick but default values for others
        assert domain.config["outbox"]["messages_per_tick"] == 100
        assert domain.config["outbox"]["tick_interval"] == 0.01  # Default
        assert domain.config["outbox"]["broker"] == "default"  # Default

    def test_engine_error_handling_with_missing_outbox_config_key(self):
        """Test Engine handles missing outbox configuration keys gracefully"""

        incomplete_config = {
            "enable_outbox": True,
            "outbox": {},  # Empty outbox config - should use defaults
        }

        domain = Domain(name="TestIncompleteConfig", config=incomplete_config)
        domain.init(traverse=False)

        with domain.domain_context():
            # Should work with default values
            engine = Engine(domain, test_mode=True)

            if engine._outbox_processors:
                processor = list(engine._outbox_processors.values())[0]
                assert processor.broker_provider_name == "default"
                assert processor.messages_per_tick == 50
                assert processor.tick_interval == 0.01


@pytest.mark.database
class TestEngineIntegration:
    """Test OutboxProcessor integration with Engine"""

    def test_engine_initializes_outbox_processors(self, outbox_test_domain):
        """Test that Engine initializes outbox processors for all database-broker provider combinations"""
        engine = Engine(outbox_test_domain, test_mode=True)

        # Engine should create outbox processors for each database-broker provider combination
        assert hasattr(engine, "_outbox_processors")

        # Calculate expected processors: one for each database provider to the configured outbox broker
        database_providers = list(outbox_test_domain.providers.keys())
        outbox_broker = outbox_test_domain.config.get("outbox", {}).get(
            "broker", "default"
        )
        expected_combinations = [
            f"outbox-processor-{db}-to-{outbox_broker}" for db in database_providers
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
            metadata = Metadata(
                headers=MessageHeaders(
                    id=f"batch-msg-{i}",
                    type="DummyEvent",
                    time=datetime.now(timezone.utc),
                    stream="test-stream",
                )
            )
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
        metadata_low = Metadata(
            headers=MessageHeaders(
                id="low-priority",
                type="DummyEvent",
                time=datetime.now(timezone.utc),
                stream="test-stream",
            )
        )
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
        metadata_high = Metadata(
            headers=MessageHeaders(
                id="high-priority",
                type="DummyEvent",
                time=datetime.now(timezone.utc),
                stream="test-stream",
            )
        )
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


@pytest.mark.database
class TestAtomicTransactionProcessing:
    """Test atomic transaction behavior in multi-processor environments"""

    @pytest.mark.asyncio
    async def test_atomic_message_processing_success(self, outbox_test_domain):
        """Test that successful message processing is atomic"""
        messages = persist_outbox_messages(outbox_test_domain)
        message = messages[0]

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker to succeed
        with patch.object(processor.broker, "publish", return_value="broker-msg-id"):
            success = await processor._process_single_message(message)
            assert success is True

        # Verify message was atomically updated to PUBLISHED
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        updated_message = outbox_repo.get(message.id)
        assert updated_message.status == OutboxStatus.PUBLISHED.value
        assert updated_message.published_at is not None

    @pytest.mark.asyncio
    async def test_atomic_message_processing_broker_failure(self, outbox_test_domain):
        """Test that broker failures are handled atomically"""
        messages = persist_outbox_messages(outbox_test_domain)
        message = messages[0]

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker to fail
        with patch.object(
            processor.broker, "publish", side_effect=Exception("Broker error")
        ):
            success = await processor._process_single_message(message)
            assert success is False

        # Verify message was atomically updated to FAILED
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        updated_message = outbox_repo.get(message.id)
        assert updated_message.status == OutboxStatus.FAILED.value
        assert updated_message.retry_count == 1

    @pytest.mark.asyncio
    async def test_atomic_processing_rollback_on_exception(self, outbox_test_domain):
        """Test that processing exceptions cause complete rollback"""
        messages = persist_outbox_messages(outbox_test_domain)
        message = messages[0]

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock _publish_message to raise an exception after lock acquisition
        with patch.object(
            processor, "_publish_message", side_effect=Exception("Processing error")
        ):
            success = await processor._process_single_message(message)
            assert success is False

        # Verify message status was properly handled (should be marked as failed in separate transaction)
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        updated_message = outbox_repo.get(message.id)
        assert updated_message.status == OutboxStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_concurrent_processor_lock_contention(self, outbox_test_domain):
        """Test that multiple processors handle lock contention correctly"""
        messages = persist_outbox_messages(outbox_test_domain)
        message = messages[0]

        # Create two processors with different worker IDs
        engine1 = MockEngine(outbox_test_domain)
        engine2 = MockEngine(outbox_test_domain)

        processor1 = OutboxProcessor(engine1, "default", "default")
        processor1.worker_id = "worker-1"
        await processor1.initialize()

        processor2 = OutboxProcessor(engine2, "default", "default")
        processor2.worker_id = "worker-2"
        await processor2.initialize()

        # Mock both brokers to succeed
        with (
            patch.object(processor1.broker, "publish", return_value="broker-msg-1"),
            patch.object(processor2.broker, "publish", return_value="broker-msg-2"),
        ):
            # Both processors try to process the same message
            success1 = await processor1._process_single_message(message)
            success2 = await processor2._process_single_message(message)

        # Only one should succeed (the one that got the lock first)
        assert success1 != success2  # Exactly one should be True
        assert success1 or success2  # At least one should succeed

        # Verify message was processed exactly once
        outbox_repo = outbox_test_domain._get_outbox_repo("default")
        updated_message = outbox_repo.get(message.id)
        assert updated_message.status == OutboxStatus.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_individual_message_transaction_isolation(self, outbox_test_domain):
        """Test that each message is processed in its own isolated transaction"""
        messages = persist_outbox_messages(outbox_test_domain)[:3]

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock broker to succeed for first message, fail for second, succeed for third
        def mock_publish(stream_name, message_payload):
            # Extract the message ID from the metadata structure
            msg_id = (
                message_payload["metadata"]["headers"]["id"]
                if "metadata" in message_payload
                and "headers" in message_payload["metadata"]
                else None
            )
            # Also check in data for backward compatibility
            if msg_id is None and "data" in message_payload:
                msg_id = message_payload["data"].get("message_id")

            if msg_id == "msg-0":
                return "broker-msg-0"  # Success
            elif msg_id == "msg-1":
                raise Exception("Broker error for msg-1")  # Failure
            else:
                return "broker-msg-2"  # Success

        with patch.object(processor.broker, "publish", side_effect=mock_publish):
            successful_count = await processor.process_batch(messages)
            assert successful_count == 2  # Two out of three should succeed

        # Verify each message has correct individual status
        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        msg_0 = outbox_repo.get(messages[0].id)
        assert msg_0.status == OutboxStatus.PUBLISHED.value

        msg_1 = outbox_repo.get(messages[1].id)
        assert msg_1.status == OutboxStatus.FAILED.value

        msg_2 = outbox_repo.get(messages[2].id)
        assert msg_2.status == OutboxStatus.PUBLISHED.value


@pytest.mark.database
class TestRetryConfiguration:
    """Test configurable retry strategy functionality"""

    def test_default_retry_configuration_loading(self):
        """Test that default retry configuration is loaded correctly"""

        domain = Domain(name="TestDefaultRetryConfig")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            retry_config = processor.get_retry_config()
            assert retry_config["max_attempts"] == 3
            assert retry_config["base_delay_seconds"] == 1
            assert retry_config["max_backoff_seconds"] == 60
            assert retry_config["backoff_multiplier"] == 2
            assert retry_config["jitter"] is True
            assert retry_config["jitter_factor"] == 0.25

    def test_custom_retry_configuration(self):
        """Test that custom retry configuration is applied correctly"""

        custom_config = {
            "enable_outbox": True,
            "outbox": {
                "broker": "default",
                "retry": {
                    "max_attempts": 5,
                    "base_delay_seconds": 30,
                    "max_backoff_seconds": 1800,
                    "backoff_multiplier": 3,
                    "jitter": False,
                    "jitter_factor": 0.1,
                },
            },
        }

        domain = Domain(name="TestCustomRetryConfig", config=custom_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            retry_config = processor.get_retry_config()
            assert retry_config["max_attempts"] == 5
            assert retry_config["base_delay_seconds"] == 30
            assert retry_config["max_backoff_seconds"] == 1800
            assert retry_config["backoff_multiplier"] == 3
            assert retry_config["jitter"] is False
            assert retry_config["jitter_factor"] == 0.1

    def test_partial_retry_configuration_override(self):
        """Test that partial retry configuration overrides work correctly"""

        partial_config = {
            "enable_outbox": True,
            "outbox": {
                "retry": {
                    "max_attempts": 7,  # Only override max_attempts
                    "base_delay_seconds": 120,  # And base delay
                }
            },
        }

        domain = Domain(name="TestPartialRetryConfig", config=partial_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            retry_config = processor.get_retry_config()
            assert retry_config["max_attempts"] == 7  # Custom
            assert retry_config["base_delay_seconds"] == 120  # Custom
            assert retry_config["max_backoff_seconds"] == 60  # Default
            assert retry_config["backoff_multiplier"] == 2  # Default
            assert retry_config["jitter"] is True  # Default
            assert retry_config["jitter_factor"] == 0.25  # Default

    def test_retry_delay_calculation_without_jitter(self):
        """Test retry delay calculation without jitter"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 10,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 100,
                    "jitter": False,
                }
            }
        }

        domain = Domain(name="TestRetryDelay", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # Test exponential backoff: 10, 20, 40, 80, 100 (capped)
            assert processor._calculate_retry_delay(0) == 10
            assert processor._calculate_retry_delay(1) == 20
            assert processor._calculate_retry_delay(2) == 40
            assert processor._calculate_retry_delay(3) == 80
            assert processor._calculate_retry_delay(4) == 100  # Capped at max_backoff

    def test_retry_delay_calculation_with_jitter(self):
        """Test retry delay calculation with jitter using default jitter factor"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 100,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 1000,
                    "jitter": True,
                    "jitter_factor": 0.25,  # Default 25% jitter
                }
            }
        }

        domain = Domain(name="TestRetryDelayJitter", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # With jitter, delay should be within ±25% of expected value (100 ±25)
            actual_delays = [processor._calculate_retry_delay(0) for _ in range(10)]

            # All delays should be within the jitter range (75-125)
            for delay in actual_delays:
                assert 75 <= delay <= 125

            # Should have some variation (not all the same)
            assert len(set(actual_delays)) > 1

    def test_retry_delay_calculation_with_custom_jitter_factor(self):
        """Test retry delay calculation with custom jitter factor"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 100,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 1000,
                    "jitter": True,
                    "jitter_factor": 0.1,  # 10% jitter
                }
            }
        }

        domain = Domain(name="TestCustomJitterFactor", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # With 10% jitter, delay should be within ±10% of expected value (100 ±10)
            actual_delays = [processor._calculate_retry_delay(0) for _ in range(20)]

            # All delays should be within the jitter range (90-110)
            for delay in actual_delays:
                assert 90 <= delay <= 110

            # Should have some variation (not all the same)
            assert len(set(actual_delays)) > 1

    def test_retry_delay_calculation_with_high_jitter_factor(self):
        """Test retry delay calculation with high jitter factor"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 100,
                    "backoff_multiplier": 1,  # No exponential backoff
                    "max_backoff_seconds": 1000,
                    "jitter": True,
                    "jitter_factor": 0.5,  # 50% jitter
                }
            }
        }

        domain = Domain(name="TestHighJitterFactor", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # With 50% jitter, delay should be within ±50% of expected value (100 ±50)
            actual_delays = [processor._calculate_retry_delay(0) for _ in range(20)]

            # All delays should be within the jitter range (50-150)
            for delay in actual_delays:
                assert 50 <= delay <= 150

            # Should have significant variation
            assert len(set(actual_delays)) > 5

    def test_retry_delay_calculation_with_zero_jitter_factor(self):
        """Test retry delay calculation with zero jitter factor (effectively no jitter)"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 100,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 1000,
                    "jitter": True,  # Jitter enabled but factor is 0
                    "jitter_factor": 0.0,  # No jitter
                }
            }
        }

        domain = Domain(name="TestZeroJitterFactor", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # With zero jitter factor, all delays should be exactly the base delay
            actual_delays = [processor._calculate_retry_delay(0) for _ in range(10)]

            # All delays should be exactly 100 (no variation)
            for delay in actual_delays:
                assert delay == 100

    def test_jitter_factor_configuration_loading(self):
        """Test that jitter factor is correctly loaded from configuration"""

        test_cases = [
            (0.1, "10% jitter factor"),
            (0.25, "25% jitter factor"),
            (0.5, "50% jitter factor"),
            (0.75, "75% jitter factor"),
        ]

        for jitter_factor, description in test_cases:
            config = {
                "outbox": {
                    "retry": {
                        "jitter_factor": jitter_factor,
                    }
                }
            }

            domain = Domain(
                name=f"TestJitterFactor{int(jitter_factor * 100)}", config=config
            )
            domain.init(traverse=False)

            with domain.domain_context():
                engine = MockEngine(domain)
                processor = OutboxProcessor(engine, "default", "default")

                retry_config = processor.get_retry_config()
                assert retry_config["jitter_factor"] == jitter_factor, (
                    f"Failed for {description}"
                )

    def test_jitter_factor_partial_override(self):
        """Test that jitter factor can be overridden independently of other retry settings"""

        partial_config = {
            "enable_outbox": True,
            "outbox": {
                "retry": {
                    "jitter_factor": 0.15,  # Only override jitter factor
                }
            },
        }

        domain = Domain(name="TestJitterFactorPartialOverride", config=partial_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            retry_config = processor.get_retry_config()
            assert retry_config["jitter_factor"] == 0.15  # Custom
            assert retry_config["max_attempts"] == 3  # Default
            assert retry_config["base_delay_seconds"] == 1  # Default
            assert retry_config["jitter"] is True  # Default

    def test_jitter_factor_minimum_delay_enforcement(self):
        """Test that jitter factor calculation enforces minimum 1 second delay"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 2,  # Very small base delay
                    "jitter": True,
                    "jitter_factor": 0.9,  # Very high jitter that could go below 1
                }
            }
        }

        domain = Domain(name="TestJitterMinDelay", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # Even with high jitter on small base delay, minimum should be 1 second
            actual_delays = [processor._calculate_retry_delay(0) for _ in range(50)]

            # All delays should be at least 1 second
            for delay in actual_delays:
                assert delay >= 1

    def test_should_retry_message_logic(self):
        """Test message retry eligibility logic"""

        config = {
            "outbox": {
                "retry": {
                    "max_attempts": 3,
                }
            }
        }

        domain = Domain(name="TestShouldRetry", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # Create a mock message
            message = Mock()

            # Should retry when retry_count < max_attempts
            message.retry_count = 0
            assert processor._should_retry_message(message) is True

            message.retry_count = 2
            assert processor._should_retry_message(message) is True

            # Should not retry when retry_count >= max_attempts
            message.retry_count = 3
            assert processor._should_retry_message(message) is False

            message.retry_count = 5
            assert processor._should_retry_message(message) is False

    def test_retry_configuration_integration(self):
        """Test that retry configuration is properly loaded and accessible"""

        custom_config = {
            "enable_outbox": True,
            "outbox": {
                "broker": "default",
                "retry": {
                    "max_attempts": 8,
                    "base_delay_seconds": 45,
                    "max_backoff_seconds": 2400,
                    "backoff_multiplier": 1.5,
                    "jitter": False,
                    "jitter_factor": 0.3,
                },
            },
        }

        domain = Domain(name="TestRetryIntegration", config=custom_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # Verify all configuration values are loaded correctly
            retry_config = processor.get_retry_config()
            assert retry_config["max_attempts"] == 8
            assert retry_config["base_delay_seconds"] == 45
            assert retry_config["max_backoff_seconds"] == 2400
            assert retry_config["backoff_multiplier"] == 1.5
            assert retry_config["jitter"] is False
            assert retry_config["jitter_factor"] == 0.3

            # Test that the processor methods use the config
            assert (
                processor._should_retry_message(
                    type("MockMessage", (), {"retry_count": 7})()
                )
                is True
            )
            assert (
                processor._should_retry_message(
                    type("MockMessage", (), {"retry_count": 8})()
                )
                is False
            )

            # Test delay calculation uses configured values
            delay = processor._calculate_retry_delay(1)  # Second retry
            expected = 45 * (1.5**1)  # base_delay * backoff_multiplier^retry_count
            assert delay == int(expected)

    def test_jitter_factor_with_exponential_backoff_integration(self):
        """Test that jitter factor works correctly with exponential backoff at different retry counts"""

        config = {
            "outbox": {
                "retry": {
                    "base_delay_seconds": 60,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 500,
                    "jitter": True,
                    "jitter_factor": 0.2,  # 20% jitter
                }
            }
        }

        domain = Domain(name="TestJitterWithBackoff", config=config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            # Test different retry counts with their expected base delays
            test_cases = [
                (0, 60),  # First retry: 60 seconds
                (1, 120),  # Second retry: 60 * 2 = 120 seconds
                (2, 240),  # Third retry: 60 * 4 = 240 seconds
                (3, 480),  # Fourth retry: 60 * 8 = 480 seconds
                (4, 500),  # Fifth retry: 60 * 16 = 960, but capped at 500
            ]

            for retry_count, expected_base in test_cases:
                # Test multiple samples to ensure jitter is working
                actual_delays = [
                    processor._calculate_retry_delay(retry_count) for _ in range(10)
                ]

                # Calculate expected jitter range (±20%)
                jitter_amount = expected_base * 0.2
                min_expected = expected_base - jitter_amount
                max_expected = expected_base + jitter_amount

                # All delays should be within the jitter range
                for delay in actual_delays:
                    assert min_expected <= delay <= max_expected, (
                        f"Retry count {retry_count}: delay {delay} not in range "
                        f"[{min_expected}, {max_expected}] for base delay {expected_base}"
                    )

                # Should have some variation (at least 2 different values in 10 samples)
                assert len(set(actual_delays)) >= 2, (
                    f"Retry count {retry_count}: insufficient jitter variation in delays {actual_delays}"
                )


@pytest.mark.database
class TestOutboxCleanup:
    """Test outbox cleanup functionality"""

    def test_cleanup_old_abandoned_messages(self, outbox_test_domain):
        """Test cleanup of old abandoned messages"""
        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        # Create an abandoned message from 31 days ago
        old_message = persist_outbox_messages(outbox_test_domain)[0]
        old_message.status = OutboxStatus.ABANDONED.value
        old_message.last_processed_at = datetime.now(timezone.utc) - timedelta(days=31)
        outbox_repo.add(old_message)

        # Create a recent abandoned message
        recent_message = persist_outbox_messages(outbox_test_domain)[0]
        recent_message.message_id = "recent-msg"
        recent_message.status = OutboxStatus.ABANDONED.value
        recent_message.last_processed_at = datetime.now(timezone.utc) - timedelta(
            days=1
        )
        outbox_repo.add(recent_message)

        # Verify both messages exist
        abandoned_messages = outbox_repo.find_abandoned()
        assert len(abandoned_messages) == 2

        # Clean up old abandoned messages (older than 30 days)
        cleaned_count = outbox_repo.cleanup_old_abandoned(
            older_than_hours=720
        )  # 30 days
        assert cleaned_count == 1

        # Verify only the recent message remains
        remaining_abandoned = outbox_repo.find_abandoned()
        assert len(remaining_abandoned) == 1
        assert remaining_abandoned[0].message_id == "recent-msg"

    def test_cleanup_old_messages_unified(self, outbox_test_domain):
        """Test unified cleanup of both published and abandoned messages"""
        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        # Create old published message (8 days ago)
        old_published = persist_outbox_messages(outbox_test_domain)[0]
        old_published.message_id = "old-published"
        old_published.status = OutboxStatus.PUBLISHED.value
        old_published.published_at = datetime.now(timezone.utc) - timedelta(days=8)
        outbox_repo.add(old_published)

        # Create recent published message (1 day ago)
        recent_published = persist_outbox_messages(outbox_test_domain)[0]
        recent_published.message_id = "recent-published"
        recent_published.status = OutboxStatus.PUBLISHED.value
        recent_published.published_at = datetime.now(timezone.utc) - timedelta(days=1)
        outbox_repo.add(recent_published)

        # Create old abandoned message (31 days ago)
        old_abandoned = persist_outbox_messages(outbox_test_domain)[0]
        old_abandoned.message_id = "old-abandoned"
        old_abandoned.status = OutboxStatus.ABANDONED.value
        old_abandoned.last_processed_at = datetime.now(timezone.utc) - timedelta(
            days=31
        )
        outbox_repo.add(old_abandoned)

        # Create recent abandoned message (1 day ago)
        recent_abandoned = persist_outbox_messages(outbox_test_domain)[0]
        recent_abandoned.message_id = "recent-abandoned"
        recent_abandoned.status = OutboxStatus.ABANDONED.value
        recent_abandoned.last_processed_at = datetime.now(timezone.utc) - timedelta(
            days=1
        )
        outbox_repo.add(recent_abandoned)

        # Clean up with 7 days for published, 30 days for abandoned
        cleanup_result = outbox_repo.cleanup_old_messages(
            published_retention_hours=168,  # 7 days
            abandoned_retention_hours=720,  # 30 days
        )

        # Verify results
        assert cleanup_result["published"] == 1  # Old published message cleaned
        assert cleanup_result["abandoned"] == 1  # Old abandoned message cleaned
        assert cleanup_result["total"] == 2

        # Verify only recent messages remain
        remaining_published = outbox_repo.find_published()
        assert len(remaining_published) == 1
        assert remaining_published[0].message_id == "recent-published"

        remaining_abandoned = outbox_repo.find_abandoned()
        assert len(remaining_abandoned) == 1
        assert remaining_abandoned[0].message_id == "recent-abandoned"


@pytest.mark.database
class TestOutboxPeriodicCleanup:
    """Test periodic cleanup functionality in OutboxProcessor"""

    def test_cleanup_configuration_loading(self, outbox_test_domain):
        """Test that cleanup configuration is loaded correctly from domain config"""
        custom_config = {
            "enable_outbox": True,
            "outbox": {
                "cleanup": {
                    "published_retention_hours": 72,  # 3 days
                    "abandoned_retention_hours": 480,  # 20 days
                },
            },
        }

        domain = Domain(name="TestCleanupConfig", config=custom_config)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")

            assert processor.cleanup_config["published_retention_hours"] == 72
            assert processor.cleanup_config["abandoned_retention_hours"] == 480

    def test_cleanup_configuration_defaults(self, outbox_test_domain):
        """Test that cleanup configuration uses defaults when not specified"""
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")

        # Should use default values
        assert processor.cleanup_config["published_retention_hours"] == 168  # 7 days
        assert processor.cleanup_config["abandoned_retention_hours"] == 720  # 30 days

    @pytest.mark.asyncio
    async def test_periodic_cleanup_trigger(self, outbox_test_domain):
        """Test that cleanup is triggered after the configured interval"""
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        processor.cleanup_config["cleanup_interval_ticks"] = (
            3  # Set low interval for testing
        )
        await processor.initialize()

        # Mock the cleanup method to track calls
        cleanup_called = {"count": 0}

        async def mock_perform_cleanup():
            cleanup_called["count"] += 1

        processor._perform_cleanup = mock_perform_cleanup

        # Simulate 3 ticks - should trigger cleanup once
        for _ in range(3):
            await processor.tick()

        # Cleanup should have been called once (after 3 ticks) and reset the counter
        assert cleanup_called["count"] == 1

        # Two more ticks should not trigger cleanup yet (tick_count = 2)
        await processor.tick()
        await processor.tick()
        assert cleanup_called["count"] == 1

        # One more tick should trigger cleanup again (tick_count = 3)
        await processor.tick()
        assert cleanup_called["count"] == 2

    @pytest.mark.asyncio
    async def test_perform_cleanup_functionality(self, outbox_test_domain):
        """Test that _perform_cleanup actually cleans up old messages"""

        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        processor.cleanup_config = {
            "published_retention_hours": 24,  # 1 day
            "abandoned_retention_hours": 48,  # 2 days
        }
        await processor.initialize()

        outbox_repo = outbox_test_domain._get_outbox_repo("default")

        # Create old messages
        old_published = persist_outbox_messages(outbox_test_domain)[0]
        old_published.message_id = "old-pub"
        old_published.status = OutboxStatus.PUBLISHED.value
        old_published.published_at = datetime.now(timezone.utc) - timedelta(days=2)
        outbox_repo.add(old_published)

        old_abandoned = persist_outbox_messages(outbox_test_domain)[0]
        old_abandoned.message_id = "old-aband"
        old_abandoned.status = OutboxStatus.ABANDONED.value
        old_abandoned.last_processed_at = datetime.now(timezone.utc) - timedelta(days=3)
        outbox_repo.add(old_abandoned)

        # Create recent messages
        recent_published = persist_outbox_messages(outbox_test_domain)[0]
        recent_published.message_id = "recent-pub"
        recent_published.status = OutboxStatus.PUBLISHED.value
        recent_published.published_at = datetime.now(timezone.utc) - timedelta(hours=12)
        outbox_repo.add(recent_published)

        # Verify messages exist before cleanup
        assert len(outbox_repo.find_published()) == 2
        assert len(outbox_repo.find_abandoned()) == 1

        # Perform cleanup
        await processor._perform_cleanup()

        # Verify old messages were cleaned up
        remaining_published = outbox_repo.find_published()
        remaining_abandoned = outbox_repo.find_abandoned()

        assert len(remaining_published) == 1
        assert remaining_published[0].message_id == "recent-pub"
        assert len(remaining_abandoned) == 0  # Old abandoned should be gone

    @pytest.mark.asyncio
    async def test_cleanup_error_handling(self, outbox_test_domain):
        """Test that cleanup errors are handled gracefully"""
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")
        await processor.initialize()

        # Mock cleanup_old_messages to raise an exception
        original_cleanup = processor.outbox_repo.cleanup_old_messages

        def failing_cleanup(*args, **kwargs):
            raise Exception("Cleanup error")

        processor.outbox_repo.cleanup_old_messages = failing_cleanup

        # This should not raise an exception
        await processor._perform_cleanup()

        # Restore original method
        processor.outbox_repo.cleanup_old_messages = original_cleanup

    @pytest.mark.asyncio
    async def test_cleanup_with_no_outbox_repo(self):
        """Test that cleanup handles missing outbox repository gracefully"""

        domain = Domain(name="TestNoRepo")
        domain.init(traverse=False)

        with domain.domain_context():
            engine = MockEngine(domain)
            processor = OutboxProcessor(engine, "default", "default")
            # Don't call initialize() so outbox_repo remains None

            # This should not raise an exception
            await processor._perform_cleanup()

    def test_cleanup_interval_configuration(self, outbox_test_domain):
        """Test that cleanup interval can be configured"""
        engine = MockEngine(outbox_test_domain)
        processor = OutboxProcessor(engine, "default", "default")

        # Default interval should be 86400 (1 day)
        assert processor.cleanup_config["cleanup_interval_ticks"] == 86400

        # Test that tick count starts at 0
        assert processor.tick_count == 0
