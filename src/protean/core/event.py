import json
import logging
from datetime import datetime, timezone

from protean.container import BaseContainer, OptionsMixin
from protean.core.value_object import BaseValueObject
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import DateTime, Field, Integer, String, ValueObject
from protean.globals import g
from protean.reflection import _ID_FIELD_NAME, declared_fields, fields
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class Metadata(BaseValueObject):
    # Unique identifier of the Event
    # Format is <domain-name>.<event-class-name>.<event-version>.<aggregate-id>.<aggregate-version>
    id = String()

    # Type of the event
    # Format is <domain-name>.<event-class-name>.<event-version>
    type = String()

    # Kind of the object
    # Can be one of "EVENT", "COMMAND"
    kind = String()

    # Name of the stream to which the event/command is written
    stream_name = String()

    # Name of the stream that originated this event/command
    origin_stream_name = String()

    # Time of event generation
    timestamp = DateTime(default=lambda: datetime.now(timezone.utc))

    # Version of the event
    # Can be overridden with `__version__` class attr in Event class definition
    version = String(default="v1")

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


class BaseEvent(BaseContainer, OptionsMixin):  # FIXME Remove OptionsMixin
    """Base Event class that all Events should inherit from.

    Core functionality associated with Events, like timestamping, are specified
    as part of the base Event class.
    """

    element_type = DomainObjects.EVENT

    def __new__(cls, *args, **kwargs):
        if cls is BaseEvent:
            raise NotSupportedError("BaseEvent cannot be instantiated")
        return super().__new__(cls)

    # Track Metadata
    _metadata = ValueObject(Metadata, default=lambda: Metadata())  # pragma: no cover

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        if not subclass.meta_.abstract:
            subclass.__track_id_field()

        # Use explicit version if specified, else default to "v1"
        if not hasattr(subclass, "__version__"):
            setattr(subclass, "__version__", "v1")

    def __setattr__(self, name, value):
        if not hasattr(self, "_initialized") or not self._initialized:
            return super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                {
                    "_event": [
                        "Event Objects are immutable and cannot be modified once created"
                    ]
                }
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
        """Check if an identifier field has been associated with the command.

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
                f"Event `{self.__class__.__name__}` should be registered with a domain"
            )

        # Store the expected version temporarily for use during persistence
        self._expected_version = kwargs.pop("_expected_version", -1)

        origin_stream_name = None
        if hasattr(g, "message_in_context"):
            if (
                g.message_in_context.metadata.kind == "COMMAND"
                and g.message_in_context.metadata.origin_stream_name is not None
            ):
                origin_stream_name = g.message_in_context.metadata.origin_stream_name

        # Value Objects are immutable, so we create a clone/copy and associate it
        self._metadata = Metadata(
            self._metadata.to_dict(),  # Template from old Metadata
            type=self.__class__.__type__,
            kind="EVENT",
            origin_stream_name=origin_stream_name,
            version=self.__class__.__version__,  # Was set in `__init_subclass__`
        )

        # Finally lock the event and make it immutable
        self._initialized = True

    @property
    def payload(self):
        """Return the payload of the event."""
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in fields(self).items()
            if field_name not in {"_metadata"}
        }

    def __eq__(self, other) -> bool:
        """Equivalence check based only on data."""
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


def domain_event_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEvent, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            {
                "_event": [
                    f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
                ]
            }
        )

    # Set the event type for the event class
    setattr(
        element_cls,
        "__type__",
        f"{domain.name}.{element_cls.__name__}.{element_cls.__version__}",
    )

    return element_cls
