"""Test cases for edge cases and coverage improvements in message handling."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.command import BaseCommand
from protean.fields import Identifier, String
from protean.utils.eventing import (
    Message,
    MessageEnvelope,
    MessageHeaders,
    DomainMeta,
    Metadata,
    EventStoreMeta,
    MessageType,
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


class UnregisteredCommand(BaseCommand):
    """Command that won't be registered with domain."""

    id = Identifier(identifier=True)
    data = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


class TestTraceParentHandling:
    """Test TraceParent instantiation in headers"""

    def test_build_headers_with_traceparent_dict(self):
        """Test that traceparent dict is converted to TraceParent object."""
        trace_id = "1234567890abcdef1234567890abcdef"
        parent_id = "abcdef1234567890"

        message_dict = {
            "data": {"test": "data"},
            "metadata": {
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    "version": "v1",
                }
            },
            "headers": {
                "id": str(uuid4()),
                "type": "test.Event",
                "time": datetime.now(timezone.utc).isoformat(),
                "stream": "test-stream",
                "traceparent": {
                    "trace_id": trace_id,
                    "parent_id": parent_id,
                    "sampled": True,
                },
            },
        }

        # This should instantiate TraceParent from the dict
        metadata_dict = {}
        Message._build_headers(metadata_dict, message_dict)

        assert metadata_dict["headers"] is not None
        assert metadata_dict["headers"].traceparent is not None
        assert metadata_dict["headers"].traceparent.trace_id == trace_id
        assert metadata_dict["headers"].traceparent.parent_id == parent_id
        assert metadata_dict["headers"].traceparent.sampled is True


class TestMessageExtractionFallbacks:
    """Test fallback values in extraction methods."""

    def test_extract_message_id_fallback(self):
        """Test _extract_message_id falls back to message dict."""
        # Create a message without headers id
        msg = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    type="test.Event",
                    time=datetime.now(timezone.utc),
                    # id is not set
                ),
            },
        )

        message_dict = {"id": "fallback-id-123"}

        # Should fall back to message dict
        result = Message._extract_message_id(msg, message_dict)
        assert result == "fallback-id-123"

    def test_extract_message_type_fallback(self):
        """Test _extract_message_type falls back to message dict."""
        # Create a message without headers type
        msg = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    time=datetime.now(timezone.utc),
                    # type is not set
                ),
            },
        )

        message_dict = {"type": "fallback.Event.v1"}

        # Should fall back to message dict
        result = Message._extract_message_type(msg, message_dict)
        assert result == "fallback.Event.v1"


class TestMessageDeserializationEdgeCases:
    """Test edge cases in message deserialization."""

    def test_deserialize_message_with_headers_fallback_values(self):
        """Test deserializing message that falls back to root-level values for headers."""
        message_dict = {
            "data": {"email": "test@example.com", "name": "Test User"},
            "metadata": {
                "domain": {
                    "fqn": "test.User.Registered.v1",
                    "kind": "EVENT",
                    "version": "v1",
                },
            },
            # These values should be picked up when headers aren't present
            "id": str(uuid4()),
            "time": datetime.now(timezone.utc).isoformat(),
            "type": "test.Registered.v1",
            "stream": "test::user-123",
        }

        message = Message.deserialize(message_dict, validate=False)

        # Verify headers were constructed with fallback values
        assert message.metadata.headers.id == message_dict["id"]
        assert message.metadata.headers.time.isoformat() == message_dict["time"]
        assert message.metadata.headers.type == message_dict["type"]
        assert message.metadata.headers.stream == message_dict["stream"]

    def test_deserialize_message_with_traceparent_in_headers(self):
        """Test deserializing message with traceparent in headers."""
        trace_id = "1234567890abcdef1234567890abcdef"
        parent_id = "abcdef1234567890"

        message_dict = {
            "data": {"email": "test@example.com", "name": "Test User"},
            "metadata": {
                "headers": {
                    "id": str(uuid4()),
                    "time": datetime.now(timezone.utc).isoformat(),
                    "type": "test.Registered.v1",
                    "stream": "test::user-123",
                    "traceparent": {
                        "trace_id": trace_id,
                        "parent_id": parent_id,
                        "sampled": True,
                    },
                },
                "domain": {
                    "fqn": "test.User.Registered.v1",
                    "kind": "EVENT",
                    "version": "v1",
                },
            },
        }

        message = Message.deserialize(message_dict, validate=False)

        # Verify traceparent was properly constructed
        assert message.metadata.headers.traceparent is not None
        assert message.metadata.headers.traceparent.trace_id == trace_id
        assert message.metadata.headers.traceparent.parent_id == parent_id
        assert message.metadata.headers.traceparent.sampled is True

    def test_deserialize_message_with_event_store_meta_from_root(self):
        """Test deserializing message with position and global_position at root level."""
        message_dict = {
            "data": {"email": "test@example.com", "name": "Test User"},
            "metadata": {
                "headers": {
                    "id": str(uuid4()),
                    "time": datetime.now(timezone.utc).isoformat(),
                    "type": "test.Registered.v1",
                    "stream": "test::user-123",
                },
                "domain": {
                    "fqn": "test.User.Registered.v1",
                    "kind": "EVENT",
                    "version": "v1",
                },
            },
            # Position and global_position at root level
            "position": 5,
            "global_position": 100,
        }

        message = Message.deserialize(message_dict, validate=False)

        # Verify EventStoreMeta was created
        assert message.metadata.event_store is not None
        assert message.metadata.event_store.position == 5
        assert message.metadata.event_store.global_position == 100

    def test_deserialize_message_with_only_position(self):
        """Test deserializing message with only position (no global_position)."""
        message_dict = {
            "data": {"email": "test@example.com", "name": "Test User"},
            "metadata": {
                "headers": {
                    "id": str(uuid4()),
                    "time": datetime.now(timezone.utc).isoformat(),
                    "type": "test.Registered.v1",
                    "stream": "test::user-123",
                },
                "domain": {
                    "fqn": "test.User.Registered.v1",
                    "kind": "EVENT",
                    "version": "v1",
                },
            },
            "position": 5,
            # No global_position provided
        }

        message = Message.deserialize(message_dict, validate=False)

        # Verify EventStoreMeta was created with None for global_position
        assert message.metadata.event_store is not None
        assert message.metadata.event_store.position == 5
        assert message.metadata.event_store.global_position is None


class TestMessageSafeGetAttr:
    """Test the _safe_get_attr helper method."""

    def test_safe_get_attr_with_valid_path(self):
        """Test _safe_get_attr with a valid nested path."""
        # Create a message with full metadata structure
        message = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    stream="test-stream",
                    type="test.Event",
                    time=datetime.now(timezone.utc),
                ),
                "event_store": EventStoreMeta(
                    position=10,
                    global_position=100,
                ),
            },
        )

        # Test accessing nested attributes
        result = message._safe_get_attr(message.metadata, "headers.stream")
        assert result == "test-stream"

        result = message._safe_get_attr(message.metadata, "event_store.position")
        assert result == 10

    def test_safe_get_attr_with_missing_attribute(self):
        """Test _safe_get_attr returns default when attribute is missing."""
        message = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    type="test.Event",
                    time=datetime.now(timezone.utc),
                    # stream is not set
                ),
            },
        )

        # Test accessing missing attribute
        result = message._safe_get_attr(
            message.metadata, "headers.stream", "default-stream"
        )
        assert result == "default-stream"

        # Test accessing missing nested object
        result = message._safe_get_attr(
            message.metadata, "event_store.position", "no-position"
        )
        assert result == "no-position"

    def test_safe_get_attr_with_attribute_error(self):
        """Test _safe_get_attr handles AttributeError gracefully."""
        message = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    type="test.Event",
                    time=datetime.now(timezone.utc),
                )
            },
        )

        # Try to access a deeply nested path that doesn't exist
        result = message._safe_get_attr(None, "headers.stream", "fallback")
        assert result == "fallback"

        # Test with an object that doesn't have the expected structure
        result = message._safe_get_attr("not_an_object", "some.path", "default")
        assert result == "default"


class TestMessageBuildErrorContext:
    """Test the _build_error_context helper method."""

    def test_build_error_context_with_full_metadata(self):
        """Test building error context with complete metadata."""
        message = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    stream="test-stream",
                    type="test.Event",
                    time=datetime.now(timezone.utc),
                ),
                "domain": DomainMeta(
                    fqn="test.Event",
                    kind="EVENT",
                    version="v1",
                ),
                "event_store": EventStoreMeta(
                    position=10,
                    global_position=100,
                ),
                "envelope": MessageEnvelope(
                    specversion="1.0",
                    checksum="abc123",
                ),
            },
        )

        error = ValueError("Test error")
        context = message._build_error_context(error)

        assert context["type"] == "test.Event"
        assert context["stream_name"] == "test-stream"
        assert context["metadata_kind"] == "EVENT"
        assert context["position"] == 10
        assert context["global_position"] == 100
        assert context["original_exception_type"] == "ValueError"
        assert context["has_metadata"] is True
        assert context["has_data"] is True
        assert context["envelope"]["checksum"] == "abc123"


class TestValidateAggregateAssociation:
    """Test _validate_aggregate_association method"""

    def test_validate_aggregate_association_raises_error(self):
        """Test that validation raises error for unassociated objects."""
        from protean.exceptions import ConfigurationError

        # Create a mock object with meta_.part_of = None
        class MockCommand:
            class meta_:
                part_of = None

            def __init__(self):
                self.__class__.__name__ = "OrphanCommand"

        orphan = MockCommand()

        # This should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            Message._validate_aggregate_association(orphan)

        assert "is not associated with an aggregate" in str(exc_info.value)
        assert "OrphanCommand" in str(exc_info.value)


class TestMessageFromDomainObjectEdgeCases:
    """Test edge cases in from_domain_object method."""

    def test_determine_expected_version_for_command(self):
        """Test that commands don't get expected_version set."""
        cmd = Register(id=str(uuid4()), email="test@example.com", name="Test User")

        # Create metadata with domain kind set to COMMAND
        metadata_dict = {
            "headers": MessageHeaders(
                id=str(uuid4()),
                type="test.Register",
                time=datetime.now(timezone.utc),
            ),
            "domain": DomainMeta(
                fqn="test.Register",
                kind=MessageType.COMMAND.value,
                version="v1",
            ),
        }
        # Use object.__setattr__ to bypass immutability check
        object.__setattr__(cmd, "_metadata", Metadata(**metadata_dict))

        # Commands should return None for expected_version
        result = Message._determine_expected_version(cmd)
        assert result is None

    def test_determine_expected_version_for_fact_event(self, test_domain):
        """Test that fact events don't get expected_version set."""

        class UserFactEvent(BaseEvent):
            id = Identifier(identifier=True)
            email = String()
            name = String()

        # Register the fact event
        test_domain.register(UserFactEvent, part_of=User)
        test_domain.init(traverse=False)

        # Simulate a fact event (name ends with FactEvent)
        metadata_dict = {
            "headers": MessageHeaders(
                id=str(uuid4()),
                type="test.UserFactEvent",
                time=datetime.now(timezone.utc),
            ),
            "domain": DomainMeta(
                fqn="test.UserFactEvent",
                kind=MessageType.EVENT.value,
                version="v1",
            ),
        }

        # Create an instance with the mocked class
        fact_event = UserFactEvent(
            id=str(uuid4()), email="test@example.com", name="Test User"
        )
        object.__setattr__(fact_event, "_metadata", Metadata(**metadata_dict))

        result = Message._determine_expected_version(fact_event)
        assert result is None


class TestMessageToDomainObjectValidation:
    """Test validation in to_domain_object method."""

    def test_to_domain_object_success(self, test_domain):
        """Test successful conversion to domain object"""
        # Use the actual registered type name from the domain
        # The domain registers it as "test.Registered.v1"
        message = Message(
            data={"id": str(uuid4()), "email": "test@example.com", "name": "Test User"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    type=Registered.__type__,  # Use the actual registered type
                    time=datetime.now(timezone.utc),
                    stream="test::user-123",
                ),
                "domain": DomainMeta(
                    fqn="test.Registered",
                    kind=MessageType.EVENT.value,
                    version="v1",
                ),
            },
        )

        result = message.to_domain_object()

        assert isinstance(result, Registered)
        assert result.email == "test@example.com"
        assert result.name == "Test User"
        # The metadata is passed through, we just verify it's set
        assert result._metadata is not None
        assert result._metadata.headers.id == message.metadata.headers.id

    def test_to_domain_object_with_unsupported_kind(self, test_domain):
        """Test that to_domain_object raises error for unsupported message kind."""
        from protean.exceptions import DeserializationError

        message = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    type="test.Unknown",
                    time=datetime.now(timezone.utc),
                ),
                "domain": DomainMeta(
                    fqn="test.Unknown",
                    kind="UNSUPPORTED",  # Invalid kind
                    version="v1",
                ),
            },
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_domain_object()

        # The InvalidDataError is wrapped in a DeserializationError
        assert "Message type is not supported for deserialization" in str(
            exc_info.value
        )

    def test_to_domain_object_with_unregistered_type(self, test_domain):
        """Test that to_domain_object raises error for unregistered message type."""
        from protean.exceptions import DeserializationError

        message = Message(
            data={"test": "data"},
            metadata={
                "headers": MessageHeaders(
                    id=str(uuid4()),
                    type="test.UnregisteredEvent.v1",
                    time=datetime.now(timezone.utc),
                ),
                "domain": DomainMeta(
                    fqn="test.UnregisteredEvent",
                    kind=MessageType.EVENT.value,
                    version="v1",
                ),
            },
        )

        with pytest.raises(DeserializationError) as exc_info:
            message.to_domain_object()

        # The ConfigurationError is wrapped in a DeserializationError
        assert "is not registered with the domain" in str(exc_info.value)
