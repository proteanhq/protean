import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn, Union, Optional
from uuid import uuid4

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
    def build(cls, payload: dict) -> "MessageEnvelope":
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
    def build(cls, traceparent: str) -> "TraceParent | None":
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
    def build(cls, **kwargs) -> "MessageHeaders":
        headers = kwargs.copy()
        if "traceparent" in headers and isinstance(headers["traceparent"], str):
            headers["traceparent"] = TraceParent.build(headers["traceparent"])
        return cls(**headers)


def new_correlation_id() -> str:
    """Generate a new correlation ID (UUID4 hex, no dashes).

    Used as fallback when no external correlation ID is provided
    at the entry point (domain.process()).
    """
    return uuid4().hex


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
    version: int = 1

    # Sequence of the event in the aggregate (version after persistence)
    sequence_id: str | None = None

    # Sync or Async?
    asynchronous: bool = True

    # Version that the stream is expected to be when the message is written
    expected_version: int | None = None

    # Processing priority for event routing through priority lanes.
    # Stored so the Engine can reconstruct the processing_priority() context
    # when handling commands asynchronously.
    priority: int = 0

    # Correlation ID: constant across an entire causal chain.
    # A flexible string — often provided by the external caller
    # (frontend, API gateway). Auto-generated (UUID4 hex) only
    # when no external ID is provided at the entry point.
    correlation_id: str | None = None

    # Causation ID: the message ID (headers.id) of the immediate
    # parent message that caused this one. Always a Protean
    # message ID (e.g. "testdomain::order-abc123-3"). None for
    # root messages (the first command in a chain).
    causation_id: str | None = None


class EventStoreMeta(BaseValueObject):
    # The ordinal position of the message in the entire message store (may have gaps)
    global_position: int | None = None

    # The ordinal position of the message in its stream (gapless)
    position: int | None = None


class Metadata(BaseValueObject):
    """Complete metadata for a domain message (event or command).

    Attributes:
        headers: Transport-level metadata (id, type, stream, time, traceparent).
        envelope: Integrity and versioning (specversion, checksum).
        domain: Domain-level metadata (fqn, kind, correlation/causation IDs, etc.).
        event_store: Store-level metadata (positions), set after persistence.
        extensions: User-provided metadata populated by message enrichment hooks.
            Registered via ``domain.register_event_enricher()`` or
            ``domain.register_command_enricher()``.  Persisted alongside all
            other metadata and survives serialization round-trips.
    """

    headers: MessageHeaders
    envelope: MessageEnvelope | None = PydanticField(default_factory=MessageEnvelope)
    domain: DomainMeta | None = None
    event_store: EventStoreMeta | None = None
    extensions: dict[str, Any] = PydanticField(default_factory=dict)


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
            ("is_fact_event", False),
            ("published", False),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Use explicit version if specified, else default to 1
        if not hasattr(cls, "__version__"):
            cls.__version__ = 1
        elif not isinstance(cls.__version__, int) or cls.__version__ < 1:
            raise IncorrectUsageError(
                f"`{cls.__name__}.__version__` must be a positive integer, "
                f"got `{cls.__version__!r}`"
            )

        # Initialize invariant storage
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

        # Convert ValueObject descriptors to direct type annotations
        # (commands/events don't need shadow fields — VOs serialize as nested dicts)
        cls._convert_vo_descriptors()

        # Resolve FieldSpec declarations before Pydantic processes annotations
        cls._resolve_fieldspecs()

        # Validate that only basic field types are used (no associations/references)
        cls.__validate_for_basic_field_types()

    @classmethod
    def _convert_vo_descriptors(cls) -> None:
        """Convert ValueObject descriptors to direct type annotations.

        Commands/Events don't need shadow fields — VOs serialize as
        nested dicts.  This converts ``email = ValueObject(Email)`` to
        the equivalent of ``email: Email | None = None``.
        """
        own_annots = getattr(cls, "__annotations__", {})
        names_to_remove: list[str] = []
        defaults_to_set: dict[str, None] = {}

        # 1. Assignment style: ``email = ValueObject(Email)``
        for name, value in list(vars(cls).items()):
            if isinstance(value, ValueObjectField):
                vo_cls = value.value_object_cls
                if value.required:
                    own_annots[name] = vo_cls
                else:
                    own_annots[name] = Optional[vo_cls]
                    defaults_to_set[name] = None
                names_to_remove.append(name)

        # 2. Annotation style: ``email: ValueObject(Email)``
        for name, annot_value in list(own_annots.items()):
            if isinstance(annot_value, ValueObjectField):
                vo_cls = annot_value.value_object_cls
                if annot_value.required:
                    own_annots[name] = vo_cls
                else:
                    own_annots[name] = Optional[vo_cls]
                    defaults_to_set[name] = None

        # Remove descriptors from namespace
        for name in names_to_remove:
            try:
                delattr(cls, name)
            except AttributeError:
                pass

        # Set defaults for optional VO fields
        for name, default in defaults_to_set.items():
            setattr(cls, name, default)

        cls.__annotations__ = own_annots

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from protean.fields.spec import resolve_fieldspecs

        resolve_fieldspecs(cls)

    @classmethod
    def __validate_for_basic_field_types(cls) -> None:
        """Reject association/reference field descriptors in Commands and Events."""
        for field_name, field_obj in vars(cls).items():
            if isinstance(field_obj, (Association, Reference)):
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
    def _migrate_legacy_metadata(cls, metadata_dict: dict) -> None:
        """Migrate legacy flat metadata format to nested structure.

        Old Protean versions stored metadata as flat keys (id, fqn, kind,
        type, stream, timestamp, sequence_id, etc.).  Current versions use
        nested sub-objects (headers, domain, envelope).  This method detects
        the old format and reshapes it in-place so that the normal
        _build_* helpers and the Metadata constructor work unchanged.
        """
        # Detect legacy format: has flat keys like 'fqn' but no 'headers'
        if "fqn" not in metadata_dict or "headers" in metadata_dict:
            return

        metadata_dict["headers"] = {
            "id": metadata_dict.pop("id", None),
            "time": metadata_dict.pop("timestamp", None),
            "type": metadata_dict.pop("type", None),
            "stream": metadata_dict.pop("stream", None),
        }

        metadata_dict["domain"] = {
            "fqn": metadata_dict.pop("fqn", None),
            "kind": metadata_dict.pop("kind", None),
            "version": metadata_dict.pop("version", None),
            "sequence_id": metadata_dict.pop("sequence_id", None),
            "asynchronous": metadata_dict.pop("asynchronous", True),
            "origin_stream": metadata_dict.pop("origin_stream", None),
        }

        # Old payload_hash is incompatible with new SHA-256 checksum; discard it
        metadata_dict.pop("payload_hash", None)
        metadata_dict["envelope"] = {
            "specversion": "1.0",
            "checksum": None,
        }

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
    def _validate_and_raise(cls, msg: "Message", message: dict) -> None:
        """Validate message integrity and raise error if validation fails."""
        assert msg.metadata is not None
        assert msg.metadata.envelope is not None
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
    def _extract_message_id(cls, msg: "Message", message: dict) -> str:
        """Extract message ID from message or return 'unknown'."""
        assert msg.metadata is not None
        if msg.metadata.headers and msg.metadata.headers.id:
            return msg.metadata.headers.id
        return message.get("id", "unknown")

    @classmethod
    def _extract_message_type(cls, msg: "Message", message: dict) -> str:
        """Extract message type from message or return 'unknown'."""
        assert msg.metadata is not None
        if msg.metadata.headers and msg.metadata.headers.type:
            return msg.metadata.headers.type
        return message.get("type", "unknown")

    @classmethod
    def _extract_stream_name(cls, metadata_dict: dict) -> str:
        """Extract stream name from metadata or return 'unknown'."""
        return metadata_dict.get("headers", {}).get("stream", "unknown")

    @classmethod
    def _handle_key_error(cls, e: KeyError, message: dict) -> NoReturn:
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
    def deserialize(cls, message: dict, validate: bool = True) -> "Message":
        """Deserialize a message from its dictionary representation."""
        try:
            metadata_dict = message["metadata"]

            # Migrate legacy flat metadata to nested structure
            cls._migrate_legacy_metadata(metadata_dict)

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
            assert msg.metadata is not None
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
            not self.metadata
            or not self.metadata.envelope
            or not self.metadata.envelope.checksum
        ):
            return False  # No checksum available for validation

        current_checksum = MessageEnvelope.compute_checksum(self.data)
        return current_checksum == self.metadata.envelope.checksum

    def _validate_message_kind(self) -> None:
        """Validate that the message kind is supported for deserialization."""
        assert self.metadata is not None
        assert self.metadata.domain is not None
        if self.metadata.domain.kind not in [
            MessageType.COMMAND.value,
            MessageType.EVENT.value,
        ]:
            raise InvalidDataError(
                {"kind": ["Message type is not supported for deserialization"]}
            )

    def _get_element_class(self) -> type:
        """Get the element class for the message type."""
        assert self.metadata is not None
        message_type = self.metadata.headers.type
        element_cls = current_domain._events_and_commands.get(
            message_type,
            None,  # type: ignore[arg-type]
        )

        if element_cls is None:
            raise ConfigurationError(
                f"Message type {message_type} is not registered with the domain."
            )

        return element_cls

    def _build_error_context(self, exception: Exception) -> dict:
        """Build detailed error context for debugging."""
        assert self.metadata is not None
        envelope = getattr(self.metadata, "envelope", None)
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

    def to_domain_object(self) -> Union["BaseEvent", "BaseCommand"]:
        """Convert this message back to its original domain object.

        If the stored type string doesn't match any registered event/command
        (e.g. an old version), the domain's upcaster chain is consulted to
        transform the payload to the current schema before construction.
        """
        assert self.metadata is not None
        try:
            self._validate_message_kind()

            type_string = self.metadata.headers.type
            element_cls = current_domain._events_and_commands.get(
                type_string,
                None,  # type: ignore[arg-type]
            )
            data = self.data

            if element_cls is None:
                # Direct lookup failed — try upcasting from an older version.
                upcaster_chain = current_domain._upcaster_chain
                element_cls = upcaster_chain.resolve_event_class(type_string)

                if element_cls is None:
                    raise ConfigurationError(
                        f"Message type {type_string} is not registered with the domain."
                    )

                # Parse "DomainName.EventName.v1" → base + int version
                base_type, _, version_str = type_string.rpartition(".")
                from_version = int(version_str.lstrip("v"))
                data = upcaster_chain.upcast(base_type, from_version, data)

            return element_cls(_metadata=self.metadata, **data)

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
        cls, message_object: Union["BaseEvent", "BaseCommand"]
    ) -> None:
        """Validate that the message object is associated with an aggregate."""
        if not message_object.meta_.part_of:
            raise ConfigurationError(
                f"`{message_object.__class__.__name__}` is not associated with an aggregate."
            )

    @classmethod
    def _determine_expected_version(
        cls, message_object: Union["BaseEvent", "BaseCommand"]
    ) -> Optional[int]:
        """Determine the expected version for the message.

        Returns expected version for non-fact events, None otherwise.
        """
        if (
            message_object._metadata.domain
            and message_object._metadata.domain.kind == MessageType.EVENT.value
            and not message_object.__class__.meta_.is_fact_event
        ):
            return message_object._expected_version  # type: ignore[union-attr]
        return None

    @classmethod
    def _ensure_headers(
        cls, message_object: Union["BaseEvent", "BaseCommand"]
    ) -> Metadata:
        """Ensure metadata has headers set correctly."""
        if not message_object._metadata.headers:
            headers = MessageHeaders(
                type=message_object.__class__.__type__,  # type: ignore[attr-defined]
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
        cls, message_object: Union["BaseEvent", "BaseCommand"]
    ) -> "Message":
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

    # ── CloudEvents v1.0 serialization ───────────────────────────────

    def _derive_source(self) -> str:
        """Derive the CloudEvents ``source`` URI-reference.

        Fallback chain:
        1. ``current_domain.config["source_uri"]`` if configured.
        2. Domain name extracted from ``metadata.domain.stream_category``
           (format ``<domain>::<aggregate>``) → ``urn:protean:<domain>``.
        3. ``"urn:protean:unknown"`` as a last resort.
        """
        # 1. Configured source_uri
        try:
            source_uri = current_domain.config.get("source_uri")
            if source_uri:
                return source_uri
            # Fall back to domain name
            return f"urn:protean:{current_domain.normalized_name}"
        except Exception:
            pass

        # 2. Extract from stream_category
        if (
            self.metadata
            and self.metadata.domain
            and self.metadata.domain.stream_category
        ):
            parts = self.metadata.domain.stream_category.split("::")
            if parts[0]:
                return f"urn:protean:{parts[0]}"

        # 3. Last resort
        return "urn:protean:unknown"

    def _extract_subject(self) -> str | None:
        """Extract the aggregate identifier from the stream name.

        Stream name formats:
        - Event:      ``<category>-<id>``
        - Fact event:  ``<category>-fact-<id>``
        - Command:     ``<category>:command-<id>``

        Returns ``None`` when stream or stream_category is unavailable.
        """
        if not self.metadata or not self.metadata.headers:
            return None

        stream = self.metadata.headers.stream
        if not stream:
            return None

        category = (
            self.metadata.domain.stream_category if self.metadata.domain else None
        )

        if category:
            # Fact event: <category>-fact-<id>
            fact_prefix = f"{category}-fact-"
            if stream.startswith(fact_prefix):
                return stream[len(fact_prefix) :]

            # Command: <category>:command-<id>
            cmd_prefix = f"{category}:command-"
            if stream.startswith(cmd_prefix):
                return stream[len(cmd_prefix) :]

            # Regular event: <category>-<id>
            evt_prefix = f"{category}-"
            if stream.startswith(evt_prefix):
                return stream[len(evt_prefix) :]

        # Fallback: parse stream name without category.
        # Command format: <anything>:command-<id>
        cmd_marker = ":command-"
        if cmd_marker in stream:
            return stream.split(cmd_marker, 1)[1]

        # Event format: last segment after final "-"
        # Only attempt if stream contains "-"
        if "-" in stream:
            # Handle <category>-fact-<id>
            if "-fact-" in stream:
                return stream.split("-fact-", 1)[1]
            # Handle <category>-<id>  (take everything after first "-")
            _, _, subject = stream.partition("-")
            return subject if subject else None

        return None

    def to_cloudevent(self) -> dict[str, Any]:
        """Serialize this message as a CloudEvents v1.0 JSON object.

        Protean is a compliant CloudEvents producer: every required and
        optional context attribute is derived from existing metadata at
        serialization time — no internal metadata classes are modified.

        **Required attributes** (always present):

        ============= ============================================
        CE Attribute  Derived from
        ============= ============================================
        specversion   Literal ``"1.0"``
        id            ``metadata.headers.id``
        type          ``metadata.headers.type``
        source        ``source_uri`` config, or ``urn:protean:<domain>``
        ============= ============================================

        **Optional attributes** (included when available):

        ================= ============================================
        CE Attribute      Derived from
        ================= ============================================
        time              ``metadata.headers.time`` (RFC 3339)
        subject           Aggregate ID parsed from stream name
        datacontenttype   Literal ``"application/json"``
        ================= ============================================

        **Protean extensions** (``protean``-namespaced):

        ======================= ============================================
        CE Extension            Derived from
        ======================= ============================================
        traceparent             ``metadata.headers.traceparent`` (W3C)
        sequence                ``metadata.domain.sequence_id``
        proteansequencetype     ``"Integer"`` or ``"DotNotation"``
        proteancorrelationid    ``metadata.domain.correlation_id``
        proteancausationid      ``metadata.domain.causation_id``
        proteanchecksum         ``metadata.envelope.checksum``
        proteankind             ``metadata.domain.kind``
        ======================= ============================================

        User-supplied extensions from ``metadata.extensions`` (populated
        via event/command enrichers) are merged into the top level.

        Returns:
            A dict conforming to the CloudEvents v1.0 JSON format.
            Keys with ``None`` values are omitted.

        Example::

            message = Message.from_domain_object(event)
            ce = message.to_cloudevent()
            # {
            #     "specversion": "1.0",
            #     "id": "myapp::order-abc123-1",
            #     "type": "MyApp.OrderPlaced.v1",
            #     "source": "https://orders.example.com",
            #     "time": "2026-03-02T10:30:00+00:00",
            #     "subject": "abc123",
            #     "datacontenttype": "application/json",
            #     "proteankind": "EVENT",
            #     "data": {"order_id": "abc123", ...},
            # }

        .. seealso::
            `CloudEvents v1.0.2 Specification
            <https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md>`_
        """
        assert self.metadata is not None, "Message must have metadata"

        headers = self.metadata.headers
        domain = self.metadata.domain
        envelope = self.metadata.envelope

        # Required attributes
        ce: dict[str, Any] = {
            "specversion": "1.0",
            "id": headers.id if headers else None,
            "type": headers.type if headers else None,
            "source": self._derive_source(),
        }

        # Optional context attributes
        if headers and headers.time:
            ce["time"] = headers.time.isoformat()
        subject = self._extract_subject()
        if subject:
            ce["subject"] = subject
        ce["datacontenttype"] = "application/json"

        # Data
        ce["data"] = self.data

        # ── Extensions ──

        # W3C Trace Context
        if headers and headers.traceparent:
            ce["traceparent"] = headers.traceparent.to_w3c()

        # Protean-namespaced extensions
        if domain:
            if domain.sequence_id is not None:
                ce["sequence"] = domain.sequence_id
                ce["proteansequencetype"] = (
                    "DotNotation" if "." in domain.sequence_id else "Integer"
                )
            if domain.correlation_id is not None:
                ce["proteancorrelationid"] = domain.correlation_id
            if domain.causation_id is not None:
                ce["proteancausationid"] = domain.causation_id
            if domain.kind is not None:
                ce["proteankind"] = domain.kind

        if envelope and envelope.checksum:
            ce["proteanchecksum"] = envelope.checksum

        # User extensions from enrichers
        if self.metadata.extensions:
            ce.update(self.metadata.extensions)

        # Strip None values
        return {k: v for k, v in ce.items() if v is not None}

    @classmethod
    def from_cloudevent(cls, cloudevent: dict[str, Any]) -> "Message":
        """Construct a Protean ``Message`` from a CloudEvents v1.0 JSON object.

        Protean is a compliant CloudEvents consumer: this method accepts
        any valid CloudEvents v1.0 structured-mode JSON object and maps
        its attributes into Protean's internal metadata structure.

        **Required CE attributes** → Protean mapping:

        ============= ============================================
        CE Attribute  Protean Destination
        ============= ============================================
        specversion   ``envelope.specversion`` (must be ``"1.0"``)
        id            ``headers.id``
        type          ``headers.type``
        source        ``extensions["ce_source"]``
        ============= ============================================

        **Optional CE attributes** → Protean mapping:

        ================= ============================================
        CE Attribute      Protean Destination
        ================= ============================================
        time              ``headers.time``
        subject           ``extensions["ce_subject"]``
        datacontenttype   ``extensions["ce_datacontenttype"]`` (if not JSON)
        dataschema        ``extensions["ce_dataschema"]``
        ================= ============================================

        **Protean extensions** (round-trip preservation):

        ======================= ============================================
        CE Extension            Protean Destination
        ======================= ============================================
        traceparent             ``headers.traceparent``
        proteancorrelationid    ``domain.correlation_id``
        proteancausationid      ``domain.causation_id``
        proteanchecksum         ``envelope.checksum``
        proteankind             ``domain.kind``
        sequence                ``domain.sequence_id``
        ======================= ============================================

        All other CloudEvents extension attributes are preserved in
        ``metadata.extensions``.

        Args:
            cloudevent: A dict conforming to the CloudEvents v1.0 JSON
                format (structured content mode).

        Returns:
            A ``Message`` ready for dispatch, persistence, or conversion
            to a domain object via ``to_domain_object()``.

        Raises:
            ValueError: If required CloudEvents attributes are missing
                or ``specversion`` is not ``"1.0"``.

        Example — consuming an external CloudEvent in a subscriber::

            @domain.subscriber(stream="orders")
            class OrderEventsSubscriber:
                def __call__(self, payload: dict) -> None:
                    message = Message.from_cloudevent(payload)
                    # Access data
                    order_id = message.data["order_id"]

        Example — round-tripping a Protean CloudEvent::

            original = Message.from_domain_object(event)
            ce = original.to_cloudevent()
            restored = Message.from_cloudevent(ce)
            domain_event = restored.to_domain_object()

        .. seealso::
            `CloudEvents v1.0.2 Specification
            <https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md>`_
        """
        # ── Validate required attributes ──
        missing = [
            attr
            for attr in ("specversion", "id", "type", "source")
            if attr not in cloudevent
        ]
        if missing:
            raise ValueError(
                f"CloudEvent is missing required attribute(s): {', '.join(missing)}"
            )

        specversion = cloudevent["specversion"]
        if specversion != "1.0":
            raise ValueError(
                f"Unsupported CloudEvents specversion '{specversion}'; "
                f"only '1.0' is supported"
            )

        # ── Extract known attributes ──
        ce_id: str = cloudevent["id"]
        ce_type: str = cloudevent["type"]
        ce_source: str = cloudevent["source"]
        ce_time_raw = cloudevent.get("time")
        ce_data: dict = cloudevent.get("data", {})
        ce_subject = cloudevent.get("subject")
        ce_datacontenttype = cloudevent.get("datacontenttype")
        ce_dataschema = cloudevent.get("dataschema")

        # Protean extensions
        traceparent_raw = cloudevent.get("traceparent")
        correlation_id = cloudevent.get("proteancorrelationid")
        causation_id = cloudevent.get("proteancausationid")
        checksum = cloudevent.get("proteanchecksum")
        kind = cloudevent.get("proteankind", MessageType.EVENT.value)
        sequence_id = cloudevent.get("sequence")

        # ── Parse time ──
        ce_time: datetime | None = None
        if ce_time_raw:
            if isinstance(ce_time_raw, datetime):
                ce_time = ce_time_raw
            elif isinstance(ce_time_raw, str):
                ce_time = datetime.fromisoformat(ce_time_raw)

        # ── Parse traceparent ──
        traceparent: TraceParent | None = None
        if traceparent_raw and isinstance(traceparent_raw, str):
            traceparent = TraceParent.build(traceparent_raw)

        # ── Build headers ──
        headers = MessageHeaders(
            id=ce_id,
            type=ce_type,
            time=ce_time,
            traceparent=traceparent,
        )

        # ── Build envelope ──
        envelope = MessageEnvelope(
            specversion=specversion,
            checksum=checksum or MessageEnvelope.compute_checksum(ce_data),
        )

        # ── Build domain meta ──
        domain_meta = DomainMeta(
            kind=kind,
            correlation_id=correlation_id,
            causation_id=causation_id,
            sequence_id=sequence_id,
        )

        # ── Collect extensions ──
        # Known CE/Protean attribute names to exclude from extensions
        _known_attrs = {
            "specversion",
            "id",
            "type",
            "source",
            "time",
            "subject",
            "datacontenttype",
            "dataschema",
            "data",
            "traceparent",
            "proteancorrelationid",
            "proteancausationid",
            "proteanchecksum",
            "proteankind",
            "sequence",
            "proteansequencetype",
        }
        extensions: dict[str, Any] = {}

        # Preserve CE-specific attributes that have no internal field
        extensions["ce_source"] = ce_source
        if ce_subject is not None:
            extensions["ce_subject"] = ce_subject
        if ce_datacontenttype and ce_datacontenttype != "application/json":
            extensions["ce_datacontenttype"] = ce_datacontenttype
        if ce_dataschema:
            extensions["ce_dataschema"] = ce_dataschema

        # Collect unknown CE extensions
        for key, value in cloudevent.items():
            if key not in _known_attrs:
                extensions[key] = value

        # ── Assemble metadata ──
        metadata = Metadata(
            headers=headers,
            envelope=envelope,
            domain=domain_meta,
            extensions=extensions,
        )

        return cls(data=ce_data, metadata=metadata)
