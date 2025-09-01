from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.command import BaseCommand
from protean.exceptions import DeserializationError
from protean.fields import Identifier, String
from protean.utils.eventing import (
    Message,
    MessageEnvelope,
    MessageHeaders,
    TraceParent,
    DomainMeta,
    Metadata,
)


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Registered(BaseEvent):
    id = Identifier(identifier=True)
    email = String()
    name = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


class TestTraceParent:
    """Test suite for TraceParent value object functionality"""

    def test_traceparent_creation_with_valid_fields(self):
        """Test creating TraceParent with valid trace_id and parent_id"""
        trace_id = "1234567890abcdef1234567890abcdef"  # 32 chars
        parent_id = "abcdef1234567890"  # 16 chars

        traceparent = TraceParent(trace_id=trace_id, parent_id=parent_id, sampled=True)

        assert traceparent.trace_id == trace_id
        assert traceparent.parent_id == parent_id
        assert traceparent.sampled is True

    def test_traceparent_build_from_valid_string(self):
        """Test building TraceParent from valid traceparent string format"""
        traceparent_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

        traceparent = TraceParent.build(traceparent_str)

        assert traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        assert traceparent.parent_id == "abcdef1234567890"
        assert traceparent.sampled is True

    def test_traceparent_build_from_unsampled_string(self):
        """Test building TraceParent with sampled=False"""
        traceparent_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-00"

        traceparent = TraceParent.build(traceparent_str)

        assert traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        assert traceparent.parent_id == "abcdef1234567890"
        assert traceparent.sampled is False

    def test_traceparent_build_with_invalid_format(self):
        """Test that invalid traceparent format returns None"""
        invalid_formats = [
            "invalid",
            "1234-5678",
            "00-1234-5678",  # Too few parts
            "00-1234-5678-9abc-def0-extra",  # Too many parts
            "01-1234567890abcdef1234567890abcdef-abcdef1234567890-01",  # Wrong version
            "1234567890abcdef1234567890abcdef-abcdef1234567890-01",  # Missing version
            "",
            None,
        ]

        for invalid_format in invalid_formats:
            result = TraceParent.build(invalid_format)
            assert result is None

    def test_traceparent_to_dict_sampled(self):
        """Test to_dict returns proper formatted string when sampled=True"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )

        result = traceparent.to_dict()
        assert result == "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

    def test_traceparent_to_dict_unsampled(self):
        """Test to_dict returns proper formatted string when sampled=False"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=False,
        )

        result = traceparent.to_dict()
        assert result == "00-1234567890abcdef1234567890abcdef-abcdef1234567890-00"

    def test_traceparent_correlation_id_property(self):
        """Test that correlation_id property returns trace_id"""
        trace_id = "1234567890abcdef1234567890abcdef"
        traceparent = TraceParent(
            trace_id=trace_id, parent_id="abcdef1234567890", sampled=False
        )

        assert traceparent.correlation_id == trace_id

    def test_traceparent_causation_id_property(self):
        """Test that causation_id property returns parent_id"""
        parent_id = "abcdef1234567890"
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id=parent_id,
            sampled=False,
        )

        assert traceparent.causation_id == parent_id

    def test_traceparent_default_sampled_false(self):
        """Test that sampled defaults to False"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef", parent_id="abcdef1234567890"
        )

        assert traceparent.sampled is False

    def test_traceparent_roundtrip_build_to_dict(self):
        """Test that build() and to_dict() are inverse operations"""
        original_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

        traceparent = TraceParent.build(original_str)
        result_str = traceparent.to_dict()

        assert result_str == original_str


class TestMessageHeaders:
    """Test suite for MessageHeaders value object functionality"""

    def test_message_headers_creation_with_traceparent(self):
        """Test creating MessageHeaders with traceparent"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )

        headers = MessageHeaders(traceparent=traceparent)

        assert headers.traceparent == traceparent
        assert headers.traceparent.correlation_id == "1234567890abcdef1234567890abcdef"

    def test_message_headers_creation_empty(self):
        """Test creating empty MessageHeaders"""
        headers = MessageHeaders()

        assert headers.traceparent is None

    def test_message_headers_to_dict_with_traceparent(self):
        """Test MessageHeaders serialization with traceparent"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(traceparent=traceparent)

        headers_dict = headers.to_dict()

        assert "traceparent" in headers_dict
        assert (
            headers_dict["traceparent"]["trace_id"]
            == "1234567890abcdef1234567890abcdef"
        )
        assert headers_dict["traceparent"]["parent_id"] == "abcdef1234567890"
        assert headers_dict["traceparent"]["sampled"] is True

    def test_message_headers_to_dict_empty(self):
        """Test MessageHeaders serialization when empty"""
        headers = MessageHeaders()
        headers_dict = headers.to_dict()

        assert "traceparent" in headers_dict
        assert headers_dict["traceparent"] is None

    def test_message_headers_build_from_traceparent_string(self):
        """Test MessageHeaders.build() method with traceparent string"""
        traceparent_str = "00-1234567890abcdef1234567890abcdef-abcdef1234567890-01"

        headers = MessageHeaders.build(traceparent=traceparent_str)

        assert headers.traceparent is not None
        assert headers.traceparent.trace_id == "1234567890abcdef1234567890abcdef"
        assert headers.traceparent.parent_id == "abcdef1234567890"
        assert headers.traceparent.sampled is True

    def test_message_headers_build_from_invalid_traceparent_string(self):
        """Test MessageHeaders.build() method with invalid traceparent string"""
        invalid_traceparent = "invalid-traceparent"

        headers = MessageHeaders.build(traceparent=invalid_traceparent)

        # build() should handle invalid traceparent gracefully
        assert headers.traceparent is None

    def test_message_headers_build_from_empty_traceparent(self):
        """Test MessageHeaders.build() method with empty/None traceparent"""
        headers1 = MessageHeaders.build(traceparent=None)
        headers2 = MessageHeaders.build(traceparent="")

        # Both should create MessageHeaders with no traceparent
        assert headers1.traceparent is None
        assert headers2.traceparent is None


class TestMessageWithHeaders:
    """Test suite for Message class with MessageHeaders functionality"""

    def test_message_creation_with_headers(self):
        """Test creating Message with headers"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(
            id="test-id",
            type="test.event",
            stream="test-stream",
            traceparent=traceparent,
        )

        message = Message(
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                envelope=MessageEnvelope(specversion="1.0", checksum=""),
                headers=headers,
                domain=DomainMeta(fqn="test.Event", kind="EVENT"),
            ),
        )

        assert message.metadata.headers == headers
        assert (
            message.metadata.headers.traceparent.correlation_id
            == "1234567890abcdef1234567890abcdef"
        )

    def test_message_creation_without_explicit_headers(self):
        """Test creating Message without explicit headers creates headers from legacy params"""
        message = Message(
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                envelope=MessageEnvelope(specversion="1.0", checksum=""),
                headers=MessageHeaders(
                    id="test-id",
                    type="test.event",
                    stream="test-stream",
                ),
                domain=DomainMeta(fqn="test.Event", kind="EVENT"),
            ),
        )

        # Headers should be auto-created from legacy parameters
        assert message.metadata.headers is not None
        assert message.metadata.headers.type == "test.event"

    def test_message_creation_with_no_headers_or_legacy_params(self):
        """Test creating Message with no headers and no legacy params leaves headers as None"""
        message = Message(
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                domain=DomainMeta(fqn="test.Event", kind="EVENT"),
                headers=MessageHeaders(stream="test-stream"),
                # Headers now include stream
            ),
        )

        # Headers should now contain stream
        assert message.metadata.headers is not None
        assert message.metadata.headers.stream == "test-stream"

    def test_message_to_dict_includes_headers(self):
        """Test that to_dict() includes headers when present"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(
            id="test-id",
            type="test.event",
            stream="test-stream",
            traceparent=traceparent,
        )

        message = Message(
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                envelope=MessageEnvelope(specversion="1.0", checksum=""),
                headers=headers,
                domain=DomainMeta(fqn="test.Event", kind="EVENT"),
            ),
        )

        message_dict = message.to_dict()

        assert "metadata" in message_dict
        assert "headers" in message_dict["metadata"]
        assert (
            message_dict["metadata"]["headers"]["traceparent"]["trace_id"]
            == "1234567890abcdef1234567890abcdef"
        )
        assert message_dict["metadata"]["headers"]["traceparent"]["sampled"] is True

    def test_message_to_dict_includes_headers_when_legacy_params_provided(self):
        """Test that to_dict() includes headers when legacy params are provided"""
        message = Message(
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                envelope=MessageEnvelope(specversion="1.0", checksum=""),
                headers=MessageHeaders(
                    id="test-id",
                    type="test.event",
                    stream="test-stream",
                ),
                domain=DomainMeta(
                    fqn="test.Event",
                    kind="EVENT",
                ),
            ),
        )

        message_dict = message.to_dict()

        assert "metadata" in message_dict
        assert "headers" in message_dict["metadata"]
        assert message_dict["metadata"]["headers"] is not None
        assert message_dict["metadata"]["headers"]["type"] == "test.event"

    def test_message_from_dict_with_headers(self):
        """Test creating Message from dict with headers"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "headers": {
                    "id": "test-id",
                    "type": "test.event",
                    "stream": "test-stream",
                    "traceparent": {
                        "trace_id": "1234567890abcdef1234567890abcdef",
                        "parent_id": "abcdef1234567890",
                        "sampled": True,
                    },
                },
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "version": "v1",
                    "sequence_id": "1",
                    "asynchronous": True,
                },
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        assert message.metadata.headers is not None
        assert (
            message.metadata.headers.traceparent.trace_id
            == "1234567890abcdef1234567890abcdef"
        )
        assert message.metadata.headers.traceparent.sampled is True

    def test_message_from_dict_without_headers_creates_headers(self):
        """Test creating Message from dict without headers creates headers from legacy fields"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "headers": {
                    "id": "msg-123",
                    "type": "test.event",
                    "stream": "test-stream",
                    "time": None,
                },
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "version": "v1",
                    "sequence_id": "1",
                    "asynchronous": True,
                },
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        # Headers should be in metadata
        assert message.metadata.headers is not None
        assert message.metadata.headers.id == "msg-123"
        assert message.metadata.headers.type == "test.event"

    def test_message_from_dict_with_empty_headers_populates_from_legacy_fields(self):
        """Test creating Message from dict with empty headers uses legacy fields"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "headers": {
                    "id": "msg-123",
                    "type": "test.event",
                    "stream": "test-stream",
                    "traceparent": None,
                },
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "version": "v1",
                    "sequence_id": "1",
                    "asynchronous": True,
                },
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        # Headers should be populated with correct values
        assert message.metadata.headers is not None
        assert message.metadata.headers.id == "msg-123"
        assert message.metadata.headers.type == "test.event"
        assert message.metadata.headers.traceparent is None

    def test_message_from_dict_with_valid_traceparent(self):
        """Test creating Message from dict with valid traceparent data"""
        message_dict = {
            "envelope": {"specversion": "1.0", "checksum": ""},
            "stream_name": "test-stream",
            "type": "test.event",
            "data": {"test": "data"},
            "metadata": {
                "headers": {
                    "id": "test-id",
                    "type": "test.event",
                    "stream": "test-stream",
                    "traceparent": {
                        "trace_id": "1234567890abcdef1234567890abcdef",
                        "parent_id": "abcdef1234567890",
                        "sampled": True,
                    },
                },
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "version": "v1",
                    "sequence_id": "1",
                    "asynchronous": True,
                },
            },
            "position": 1,
            "global_position": 1,
            "time": "2023-01-01T00:00:00Z",
            "id": "msg-123",
        }

        message = Message.from_dict(message_dict)

        # With valid traceparent data, headers should be properly created
        assert message.metadata.headers is not None
        assert message.metadata.headers.traceparent is not None
        assert (
            message.metadata.headers.traceparent.trace_id
            == "1234567890abcdef1234567890abcdef"
        )
        assert message.metadata.headers.traceparent.sampled is True

    def test_message_roundtrip_with_headers(self):
        """Test that headers are preserved through serialization/deserialization cycle"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(
            id="test-id",
            type="test.event",
            stream="test-stream",
            traceparent=traceparent,
        )

        # Create original message
        original_message = Message(
            stream_name="test-stream",
            data={"test": "data"},
            metadata=Metadata(
                envelope=MessageEnvelope(specversion="1.0", checksum=""),
                headers=headers,
                domain=DomainMeta(fqn="test.Event", kind="EVENT"),
            ),
        )

        # Serialize to dict
        message_dict = original_message.to_dict()

        # Deserialize back to message
        reconstructed_message = Message.from_dict(message_dict, validate=False)

        # Verify headers are preserved
        assert reconstructed_message.metadata.headers is not None
        assert (
            reconstructed_message.metadata.headers.traceparent.trace_id
            == "1234567890abcdef1234567890abcdef"
        )
        assert (
            reconstructed_message.metadata.headers.traceparent.parent_id
            == "abcdef1234567890"
        )
        assert reconstructed_message.metadata.headers.traceparent.sampled is True
        assert (
            reconstructed_message.metadata.headers.traceparent.correlation_id
            == "1234567890abcdef1234567890abcdef"
        )
        assert (
            reconstructed_message.metadata.headers.traceparent.causation_id
            == "abcdef1234567890"
        )

    def test_message_to_message_creates_headers_with_type(self):
        """Test that to_message creates message with headers containing type"""
        identifier = str(uuid4())
        user = User(id=identifier, email="john.doe@example.com", name="John Doe")
        user.raise_(
            Registered(id=identifier, email="john.doe@example.com", name="John Doe")
        )

        message = Message.to_message(user._events[-1])

        # Headers should be created with type from the event
        assert message.metadata.headers is not None
        assert message.metadata.headers.type is not None

    def test_message_error_context_includes_headers(self):
        """Test that error context includes headers information"""
        traceparent = TraceParent(
            trace_id="1234567890abcdef1234567890abcdef",
            parent_id="abcdef1234567890",
            sampled=True,
        )
        headers = MessageHeaders(
            id="test-msg-with-headers",
            type="unregistered.type",
            traceparent=traceparent,
        )

        message = Message(
            stream_name="test-stream",
            data={"field1": "value1"},
            metadata=Metadata(
                envelope=MessageEnvelope(specversion="1.0", checksum=""),
                headers=headers,
                domain=DomainMeta(fqn="unregistered.Type", kind="EVENT"),
            ),
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_object()

        error = exc_info.value
        context = error.context

        # Verify headers are included in error context
        assert "envelope" in context
        assert context["envelope"] is not None
