from protean.exceptions import (
    IncorrectUsageError,
    InvalidDataError,
    NotSupportedError,
    ValidationError,
)
from protean.utils import DomainObjects, derive_element_class, fqn
from protean.utils.eventing import BaseMessageType, Metadata
from protean.utils.globals import g


class BaseCommand(BaseMessageType):
    """Base Command class that all commands should inherit from.

    Core functionality associated with commands, like timestamping and authentication, are specified
    as part of the base command class.
    """

    element_type = DomainObjects.COMMAND

    def __new__(cls, *args, **kwargs):
        if cls is BaseCommand:
            raise NotSupportedError("BaseCommand cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)

            version = (
                self.__class__.__version__
                if hasattr(self.__class__, "__version__")
                else "v1"
            )

            origin_stream = None
            if hasattr(g, "message_in_context"):
                if g.message_in_context.metadata.kind == "EVENT":
                    origin_stream = g.message_in_context.stream_name

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


def command_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseCommand, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Command `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
