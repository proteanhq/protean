from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Union, Optional

from pydantic import BaseModel, ConfigDict, Field as PydanticField, PrivateAttr

from protean.core.value_object import BaseValueObject
from protean.fields.resolved import ResolvedField
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    InvalidDataError,
    DeserializationError,
)
from protean.fields.association import Association, Reference
from protean.fields.base import FieldBase
from protean.fields.embedded import ValueObject as ValueObjectField
from protean.fields.spec import FieldSpec
from protean.utils.container import OptionsMixin
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME
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

    specversion: str = "1.0"
    checksum: str | None = None

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

    trace_id: str
    parent_id: str
    sampled: bool = False

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

    def to_w3c(self) -> str:
        """Return the W3C traceparent header string format."""
        return f"00-{self.trace_id}-{self.parent_id}-{'01' if self.sampled else '00'}"

    @property
    def correlation_id(self) -> str:
        return self.trace_id

    @property
    def causation_id(self) -> str:
        return self.parent_id


class MessageHeaders(BaseValueObject):
    """Structured headers for message metadata"""

    # Event Format: <domain-name>.<class-name>.<version>.<aggregate-id>.<aggregate-version>
    # Command Format: <domain-name>.<class-name>.<version>
    id: str | None = None

    # Time of event generation
    time: datetime | None = None

    # Type of the event
    # Format: <domain-name>.<event-class-name>.<event-version>
    type: str | None = None

    # Name of the stream to which the event/command is written
    stream: str | None = None

    # OpenTelemetry compatible, W3C-spec compliant trace context
    traceparent: TraceParent | None = None

    # Caller-provided key for command deduplication
    idempotency_key: str | None = None

    @classmethod
    def build(cls, **kwargs) -> MessageHeaders:
        headers = kwargs.copy()
        if "traceparent" in headers and isinstance(headers["traceparent"], str):
            headers["traceparent"] = TraceParent.build(headers["traceparent"])
        return cls(**headers)


class DomainMeta(BaseValueObject):
    # Fully Qualified Name of the event/command
    fqn: str | None = None

    # Kind of the object — "EVENT" or "COMMAND"
    kind: str | None = None

    # Name of the stream that originated this event/command
    origin_stream: str | None = None

    # Stream category
    stream_category: str | None = None

    # Version of the event (overridable via __version__ class attr)
    version: str = "v1"

    # Sequence of the event in the aggregate (version after persistence)
    sequence_id: str | None = None

    # Sync or Async?
    asynchronous: bool = True

    # Version that the stream is expected to be when the message is written
    expected_version: int | None = None


class EventStoreMeta(BaseValueObject):
    # The ordinal position of the message in the entire message store (may have gaps)
    global_position: int | None = None

    # The ordinal position of the message in its stream (gapless)
    position: int | None = None


class Metadata(BaseValueObject):
    headers: MessageHeaders
    envelope: MessageEnvelope | None = PydanticField(default_factory=MessageEnvelope)
    domain: DomainMeta | None = None
    event_store: EventStoreMeta | None = None


# ---------------------------------------------------------------------------
# BaseMessageType
# ---------------------------------------------------------------------------
class BaseMessageType(BaseModel, OptionsMixin):
    """Base class for Command and Event element classes.

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints.
    """

    element_type: ClassVar[str] = ""

    model_config = ConfigDict(
        extra="forbid",
        ignored_types=(
            FieldSpec,
            FieldBase,
            str,
            int,
            float,
            bool,
            list,
            dict,
            tuple,
            set,
            type,
        ),
    )

    _metadata: Any = PrivateAttr(default=None)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("abstract", False),
            ("aggregate_cluster", None),
            ("part_of", None),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Use explicit version if specified, else default to "v1"
        if not hasattr(cls, "__version__"):
            setattr(cls, "__version__", "v1")

        # Initialize invariant storage
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

        # Resolve FieldSpec declarations before Pydantic processes annotations
        cls._resolve_fieldspecs()

        # Validate that only basic field types are used (no associations/references)
        cls.__validate_for_basic_field_types()

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from protean.fields.spec import resolve_fieldspecs

        resolve_fieldspecs(cls)

    @classmethod
    def __validate_for_basic_field_types(cls) -> None:
        """Reject association/reference field descriptors in Commands and Events."""
        for field_name, field_obj in vars(cls).items():
            if isinstance(field_obj, (Association, Reference, ValueObjectField)):
                raise IncorrectUsageError(
                    f"Commands and Events can only contain basic field types. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {cls.__name__}"
                )

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, ResolvedField] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = ResolvedField(fname, finfo, finfo.annotation)
        setattr(cls, _FIELDS, fields_dict)

        # Track id field
        if not cls.meta_.abstract:
            cls.__track_id_field()

    def __setattr__(self, name: str, value: Any) -> None:
        if not getattr(self, "_initialized", False):
            super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                "Event/Command Objects are immutable and cannot be modified once created"
            )

    @classmethod
    def __track_id_field(cls) -> None:
        """Check if an identifier field has been associated with the event/command.

        When an identifier is provided, its value is used to construct
        unique stream name."""
        try:
            id_field = next(
                field
                for _, field in getattr(cls, _FIELDS, {}).items()
                if getattr(field, "identifier", False)
            )
            setattr(cls, _ID_FIELD_NAME, id_field.field_name)
        except StopIteration:
            pass

    @property
    def payload(self) -> dict[str, Any]:
        """Return the payload of the event/command."""
        return {
            fname: shim.as_dict(getattr(self, fname, None))
            for fname, shim in getattr(self, _FIELDS, {}).items()
        }

    def __eq__(self, other: object) -> bool:
        """Equivalence check based only on identifier."""
        if type(other) is not type(self):
            return False
        self_id = (
            self._metadata.headers.id
            if self._metadata and self._metadata.headers
            else None
        )
        other_id = (
            other._metadata.headers.id
            if other._metadata and other._metadata.headers
            else None
        )
        return self_id == other_id

    def __hash__(self) -> int:
        """Hash based on data."""
        return hash(json.dumps(self.payload, sort_keys=True))

    def to_dict(self) -> dict[str, Any]:
        """Return data as a dictionary, including metadata."""
        result = self.payload.copy()
        if self._metadata:
            result["_metadata"] = self._metadata.to_dict()
        return result


class Message(BaseModel, OptionsMixin):
    """Generic message class
    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    - Message format versioning for schema evolution
    """

    model_config = ConfigDict(extra="forbid")

    # JSON representation of the message body
    data: dict = {}

    # JSON representation of the message metadata
    metadata: Metadata | None = None

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return []

    def to_dict(self) -> dict:
        """Return data as a dictionary."""
        result: dict[str, Any] = {"data": self.data}
        result["metadata"] = self.metadata.to_dict() if self.metadata else None
        return result

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return hash(json.dumps(self.to_dict(), sort_keys=True))

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}".format(self.to_dict()),
        )

    def __bool__(self) -> bool:
        return bool(self.data) or bool(self.metadata)

    @classmethod
    def _build_envelope(cls, metadata_dict: dict, message: dict) -> None:
        """Build envelope within metadata if not present."""
        if "envelope" not in metadata_dict:
            envelope_data = message.get("envelope", {})
            specversion = envelope_data.get("specversion") or "1.0"
            metadata_dict["envelope"] = MessageEnvelope(
                specversion=specversion,
                checksum=envelope_data.get("checksum"),
            )

    @classmethod
    def _build_headers(cls, metadata_dict: dict, message: dict) -> None:
        """Build headers within metadata if not present."""
        if "headers" not in metadata_dict:
            headers_data = message.get("headers", {})
            headers_kwargs = {
                "id": headers_data.get("id", message.get("id", None)),
                "time": headers_data.get("time", message.get("time", None)),
                "type": headers_data.get("type", message.get("type", None)),
                "stream": headers_data.get("stream", message.get("stream", None)),
                "idempotency_key": headers_data.get("idempotency_key", None),
            }

            traceparent_data = headers_data.get("traceparent")
            if traceparent_data:
                headers_kwargs["traceparent"] = TraceParent(**traceparent_data)

            metadata_dict["headers"] = MessageHeaders(**headers_kwargs)

    @classmethod
    def _build_event_store_meta(cls, metadata_dict: dict, message: dict) -> None:
        """Add EventStoreMeta if position and global_position are present."""
        if "position" in message or "global_position" in message:
            metadata_dict["event_store"] = EventStoreMeta(
                position=message.get("position"),
                global_position=message.get("global_position"),
            )

    @classmethod
    def _validate_and_raise(cls, msg: Message, message: dict) -> None:
        """Validate message integrity and raise error if validation fails."""
        if not msg.verify_integrity():
            message_id = cls._extract_message_id(msg, message)
            message_type = cls._extract_message_type(msg, message)

            raise DeserializationError(
                message_id=str(message_id),
                error="Message integrity validation failed - checksum mismatch",
                context={
                    "stored_checksum": msg.metadata.envelope.checksum,
                    "computed_checksum": MessageEnvelope.compute_checksum(msg.data),
                    "validation_requested": True,
                    "message_type": message_type,
                    "stream_name": cls._extract_stream_name(msg.metadata.to_dict()),
                },
            )

    @classmethod
    def _extract_message_id(cls, msg: Message, message: dict) -> str:
        """Extract message ID from message or return 'unknown'."""
        if msg.metadata.headers and msg.metadata.headers.id:
            return msg.metadata.headers.id
        return message.get("id", "unknown")

    @classmethod
    def _extract_message_type(cls, msg: Message, message: dict) -> str:
        """Extract message type from message or return 'unknown'."""
        if msg.metadata.headers and msg.metadata.headers.type:
            return msg.metadata.headers.type
        return message.get("type", "unknown")

    @classmethod
    def _extract_stream_name(cls, metadata_dict: dict) -> str:
        """Extract stream name from metadata or return 'unknown'."""
        return metadata_dict.get("headers", {}).get("stream", "unknown")

    @classmethod
    def _handle_key_error(cls, e: KeyError, message: dict) -> None:
        """Handle KeyError by converting to DeserializationError with context."""
        headers_data = message.get("headers", {})
        message_id = headers_data.get("id") or message.get("id", "unknown")
        message_type = headers_data.get("type") or message.get("type", "unknown")
        missing_field = str(e).strip("'\"")

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

    @classmethod
    def deserialize(cls, message: dict, validate: bool = True) -> Message:
        """Deserialize a message from its dictionary representation."""
        try:
            metadata_dict = message["metadata"]

            # Build metadata components
            cls._build_envelope(metadata_dict, message)
            cls._build_headers(metadata_dict, message)
            cls._build_event_store_meta(metadata_dict, message)

            # Create the message object
            msg = Message(
                data=message["data"],
                metadata=metadata_dict,
            )

            # Validate integrity if requested
            if validate and msg.metadata.envelope and msg.metadata.envelope.checksum:
                cls._validate_and_raise(msg, message)

            return msg

        except KeyError as e:
            cls._handle_key_error(e, message)

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

    def _validate_message_kind(self) -> None:
        """Validate that the message kind is supported for deserialization."""
        if self.metadata.domain.kind not in [
            MessageType.COMMAND.value,
            MessageType.EVENT.value,
        ]:
            raise InvalidDataError(
                {"kind": ["Message type is not supported for deserialization"]}
            )

    def _get_element_class(self) -> type:
        """Get the element class for the message type."""
        element_cls = current_domain._events_and_commands.get(
            self.metadata.headers.type, None
        )

        if element_cls is None:
            raise ConfigurationError(
                f"Message type {self.metadata.headers.type} is not registered with the domain."
            )

        return element_cls

    def _build_error_context(self, exception: Exception) -> dict:
        """Build detailed error context for debugging."""
        envelope = (
            getattr(self.metadata, "envelope", None)
            if hasattr(self, "metadata")
            else None
        )
        envelope_data = envelope.to_dict() if envelope else None

        message_type = (
            self.metadata.headers.type if self.metadata.headers else "unknown"
        )

        context = {
            "type": message_type,
            "stream_name": self._safe_get_attr(
                self.metadata, "headers.stream", "unknown"
            ),
            "metadata_kind": self._safe_get_attr(
                self.metadata, "domain.kind", "unknown"
            ),
            "metadata_type": self._safe_get_attr(
                self.metadata, "headers.type", "unknown"
            ),
            "position": self._safe_get_attr(
                self.metadata, "event_store.position", "unknown"
            ),
            "global_position": self._safe_get_attr(
                self.metadata, "event_store.global_position", "unknown"
            ),
            "original_exception_type": type(exception).__name__,
            "has_metadata": hasattr(self, "metadata"),
            "has_data": hasattr(self, "data"),
            "data_keys": list(self.data.keys())
            if hasattr(self, "data") and isinstance(self.data, dict)
            else "not_available",
            "envelope": envelope_data,
        }

        return context

    def _safe_get_attr(self, obj, attr_path: str, default: str = "unknown") -> str:
        """Safely get nested attribute from object."""
        try:
            attrs = attr_path.split(".")
            result = obj
            for attr in attrs:
                result = getattr(result, attr, None)
                if result is None:
                    return default
            return result if result is not None else default
        except (AttributeError, TypeError):
            return default

    def to_domain_object(self) -> Union[BaseEvent, BaseCommand]:
        """Convert this message back to its original domain object."""
        try:
            self._validate_message_kind()
            element_cls = self._get_element_class()
            return element_cls(_metadata=self.metadata, **self.data)

        except Exception as e:
            context = self._build_error_context(e)

            if self.metadata.headers and self.metadata.headers.id:
                message_id = self.metadata.headers.id
            else:
                message_id = context.get("type", "unknown")

            # Ensure message_id is never None
            message_id = str(message_id) if message_id else "unknown"

            raise DeserializationError(
                message_id=message_id, error=str(e), context=context
            ) from e

    @classmethod
    def _validate_aggregate_association(
        cls, message_object: Union[BaseEvent, BaseCommand]
    ) -> None:
        """Validate that the message object is associated with an aggregate."""
        if not message_object.meta_.part_of:
            raise ConfigurationError(
                f"`{message_object.__class__.__name__}` is not associated with an aggregate."
            )

    @classmethod
    def _determine_expected_version(
        cls, message_object: Union[BaseEvent, BaseCommand]
    ) -> Optional[int]:
        """Determine the expected version for the message.

        Returns expected version for non-fact events, None otherwise.
        """
        if (
            message_object._metadata.domain
            and message_object._metadata.domain.kind == MessageType.EVENT.value
            and not message_object.__class__.__name__.endswith("FactEvent")
        ):
            return message_object._expected_version
        return None

    @classmethod
    def _ensure_headers(cls, message_object: Union[BaseEvent, BaseCommand]) -> Metadata:
        """Ensure metadata has headers set correctly."""
        if not message_object._metadata.headers:
            headers = MessageHeaders(
                type=message_object.__class__.__type__,
                time=None,  # Don't set time for converted messages
            )
            metadata_dict = message_object._metadata.to_dict()
            metadata_dict["headers"] = headers
            return Metadata(**metadata_dict)
        return message_object._metadata

    @classmethod
    def _build_final_metadata(
        cls,
        metadata: Metadata,
        envelope: MessageEnvelope,
        expected_version: Optional[int],
    ) -> Metadata:
        """Build final metadata with envelope and expected version."""
        metadata_dict = metadata.to_dict()
        metadata_dict["envelope"] = envelope

        if expected_version is not None and metadata_dict.get("domain"):
            metadata_dict["domain"]["expected_version"] = expected_version

        return Metadata(**metadata_dict)

    @classmethod
    def from_domain_object(
        cls, message_object: Union[BaseEvent, BaseCommand]
    ) -> Message:
        """Create a message from a domain event or command."""
        cls._validate_aggregate_association(message_object)

        expected_version = cls._determine_expected_version(message_object)
        metadata = cls._ensure_headers(message_object)
        envelope = MessageEnvelope.build(message_object.payload)

        metadata_with_envelope = cls._build_final_metadata(
            metadata, envelope, expected_version
        )

        return cls(
            data=message_object.payload,
            metadata=metadata_with_envelope,
        )
