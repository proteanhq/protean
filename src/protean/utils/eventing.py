import json
from datetime import datetime, timezone

from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import DateTime, Field, Integer, String, ValueObject
from protean.fields.association import Association, Reference
from protean.utils.container import BaseContainer, OptionsMixin
from protean.utils.reflection import _ID_FIELD_NAME, declared_fields, fields


class Metadata(BaseValueObject):
    # Unique identifier of the event/command
    #
    # FIXME Fix the format documentation
    # Event Format is <domain-name>.<class-name>.<version>.<aggregate-id>.<aggregate-version>
    # Command Format is <domain-name>.<class-name>.<version>
    id = String()

    # Type of the event
    # Format is <domain-name>.<event-class-name>.<event-version>
    type = String()

    # Fully Qualified Name of the event/command
    fqn = String(sanitize=False)

    # Kind of the object
    # Can be one of "EVENT", "COMMAND"
    kind = String()

    # Name of the stream to which the event/command is written
    stream = String()

    # Name of the stream that originated this event/command
    origin_stream = String()

    # Time of event generation
    timestamp = DateTime(default=lambda: datetime.now(timezone.utc))

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

    # Hash of the payload
    payload_hash = Integer()


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

        return self._metadata.id == other._metadata.id

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
