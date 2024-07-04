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
from protean.reflection import _ID_FIELD_NAME, declared_fields
from protean.utils import DomainObjects, derive_element_class


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

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, finalize=False, **kwargs)

            version = (
                self.__class__.__version__
                if hasattr(self.__class__, "__version__")
                else "v1"
            )

            origin_stream_name = None
            if hasattr(g, "message_in_context"):
                if g.message_in_context.metadata.kind == "EVENT":
                    origin_stream_name = g.message_in_context.stream_name

            # Value Objects are immutable, so we create a clone/copy and associate it
            self._metadata = Metadata(
                self._metadata.to_dict(),  # Template
                kind="COMMAND",
                origin_stream_name=origin_stream_name,
                version=version,
            )

            # Finally lock the event and make it immutable
            self._initialized = True

        except ValidationError as exception:
            raise InvalidDataError(exception.messages)

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
            ("aggregate_cluster", None),
            ("part_of", None),
            ("stream_name", part_of.meta_.stream_name if part_of else None),
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


def command_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseCommand, **kwargs)

    if (
        not (element_cls.meta_.part_of or element_cls.meta_.stream_name)
        and not element_cls.meta_.abstract
    ):
        raise IncorrectUsageError(
            {
                "_command": [
                    f"Command `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
                ]
            }
        )

    return element_cls
