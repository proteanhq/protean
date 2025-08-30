from __future__ import annotations

import hashlib
import json
import logging
from enum import Enum
from typing import Dict, Union

from protean import fields
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import (
    ConfigurationError,
    InvalidDataError,
    DeserializationError,
)
from protean.core.value_object import BaseValueObject
from protean.utils.container import BaseContainer, OptionsMixin
from protean.utils.eventing import Metadata
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)


class MessageType(Enum):
    EVENT = "EVENT"
    COMMAND = "COMMAND"
    READ_POSITION = "READ_POSITION"


class MessageRecord(BaseContainer):
    """
    Base Container holding all fields of a message.
    """

    # Primary key. The ordinal position of the message in the entire message store.
    # Global position may have gaps.
    global_position = fields.Auto(increment=True, identifier=True)

    # The ordinal position of the message in its stream.
    # Position is gapless.
    position = fields.Integer()

    # Message creation time
    time = fields.DateTime()

    # Unique ID of the message
    id = fields.Auto()

    # Name of stream to which the message is written
    stream_name = fields.String(max_length=255)

    # The type of the message
    type = fields.String()

    # JSON representation of the message body
    data = fields.Dict()

    # JSON representation of the message metadata
    metadata = fields.ValueObject(Metadata)


class MessageEnvelope(BaseValueObject):
    """Message envelope containing integrity and versioning information."""

    specversion = fields.String(default="1.0")
    checksum = fields.String()

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

    trace_id = fields.String(max_length=32, min_length=32)
    parent_id = fields.String(max_length=16, min_length=16)
    sampled = fields.Boolean(default=False)

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

    # Tracing (OpenTelemetry compatible, W3C-spec compliant)
    #   Holds trace context information
    #   Serves as a container for Correlation and Causation IDs as well
    traceparent = fields.ValueObject(TraceParent, required=False)

    @classmethod
    def build(cls, traceparent: str) -> MessageHeaders:
        headers = {}
        if traceparent:
            headers["traceparent"] = TraceParent.build(traceparent)
        return cls(**headers)


class Message(MessageRecord, OptionsMixin):  # FIXME Remove OptionsMixin
    """Generic message class
    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    - Message format versioning for schema evolution
    """

    envelope = fields.ValueObject(MessageEnvelope)
    headers = fields.ValueObject(MessageHeaders)

    # Version that the stream is expected to be when the message is written
    expected_version = fields.Integer()

    @classmethod
    def from_dict(cls, message: Dict, validate: bool = True) -> Message:
        try:
            envelope = (
                MessageEnvelope(**message.get("envelope"))
                if message.get("envelope", None)
                else MessageEnvelope()
            )

            headers_data = message.get("headers")
            if headers_data is not None:
                # If headers_data contains a traceparent string, use build()
                # If headers_data is a dict with traceparent dict/None, create directly
                traceparent_data = headers_data.get("traceparent")
                if isinstance(traceparent_data, str):
                    headers = MessageHeaders.build(traceparent_data)
                elif isinstance(traceparent_data, dict):
                    # Create TraceParent from dict and MessageHeaders
                    traceparent = (
                        TraceParent(**traceparent_data) if traceparent_data else None
                    )
                    headers = MessageHeaders(traceparent=traceparent)
                else:
                    # traceparent is None or other
                    headers = MessageHeaders(traceparent=None)
            else:
                headers = None

            # Create the message object
            msg = Message(
                stream_name=message["stream_name"],
                type=message["type"],
                data=message["data"],
                metadata=message["metadata"],
                position=message["position"],
                global_position=message["global_position"],
                time=message["time"],
                id=message["id"],
                envelope=envelope,
                headers=headers,
            )

            # Validate integrity if requested and checksum is present
            if validate and msg.envelope.checksum:
                if not msg.validate_checksum():
                    raise DeserializationError(
                        message_id=str(message.get("id", "unknown")),
                        error="Message integrity validation failed - checksum mismatch",
                        context={
                            "stored_checksum": msg.envelope.checksum,
                            "computed_checksum": MessageEnvelope.compute_checksum(
                                msg.data
                            ),
                            "validation_requested": True,
                            "message_type": message.get("type", "unknown"),
                            "stream_name": message.get("stream_name", "unknown"),
                        },
                    )

            return msg
        except KeyError as e:
            # Convert KeyError to DeserializationError with better context
            message_id = message.get("id", "unknown")
            missing_field = str(e).strip("'\"")

            # Build context about available fields
            context = {
                "missing_field": missing_field,
                "available_fields": list(message.keys())
                if isinstance(message, dict)
                else "not_available",
                "message_type": message.get("type", "unknown"),
                "stream_name": message.get("stream_name", "unknown"),
                "original_exception_type": "KeyError",
            }

            raise DeserializationError(
                message_id=str(message_id),
                error=f"Missing required field '{missing_field}' in message data",
                context=context,
            ) from e

    def validate_checksum(self) -> bool:
        """Validate message integrity using stored checksum.

        Computes the current checksum and compares it with the stored checksum
        to verify message integrity.

        Returns:
            bool: True if message integrity is valid, False otherwise
        """
        if not hasattr(self, "envelope") or not self.envelope.checksum:
            return False  # No checksum available for validation

        current_checksum = MessageEnvelope.compute_checksum(self.data)
        return current_checksum == self.envelope.checksum

    def to_object(self) -> Union[BaseEvent, BaseCommand]:
        """Reconstruct the event/command object from the message data."""
        try:
            if self.metadata.kind not in [
                MessageType.COMMAND.value,
                MessageType.EVENT.value,
            ]:
                # We are dealing with a malformed or unknown message
                raise InvalidDataError(
                    {"kind": ["Message type is not supported for deserialization"]}
                )

            element_cls = current_domain._events_and_commands.get(
                self.metadata.type, None
            )

            if element_cls is None:
                raise ConfigurationError(
                    f"Message type {self.metadata.type} is not registered with the domain."
                )

            return element_cls(_metadata=self.metadata, **self.data)

        except Exception as e:
            # Enhanced error context for debugging
            envelope = getattr(self, "envelope", None)
            envelope_data = envelope.to_dict() if envelope else None

            context = {
                "type": getattr(self, "type", "unknown"),
                "stream_name": getattr(self, "stream_name", "unknown"),
                "metadata_kind": getattr(self.metadata, "kind", "unknown")
                if hasattr(self, "metadata")
                else "unknown",
                "metadata_type": getattr(self.metadata, "type", "unknown")
                if hasattr(self, "metadata")
                else "unknown",
                "position": getattr(self, "position", "unknown"),
                "global_position": getattr(self, "global_position", "unknown"),
                "original_exception_type": type(e).__name__,
                "has_metadata": hasattr(self, "metadata"),
                "has_data": hasattr(self, "data"),
                "data_keys": list(self.data.keys())
                if hasattr(self, "data") and isinstance(self.data, dict)
                else "not_available",
                "envelope": envelope_data,
            }

            message_id = getattr(self, "id", "unknown")
            # Handle case where ID is None
            if message_id is None:
                message_id = "unknown"

            raise DeserializationError(
                message_id=str(message_id), error=str(e), context=context
            ) from e

    @classmethod
    def to_message(cls, message_object: Union[BaseEvent, BaseCommand]) -> Message:
        if not message_object.meta_.part_of:
            raise ConfigurationError(
                f"`{message_object.__class__.__name__}` is not associated with an aggregate."
            )

        # Set the expected version of the stream
        #   Applies only to events
        expected_version = None
        if message_object._metadata.kind == MessageType.EVENT.value:
            # If this is a Fact Event, don't set an expected version.
            # Otherwise, expect the previous version
            if not message_object.__class__.__name__.endswith("FactEvent"):
                expected_version = message_object._expected_version

        # Create the message
        message = cls(
            stream_name=message_object._metadata.stream,
            type=message_object.__class__.__type__,
            data=message_object.payload,
            metadata=message_object._metadata,
            expected_version=expected_version,
        )

        # Automatically compute and set checksum for integrity validation
        message.envelope = MessageEnvelope.build(message.data)

        return message
