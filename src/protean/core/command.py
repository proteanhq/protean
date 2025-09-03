from datetime import datetime, timezone

from protean.exceptions import (
    IncorrectUsageError,
    InvalidDataError,
    NotSupportedError,
    ValidationError,
)
from protean.utils import DomainObjects, derive_element_class, fqn
from protean.utils.eventing import BaseMessageType, Metadata, MessageHeaders, DomainMeta
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
                if g.message_in_context.metadata.domain.kind == "EVENT":
                    origin_stream = g.message_in_context.metadata.headers.stream

            # Use existing headers if they have meaningful content, otherwise create new ones
            has_meaningful_headers = (
                hasattr(self._metadata, "headers")
                and self._metadata.headers
                and (self._metadata.headers.type or self._metadata.headers.id)
            )

            headers = (
                self._metadata.headers
                if has_meaningful_headers
                else MessageHeaders(
                    type=self.__class__.__type__, time=datetime.now(timezone.utc)
                )
            )

            # If metadata already has domain with sequence_id and asynchronous set (from enrich),
            # preserve those values
            existing_domain = (
                self._metadata.domain if hasattr(self._metadata, "domain") else None
            )

            # Build domain metadata
            domain_meta = DomainMeta(
                kind="COMMAND",
                fqn=fqn(self.__class__),
                origin_stream=origin_stream,
                version=version,
                sequence_id=existing_domain.sequence_id
                if existing_domain and hasattr(existing_domain, "sequence_id")
                else None,
                asynchronous=existing_domain.asynchronous
                if existing_domain and hasattr(existing_domain, "asynchronous")
                else True,
            )

            # Also preserve envelope if it exists
            existing_envelope = (
                self._metadata.envelope if hasattr(self._metadata, "envelope") else None
            )

            # Preserve stream in headers if it exists
            existing_stream = None
            if (
                hasattr(self._metadata, "headers")
                and self._metadata.headers
                and hasattr(self._metadata.headers, "stream")
            ):
                existing_stream = self._metadata.headers.stream

            # Create new headers with stream if needed
            if existing_stream:
                headers = MessageHeaders(
                    **{**headers.to_dict(), "stream": existing_stream}
                )

            self._metadata = Metadata(
                headers=headers,
                envelope=existing_envelope,
                domain=domain_meta,
            )

            # Finally lock the command and make it immutable
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
