"""Tests for DomainMeta value object in message metadata."""

import pytest
from datetime import datetime, timezone

from protean.core.aggregate import BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils.eventing import (
    Message,
    MessageEnvelope,
    MessageHeaders,
    DomainMeta,
    Metadata,
    MessageType,
)


class User(BaseAggregate):
    email = String(identifier=True)
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
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


class TestDomainMetaFields:
    """Test suite for DomainMeta field validation and behavior"""

    def test_domain_meta_creation_with_all_fields(self):
        """Test creating DomainMeta with all fields populated"""
        domain_meta = DomainMeta(
            fqn="test.domain.Event",
            kind="EVENT",
            origin_stream="user-123",
            stream_category="user",
            version="v2",
            sequence_id="1.0",
            asynchronous=True,
            expected_version=5,
        )

        assert domain_meta.fqn == "test.domain.Event"
        assert domain_meta.kind == "EVENT"
        assert domain_meta.origin_stream == "user-123"
        assert domain_meta.stream_category == "user"
        assert domain_meta.version == "v2"
        assert domain_meta.sequence_id == "1.0"
        assert domain_meta.asynchronous is True
        assert domain_meta.expected_version == 5

    def test_domain_meta_creation_with_minimal_fields(self):
        """Test creating DomainMeta with only required fields"""
        domain_meta = DomainMeta(
            fqn="test.domain.Command",
            kind="COMMAND",
        )

        assert domain_meta.fqn == "test.domain.Command"
        assert domain_meta.kind == "COMMAND"
        assert domain_meta.origin_stream is None
        assert domain_meta.stream_category is None
        assert domain_meta.version == "v1"  # Default value
        assert domain_meta.sequence_id is None
        assert domain_meta.asynchronous is True  # Default value
        assert domain_meta.expected_version is None

    def test_domain_meta_with_event_kind(self):
        """Test DomainMeta for EVENT kind"""
        domain_meta = DomainMeta(
            fqn="test.UserRegistered",
            kind=MessageType.EVENT.value,
            origin_stream="user-abc123",
            stream_category="user",
            sequence_id="2",
        )

        assert domain_meta.kind == "EVENT"
        assert domain_meta.origin_stream == "user-abc123"
        assert domain_meta.stream_category == "user"
        assert domain_meta.sequence_id == "2"

    def test_domain_meta_with_command_kind(self):
        """Test DomainMeta for COMMAND kind"""
        domain_meta = DomainMeta(
            fqn="test.RegisterUser",
            kind=MessageType.COMMAND.value,
            stream_category="user:command",
        )

        assert domain_meta.kind == "COMMAND"
        assert domain_meta.stream_category == "user:command"
        # Commands typically don't have sequence_id
        assert domain_meta.sequence_id is None

    def test_domain_meta_stream_category_for_events(self):
        """Test that stream_category is properly set for events"""
        domain_meta = DomainMeta(
            fqn="order.OrderPlaced",
            kind="EVENT",
            origin_stream="order-xyz789",
            stream_category="order",
            sequence_id="1",
        )

        assert domain_meta.stream_category == "order"
        assert domain_meta.origin_stream == "order-xyz789"

    def test_domain_meta_stream_category_for_commands(self):
        """Test that stream_category includes :command suffix for commands"""
        domain_meta = DomainMeta(
            fqn="order.PlaceOrder",
            kind="COMMAND",
            stream_category="order:command",
        )

        assert domain_meta.stream_category == "order:command"

    def test_domain_meta_version_field(self):
        """Test version field behavior"""
        # Default version
        meta_default = DomainMeta(fqn="test.Event", kind="EVENT")
        assert meta_default.version == "v1"

        # Custom version
        meta_custom = DomainMeta(fqn="test.Event", kind="EVENT", version="v3")
        assert meta_custom.version == "v3"

    def test_domain_meta_asynchronous_field(self):
        """Test asynchronous field behavior"""
        # Default is True
        meta_async = DomainMeta(fqn="test.Event", kind="EVENT")
        assert meta_async.asynchronous is True

        # Explicit False
        meta_sync = DomainMeta(fqn="test.Event", kind="EVENT", asynchronous=False)
        assert meta_sync.asynchronous is False

    def test_domain_meta_expected_version_field(self):
        """Test expected_version field for optimistic concurrency"""
        # Without expected version
        meta_no_version = DomainMeta(fqn="test.Event", kind="EVENT")
        assert meta_no_version.expected_version is None

        # With expected version
        meta_with_version = DomainMeta(
            fqn="test.Event", kind="EVENT", expected_version=10
        )
        assert meta_with_version.expected_version == 10

    def test_domain_meta_sequence_id_for_event_sourced(self):
        """Test sequence_id for event sourced aggregates"""
        # Event sourced: sequence_id is just the version number
        meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            sequence_id="5",  # Just version for event sourced
        )
        assert meta.sequence_id == "5"

    def test_domain_meta_sequence_id_for_regular_aggregate(self):
        """Test sequence_id for regular aggregates with multiple events"""
        # Regular aggregate: sequence_id is version.eventnumber
        meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            sequence_id="0.3",  # version.eventnumber for regular aggregates
        )
        assert meta.sequence_id == "0.3"

    def test_domain_meta_to_dict(self):
        """Test converting DomainMeta to dictionary"""
        domain_meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            origin_stream="test-123",
            stream_category="test",
            version="v2",
            sequence_id="1.0",
            asynchronous=False,
            expected_version=7,
        )

        meta_dict = domain_meta.to_dict()

        assert meta_dict == {
            "fqn": "test.Event",
            "kind": "EVENT",
            "origin_stream": "test-123",
            "stream_category": "test",
            "version": "v2",
            "sequence_id": "1.0",
            "asynchronous": False,
            "expected_version": 7,
        }

    def test_domain_meta_from_dict(self):
        """Test creating DomainMeta from dictionary"""
        meta_dict = {
            "fqn": "test.Command",
            "kind": "COMMAND",
            "stream_category": "test:command",
            "version": "v1",
            "asynchronous": True,
        }

        domain_meta = DomainMeta(**meta_dict)

        assert domain_meta.fqn == "test.Command"
        assert domain_meta.kind == "COMMAND"
        assert domain_meta.stream_category == "test:command"
        assert domain_meta.version == "v1"
        assert domain_meta.asynchronous is True


class TestDomainMetaInMessage:
    """Test DomainMeta when used within Message objects"""

    def test_message_with_domain_meta(self):
        """Test creating a Message with DomainMeta"""
        domain_meta = DomainMeta(
            fqn="test.Registered",
            kind="EVENT",
            origin_stream="user-123",
            stream_category="user",
            sequence_id="1",
        )

        message = Message(
            data={"email": "test@example.com", "name": "Test User"},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="msg-123",
                    type="test.Registered",
                    time=datetime.now(timezone.utc),
                    stream="user-123",
                ),
                domain=domain_meta,
                envelope=MessageEnvelope(specversion="1.0", checksum="abc123"),
            ),
        )

        assert message.metadata.domain.fqn == "test.Registered"
        assert message.metadata.domain.kind == "EVENT"
        assert message.metadata.domain.origin_stream == "user-123"
        assert message.metadata.domain.stream_category == "user"
        assert message.metadata.domain.sequence_id == "1"

    def test_message_deserialization_with_domain_meta(self):
        """Test deserializing a message preserves DomainMeta"""
        message_dict = {
            "data": {"email": "test@example.com"},
            "metadata": {
                "headers": {
                    "id": "msg-456",
                    "type": "test.Register",
                    "time": datetime.now(timezone.utc).isoformat(),
                    "stream": "user:command",
                },
                "domain": {
                    "fqn": "test.Register",
                    "kind": "COMMAND",
                    "stream_category": "user:command",
                    "version": "v1",
                    "asynchronous": True,
                },
                "envelope": {"specversion": "1.0", "checksum": "xyz789"},
            },
        }

        message = Message.deserialize(message_dict, validate=False)

        assert message.metadata.domain.fqn == "test.Register"
        assert message.metadata.domain.kind == "COMMAND"
        assert message.metadata.domain.stream_category == "user:command"
        assert message.metadata.domain.version == "v1"
        assert message.metadata.domain.asynchronous is True

    def test_message_with_partial_domain_meta(self):
        """Test message with partially populated DomainMeta"""
        message_dict = {
            "data": {"test": "data"},
            "metadata": {
                "headers": {
                    "id": "msg-789",
                    "type": "test.Event",
                    "stream": "test-stream",
                },
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    # Only required fields, others should use defaults or be None
                },
            },
        }

        message = Message.deserialize(message_dict, validate=False)

        assert message.metadata.domain.fqn == "test.Event"
        assert message.metadata.domain.kind == "EVENT"
        assert message.metadata.domain.origin_stream is None
        assert message.metadata.domain.stream_category is None
        assert message.metadata.domain.version == "v1"  # Default
        assert message.metadata.domain.asynchronous is True  # Default

    def test_event_message_with_stream_category(self):
        """Test that stream_category can be stored in event metadata"""
        # Create a message directly with stream_category in domain metadata
        message = Message(
            data={"id": "user-123", "email": "test@example.com", "name": "Test"},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="event-123",
                    type="test.Registered",
                    time=datetime.now(timezone.utc),
                    stream="redis_streams::user-user-123",
                ),
                domain=DomainMeta(
                    fqn="test.Registered",
                    kind="EVENT",
                    origin_stream="user-user-123",
                    stream_category="redis_streams::user",  # For broker routing
                    sequence_id="1",
                ),
                envelope=MessageEnvelope(specversion="1.0", checksum="test"),
            ),
        )

        assert message.metadata.domain.stream_category == "redis_streams::user"
        assert message.metadata.domain.origin_stream == "user-user-123"

    def test_command_message_with_stream_category(self):
        """Test that stream_category with :command suffix can be stored"""
        # Create a message directly with stream_category for commands
        message = Message(
            data={"id": "cmd-123", "email": "test@example.com", "name": "Test"},
            metadata=Metadata(
                headers=MessageHeaders(
                    id="cmd-123",
                    type="test.Register",
                    time=datetime.now(timezone.utc),
                    stream="redis_streams::user:command",
                ),
                domain=DomainMeta(
                    fqn="test.Register",
                    kind="COMMAND",
                    stream_category="redis_streams::user:command",  # Command suffix
                ),
                envelope=MessageEnvelope(specversion="1.0", checksum="test"),
            ),
        )

        assert message.metadata.domain.stream_category == "redis_streams::user:command"


class TestDomainMetaCompatibility:
    """Test backward compatibility and edge cases"""

    def test_domain_meta_without_stream_category(self):
        """Test that DomainMeta works without stream_category (backward compat)"""
        # Old messages without stream_category should still work
        message_dict = {
            "data": {"test": "data"},
            "metadata": {
                "headers": {"id": "msg-old", "type": "test.Event"},
                "domain": {
                    "fqn": "test.Event",
                    "kind": "EVENT",
                    "origin_stream": "test-123",
                    # No stream_category field
                },
            },
        }

        message = Message.deserialize(message_dict, validate=False)

        assert message.metadata.domain.fqn == "test.Event"
        assert message.metadata.domain.origin_stream == "test-123"
        assert message.metadata.domain.stream_category is None

    def test_domain_meta_with_empty_stream_category(self):
        """Test DomainMeta with empty stream_category"""
        domain_meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            stream_category="",  # Empty string
        )

        assert domain_meta.stream_category == ""

    def test_domain_meta_immutability(self):
        """Test that DomainMeta is immutable (as a ValueObject)"""
        domain_meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            stream_category="test",
        )

        with pytest.raises(IncorrectUsageError) as exc:
            domain_meta.stream_category = "modified"

        assert "immutable" in str(exc.value).lower()

    def test_domain_meta_equality(self):
        """Test DomainMeta equality comparison"""
        meta1 = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            stream_category="test",
            sequence_id="1",
        )

        meta2 = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            stream_category="test",
            sequence_id="1",
        )

        meta3 = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            stream_category="different",
            sequence_id="1",
        )

        assert meta1 == meta2
        assert meta1 != meta3

    def test_domain_meta_hash(self):
        """Test DomainMeta can be used in sets/dicts"""
        meta1 = DomainMeta(fqn="test.Event", kind="EVENT", stream_category="test")

        meta2 = DomainMeta(fqn="test.Event", kind="EVENT", stream_category="test")

        # Should be hashable
        meta_set = {meta1, meta2}
        assert len(meta_set) == 1  # Same values, should be deduplicated


class TestDomainMetaValidation:
    """Test validation and error handling for DomainMeta"""

    def test_invalid_kind_value(self):
        """Test that invalid kind values are stored (no validation at this level)"""
        # DomainMeta itself doesn't validate kind values
        # Validation happens at Message.to_domain_object() level
        domain_meta = DomainMeta(
            fqn="test.Invalid",
            kind="INVALID_KIND",  # Not EVENT or COMMAND
        )

        assert domain_meta.kind == "INVALID_KIND"

    def test_none_values_in_optional_fields(self):
        """Test that None values are properly handled in optional fields"""
        domain_meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            origin_stream=None,
            stream_category=None,
            sequence_id=None,
            expected_version=None,
        )

        assert domain_meta.origin_stream is None
        assert domain_meta.stream_category is None
        assert domain_meta.sequence_id is None
        assert domain_meta.expected_version is None

    def test_special_characters_in_stream_category(self):
        """Test that special characters in stream_category are preserved"""
        # Stream categories might include special chars like :: or :
        domain_meta = DomainMeta(
            fqn="test.Event",
            kind="EVENT",
            stream_category="redis_streams::user:special-chars_123",
        )

        assert domain_meta.stream_category == "redis_streams::user:special-chars_123"
