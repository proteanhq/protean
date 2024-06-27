import logging
from datetime import datetime, timezone

from protean.container import BaseContainer, OptionsMixin
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import DateTime, Field, Integer, String, ValueObject
from protean.reflection import _ID_FIELD_NAME, declared_fields, fields
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class Metadata(BaseValueObject):
    # Unique identifier of the Event
    # Format is <domain-name>.<event-class-name>.<event-version>.<aggregate-id>.<aggregate-version>
    id = String()

    # Time of event generation
    timestamp = DateTime(default=lambda: datetime.now(timezone.utc))

    # Version of the event
    # Can be overridden with `__version__` class attr in Event class definition
    version = String(default="v1")

    # Sequence of the event in the aggregate
    # This is the version of the aggregate *after* the time of event generation,
    #   so it will always be one more than the version in the event store.
    sequence_id = Integer()


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
        part_of = (
            getattr(cls.meta_, "part_of") if hasattr(cls.meta_, "part_of") else None
        )

        # This method is called during class import, so we cannot use part_of if it
        #   is still a string. We ignore it for now, and resolve `stream_name` later
        #   when the domain has resolved references.
        # FIXME A better mechanism would be to not set stream_name here, unless explicitly
        #   specified, and resolve it during `domain.init()`
        part_of = None if isinstance(part_of, str) else part_of

        return [
            ("abstract", False),
            ("part_of", None),
            ("stream_name", part_of.meta_.stream_name if part_of else None),
            ("aggregate_cluster", None),
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

        if hasattr(self.__class__, "__version__"):
            # Value Objects are immutable, so we create a clone/copy and associate it
            self._metadata = Metadata(
                self._metadata.to_dict(), version=self.__class__.__version__
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

        return self.payload == other.payload


def domain_event_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseEvent, **kwargs)

    if (
        not (element_cls.meta_.part_of or element_cls.meta_.stream_name)
        and not element_cls.meta_.abstract
    ):
        raise IncorrectUsageError(
            {
                "_event": [
                    f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
                ]
            }
        )

    return element_cls
