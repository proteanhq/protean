from protean.container import BaseContainer, OptionsMixin
from protean.core.event import Metadata
from protean.exceptions import (
    IncorrectUsageError,
    InvalidDataError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import Field, ValueObject
from protean.globals import g
from protean.reflection import _ID_FIELD_NAME, declared_fields, fields
from protean.utils import DomainObjects, derive_element_class, fqn


class BaseCommand(BaseContainer, OptionsMixin):
    """Base Command class that all commands should inherit from.

    Core functionality associated with commands, like timestamping and authentication, are specified
    as part of the base command class.
    """

    element_type = DomainObjects.COMMAND

    def __new__(cls, *args, **kwargs):
        if cls is BaseCommand:
            raise NotSupportedError("BaseCommand cannot be instantiated")
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

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, finalize=False, **kwargs)

            version = (
                self.__class__.__version__
                if hasattr(self.__class__, "__version__")
                else "v1"
            )

            origin_stream = None
            if hasattr(g, "message_in_context"):
                if g.message_in_context.metadata.kind == "EVENT":
                    origin_stream = g.message_in_context.stream

            # Value Objects are immutable, so we create a clone/copy and associate it
            self._metadata = Metadata(
                self._metadata.to_dict(),  # Template
                kind="COMMAND",
                fqn=fqn(self.__class__),
                origin_stream=origin_stream,
                version=version,
            )

            # Finally lock the event and make it immutable
            self._initialized = True

        except ValidationError as exception:
            raise InvalidDataError(exception.messages)

    @property
    def payload(self):
        """Return the payload of the event."""
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in fields(self).items()
            if field_name not in {"_metadata"}
        }

    def __setattr__(self, name, value):
        if not hasattr(self, "_initialized") or not self._initialized:
            return super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                {
                    "_command": [
                        "Command Objects are immutable and cannot be modified once created"
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

    def to_dict(self):
        """Return data as a dictionary.

        We need to override this method in Command, because `to_dict()` of `BaseContainer`
        eliminates `_metadata`.
        """
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in fields(self).items()
        }


def command_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseCommand, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            {
                "_command": [
                    f"Command `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
                ]
            }
        )

    return element_cls
