from __future__ import annotations

import hashlib
import json
import logging
from enum import Enum
from typing import TYPE_CHECKING, Union

from protean.core.value_object import BaseValueObject
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    InvalidDataError,
    DeserializationError,
)
from protean.fields import Boolean, DateTime, Field, String, ValueObject, Dict
from protean.fields.basic import Integer
from protean.fields.association import Association, Reference
from protean.utils.container import BaseContainer, OptionsMixin
from protean.utils.reflection import _ID_FIELD_NAME, declared_fields, fields
from protean.utils.globals import current_domain

if TYPE_CHECKING:
    from protean.core.command import BaseCommand
    from protean.core.event import BaseEvent

logger = logging.getLogger(__name__)


class MessageType(Enum):
    EVENT = "EVENT"
    COMMAND = "COMMAND"
    READ_POSITION = "READ_POSITION"


class MessageEnvelope(BaseValueObject):
    """Message envelope containing integrity and versioning information."""

    specversion = String(default="1.0")
    checksum = String()

    @classmethod
    def build(cls, payload: dict) -> MessageEnvelope:
        return cls(checksum=cls.compute_checksum(payload))

    @classmethod
    def compute_checksum(cls, payload: dict) -> str:
        """Compute checksum for message integrity validation."""
        json_data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_data.encode("utf-8")).hexdigest()


class TraceParent(BaseValueObject):
    """Represents the trace context for distributed tracing (OpenTelemetry compatible)

    Format:
    traceparent: 00-<trace_id>-<parent_id>-<trace_flags>
    """

    trace_id = String(max_length=32, min_length=32)
    parent_id = String(max_length=16, min_length=16)
    sampled = Boolean(default=False)

    @classmethod
    def build(cls, traceparent: str) -> TraceParent:
        try:
            parts = traceparent.split("-")
            if len(parts) != 4:
                raise ValueError("Traceparent must have 4 parts separated by hyphens")

            version, trace_id, parent_id, sampled_flag = parts

            # Version should always be "00" for current W3C spec
            if version != "00":
                raise ValueError(f"Unsupported traceparent version: {version}")

            sampled = sampled_flag == "01"
            return cls(trace_id=trace_id, parent_id=parent_id, sampled=sampled)
        except Exception as e:
            logger.error(f"Error parsing traceparent: {e}")
            logger.error(f"Provided traceparent: {traceparent}")
            return None

    def to_dict(self) -> str:
        return f"00-{self.trace_id}-{self.parent_id}-{'01' if self.sampled else '00'}"

    @property
    def correlation_id(self) -> str:
        return self.trace_id

    @property
    def causation_id(self) -> str:
        return self.parent_id


class MessageHeaders(BaseValueObject):
    """Structured headers for message metadata"""

    #######################
    # Core identification #
    #######################
    # FIXME Fix the format documentation for `id`
    # Event Format is <domain-name>.<class-name>.<version>.<aggregate-id>.<aggregate-version>
    # Command Format is <domain-name>.<class-name>.<version>
    id = String()

    # Time of event generation
    time = DateTime()

    # Type of the event
    # Format is <domain-name>.<event-class-name>.<event-version>
    type = String()

    # Name of the stream to which the event/command is written
    stream = String()

    ###########
    # Tracing #
    ###########
    # OpenTelemetry compatible, W3C-spec compliant
    #   Holds trace context information
    #   Serves as a container for Correlation and Causation IDs as well
    traceparent = ValueObject(TraceParent)

    @classmethod
    def build(cls, **kwargs) -> MessageHeaders:
        headers = kwargs.copy()
        if "traceparent" in headers:
            headers["traceparent"] = TraceParent.build(headers["traceparent"])
        return cls(**headers)


class DomainMeta(BaseValueObject):
    # Fully Qualified Name of the event/command
    fqn = String(sanitize=False)

    # Kind of the object
    # Can be one of "EVENT", "COMMAND"
    kind = String()

    # Name of the stream that originated this event/command
    origin_stream = String()

    # Version of the event
    # Can be overridden with `__version__` class attr in event/command class definition
    version = String(default="v1")

    # Applies to Events only
    # Sequence of the event in the aggregate
    # This is the version of the aggregate as it will be *after* persistence.
    #
    # For Event Sourced aggregates, sequence_id is the same as version (like "1").
    # For Regular aggregates, sequence_id is `version`.`eventnumber` (like "0.1"). This is to
    #   ensure that the ordering is possible even when multiple events are raised as past of
    #   single update.
    sequence_id = String()

    # Sync or Async?
    asynchronous = Boolean(default=True)

    # Version that the stream is expected to be when the message is written
    expected_version = Integer()


class EventStoreMeta(BaseValueObject):
    # Primary key. The ordinal position of the message in the entire message store.
    # Global position may have gaps.
    global_position = Integer()

    # The ordinal position of the message in its stream.
    # Position is gapless.
    position = Integer()


class Metadata(BaseValueObject):
    headers = ValueObject(MessageHeaders)
    envelope = ValueObject(MessageEnvelope)
    domain = ValueObject(DomainMeta)
    event_store = ValueObject(EventStoreMeta)


class BaseMessageType(BaseContainer, OptionsMixin):  # FIXME Remove OptionsMixin
    """Base class inherited by Event and Command element classes.

    Core functionality associated with message type structures, like timestamping, are specified
    as part of this base class.
    """

    # Track Metadata
    _metadata = ValueObject(Metadata, default=lambda: Metadata())  # pragma: no cover

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        if not subclass.meta_.abstract:
            subclass.__track_id_field()

        # Use explicit version if specified, else default to "v1"
        if not hasattr(subclass, "__version__"):
            setattr(subclass, "__version__", "v1")

        subclass.__validate_for_basic_field_types()

    @classmethod
    def __validate_for_basic_field_types(subclass):
        for field_name, field_obj in fields(subclass).items():
            # Value objects can hold all kinds of fields, except associations
            if isinstance(field_obj, (Reference, Association)):
                raise IncorrectUsageError(
                    f"Events/Commands cannot have associations. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {subclass.__name__}"
                )

    def __setattr__(self, name, value):
        if not hasattr(self, "_initialized") or not self._initialized:
            return super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                "Event/Command Objects are immutable and cannot be modified once created"
            )

    @classmethod
    def _default_options(cls):
        return [
            ("abstract", False),
            ("aggregate_cluster", None),
            ("part_of", None),
        ]

    @classmethod
    def __track_id_field(subclass):
        """Check if an identifier field has been associated with the event/command.

        When an identifier is provided, its value is used to construct
        unique stream name."""
        try:
            id_field = next(
                field
                for _, field in declared_fields(subclass).items()
                if isinstance(field, (Field)) and field.identifier
            )

            setattr(subclass, _ID_FIELD_NAME, id_field.field_name)

        except StopIteration:
            # No Identity fields declared
            pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, finalize=False, **kwargs)

        if not hasattr(self.__class__, "__type__"):
            raise ConfigurationError(
                f"`{self.__class__.__name__}` should be registered with a domain"
            )

    @property
    def payload(self):
        """Return the payload of the event."""
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in fields(self).items()
            if field_name not in {"_metadata"}
        }

    def __eq__(self, other) -> bool:
        """Equivalence check based only on identifier."""
        if type(other) is not type(self):
            return False

        return (self._metadata.headers.id if self._metadata.headers else None) == (
            other._metadata.headers.id if other._metadata.headers else None
        )

    def __hash__(self) -> int:
        """Hash based on data."""
        return hash(json.dumps(self.payload, sort_keys=True))

    def to_dict(self):
        """Return data as a dictionary.

        We need to override this method in Event, because `to_dict()` of `BaseContainer`
        eliminates `_metadata`.
        """
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in fields(self).items()
        }


class Message(BaseContainer, OptionsMixin):  # FIXME Remove OptionsMixin
    """Generic message class
    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    - Message format versioning for schema evolution
    """

    # JSON representation of the message body
    data = Dict()

    # JSON representation of the message metadata
    metadata = ValueObject(Metadata)

    @classmethod
    def deserialize(cls, message: dict, validate: bool = True) -> Message:
        """Deserialize a message from its dictionary representation."""
        try:
            # Handle headers and envelope within metadata
            metadata_dict = message["metadata"]

            # Handle envelope within metadata (backward compatibility)
            if "envelope" not in metadata_dict:
                envelope_data = message.get("envelope", {})
                metadata_dict["envelope"] = MessageEnvelope(
                    specversion=envelope_data.get("specversion", "1.0"),
                    checksum=envelope_data.get("checksum", ""),
                )

            # If headers are not in metadata but at top level (backward compatibility)
            if "headers" not in metadata_dict:
                headers_data = message.get("headers", {})
                # Extract id, time, type from headers or fallback to top level for backward compatibility
                headers_kwargs = {
                    "id": headers_data.get("id", message.get("id", None)),
                    "time": headers_data.get("time", message.get("time", None)),
                    "type": headers_data.get("type", message.get("type", None)),
                }

                # If headers_data contains a traceparent string, use build()
                # If headers_data is a dict with traceparent dict/None, create directly
                traceparent_data = headers_data.get("traceparent")
                traceparent = (
                    TraceParent(**traceparent_data) if traceparent_data else None
                )
                headers_kwargs["traceparent"] = traceparent

                metadata_dict["headers"] = MessageHeaders(**headers_kwargs)

            # FIXME We can do this properly if we shift this method into event store port.
            #    `position` and `global_position` are present in event store message structure alone.
            # Add EventStoreMeta if position and global_position are present
            if "position" in message or "global_position" in message:
                metadata_dict["event_store"] = EventStoreMeta(
                    position=message.get("position"),
                    global_position=message.get("global_position"),
                )

            # Create the message object
            msg = Message(
                data=message["data"],
                metadata=metadata_dict,
            )

            # Validate integrity if requested and checksum is present
            if validate and msg.metadata.envelope and msg.metadata.envelope.checksum:
                if not msg.verify_integrity():
                    # Get message ID from metadata.headers or fallback to top-level
                    message_id = (
                        msg.metadata.headers.id
                        if msg.metadata.headers and msg.metadata.headers.id
                        else message.get("id", "unknown")
                    )
                    message_type = (
                        msg.metadata.headers.type
                        if msg.metadata.headers and msg.metadata.headers.type
                        else message.get("type", "unknown")
                    )

                    raise DeserializationError(
                        message_id=str(message_id),
                        error="Message integrity validation failed - checksum mismatch",
                        context={
                            "stored_checksum": msg.metadata.envelope.checksum,
                            "computed_checksum": MessageEnvelope.compute_checksum(
                                msg.data
                            ),
                            "validation_requested": True,
                            "message_type": message_type,
                            "stream_name": metadata_dict.get("headers", {}).get(
                                "stream", "unknown"
                            ),
                        },
                    )

            return msg
        except KeyError as e:
            # Convert KeyError to DeserializationError with better context
            # Try to get message ID and type from headers first, then fallback to top-level
            headers_data = message.get("headers", {})
            message_id = headers_data.get("id") or message.get("id", "unknown")
            message_type = headers_data.get("type") or message.get("type", "unknown")
            missing_field = str(e).strip("'\"")

            # Build context about available fields
            context = {
                "missing_field": missing_field,
                "available_fields": list(message.keys())
                if isinstance(message, dict)
                else "not_available",
                "message_type": message_type,
                "stream_name": message.get("metadata", {})
                .get("headers", {})
                .get("stream", "unknown"),
                "original_exception_type": "KeyError",
            }

            raise DeserializationError(
                message_id=str(message_id),
                error=f"Missing required field '{missing_field}' in message data",
                context=context,
            ) from e

    def verify_integrity(self) -> bool:
        """Verify message integrity using checksum validation.

        Computes the current checksum and compares it with the stored checksum
        to verify message integrity.

        Returns:
            bool: True if message integrity is valid, False otherwise
        """
        if (
            not hasattr(self, "metadata")
            or not self.metadata.envelope
            or not self.metadata.envelope.checksum
        ):
            return False  # No checksum available for validation

        current_checksum = MessageEnvelope.compute_checksum(self.data)
        return current_checksum == self.metadata.envelope.checksum

    def to_domain_object(self) -> Union[BaseEvent, BaseCommand]:
        """Convert this message back to its original domain object."""
        try:
            if self.metadata.domain.kind not in [
                MessageType.COMMAND.value,
                MessageType.EVENT.value,
            ]:
                # We are dealing with a malformed or unknown message
                raise InvalidDataError(
                    {"kind": ["Message type is not supported for deserialization"]}
                )

            element_cls = current_domain._events_and_commands.get(
                self.metadata.headers.type, None
            )

            if element_cls is None:
                raise ConfigurationError(
                    f"Message type {self.metadata.headers.type} is not registered with the domain."
                )

            return element_cls(_metadata=self.metadata, **self.data)

        except Exception as e:
            # Enhanced error context for debugging
            envelope = (
                getattr(self.metadata, "envelope", None)
                if hasattr(self, "metadata")
                else None
            )
            envelope_data = envelope.to_dict() if envelope else None

            # Get type and ID from metadata.headers if available
            message_type = (
                self.metadata.headers.type if self.metadata.headers else "unknown"
            )
            message_id = (
                self.metadata.headers.id
                if self.metadata.headers and self.metadata.headers.id
                else "unknown"
            )

            context = {
                "type": message_type,
                "stream_name": self.metadata.headers.stream
                if self.metadata.headers and self.metadata.headers.stream
                else "unknown",
                "metadata_kind": getattr(self.metadata.domain, "kind", "unknown")
                if hasattr(self, "metadata") and self.metadata.domain
                else "unknown",
                "metadata_type": getattr(self.metadata.headers, "type", "unknown")
                if hasattr(self, "metadata") and self.metadata.headers
                else "unknown",
                "position": self.metadata.event_store.position
                if self.metadata.event_store
                else "unknown",
                "global_position": self.metadata.event_store.global_position
                if self.metadata.event_store
                else "unknown",
                "original_exception_type": type(e).__name__,
                "has_metadata": hasattr(self, "metadata"),
                "has_data": hasattr(self, "data"),
                "data_keys": list(self.data.keys())
                if hasattr(self, "data") and isinstance(self.data, dict)
                else "not_available",
                "envelope": envelope_data,
            }

            # Handle case where ID is None
            if message_id is None:
                message_id = "unknown"

            raise DeserializationError(
                message_id=str(message_id), error=str(e), context=context
            ) from e

    @classmethod
    def from_domain_object(
        cls, message_object: Union[BaseEvent, BaseCommand]
    ) -> Message:
        """Create a message from a domain event or command."""
        if not message_object.meta_.part_of:
            raise ConfigurationError(
                f"`{message_object.__class__.__name__}` is not associated with an aggregate."
            )

        # Set the expected version of the stream
        #   Applies only to events
        expected_version = None
        if (
            message_object._metadata.domain
            and message_object._metadata.domain.kind == MessageType.EVENT.value
        ):
            # If this is a Fact Event, don't set an expected version.
            # Otherwise, expect the previous version
            if not message_object.__class__.__name__.endswith("FactEvent"):
                expected_version = message_object._expected_version

        # Ensure metadata has headers set correctly
        # The message_object._metadata should already have headers from event/command creation
        # If not, create minimal headers
        if not message_object._metadata.headers:
            headers = MessageHeaders(
                type=message_object.__class__.__type__,
                time=None,  # Don't set time for converted messages
            )
            # Clone metadata with headers
            metadata_dict = message_object._metadata.to_dict()
            metadata_dict["headers"] = headers
            metadata = Metadata(**metadata_dict)
        else:
            metadata = message_object._metadata

        # Automatically compute and set envelope with checksum for integrity validation
        envelope = MessageEnvelope.build(message_object.payload)

        # Clone metadata with envelope and expected_version
        metadata_dict = metadata.to_dict()
        metadata_dict["envelope"] = envelope

        # Set expected_version in domain if it exists
        if expected_version is not None and metadata_dict.get("domain"):
            metadata_dict["domain"]["expected_version"] = expected_version

        metadata_with_envelope = Metadata(**metadata_dict)

        # Create the message
        message = cls(
            data=message_object.payload,
            metadata=metadata_with_envelope,
        )

        return message
