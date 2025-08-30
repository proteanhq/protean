import logging

from datetime import datetime, timezone

from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
)
from protean.utils import DomainObjects, derive_element_class, fqn
from protean.utils.eventing import BaseMessageType, Metadata, MessageHeaders
from protean.utils.globals import g

logger = logging.getLogger(__name__)


class BaseEvent(BaseMessageType):
    """Base Event class that all Events should inherit from.

    Core functionality associated with Events, like timestamping, are specified
    as part of the base Event class.
    """

    element_type = DomainObjects.EVENT

    def __new__(cls, *args, **kwargs):
        if cls is BaseEvent:
            raise NotSupportedError("BaseEvent cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Store the expected version temporarily for use during persistence
        self._expected_version = kwargs.pop("_expected_version", -1)

        origin_stream = None
        if hasattr(g, "message_in_context"):
            if (
                g.message_in_context.metadata.kind == "COMMAND"
                and g.message_in_context.metadata.origin_stream is not None
            ):
                origin_stream = g.message_in_context.metadata.origin_stream

        # Value Objects are immutable, so we create a clone/copy and associate it
        # Use existing headers if they exist, but ensure type is set
        if hasattr(self._metadata, "headers") and self._metadata.headers:
            # Preserve existing headers but ensure type is set
            headers = MessageHeaders(
                id=self._metadata.headers.id,
                time=self._metadata.headers.time,
                type=self._metadata.headers.type or self.__class__.__type__,
                traceparent=self._metadata.headers.traceparent,
            )
        else:
            # Create new headers with type and current time
            headers = MessageHeaders(
                type=self.__class__.__type__, time=datetime.now(timezone.utc)
            )

        self._metadata = Metadata(
            self._metadata.to_dict(),  # Template from old Metadata
            kind="EVENT",
            fqn=fqn(self.__class__),
            origin_stream=origin_stream,
            version=self.__class__.__version__,  # Was set in `__init_subclass__`
            headers=headers,
        )

        # Finally lock the event and make it immutable
        self._initialized = True


def domain_event_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEvent, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
