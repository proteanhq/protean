from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar

from pydantic import ValidationError as PydanticValidationError

from protean.core.value_object import _convert_pydantic_errors
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    InvalidDataError,
    NotSupportedError,
)
from protean.utils import (
    DomainObjects,
    derive_element_class,
    fqn,
)
from protean.utils.eventing import (
    BaseMessageType,
    DomainMeta,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import g

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BaseEvent
# ---------------------------------------------------------------------------
class BaseEvent(BaseMessageType):
    """Base Event class that all Events should inherit from.

    Fields are declared using standard Python type annotations with optional
    Field constraints.
    """

    element_type: ClassVar[str] = DomainObjects.EVENT

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseEvent:
        if cls is BaseEvent:
            raise NotSupportedError("BaseEvent cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        incoming_metadata = kwargs.pop("_metadata", None)
        expected_version = kwargs.pop("_expected_version", -1)

        # Support template dict pattern: Event({"key": "val"}, key2="val2")
        # Keyword args take precedence over template dict values.
        if args:
            merged: dict[str, Any] = {}
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                merged.update(template)
            merged.update(kwargs)
            kwargs = merged

        # Template dicts (e.g. from to_dict()) may re-introduce _metadata,
        # _expected_version, and _version; prefer the explicitly passed
        # keyword args.  _version is an aggregate-internal field and is not
        # part of the event schema, so discard it silently.
        template_metadata = kwargs.pop("_metadata", None)
        if incoming_metadata is None:
            incoming_metadata = template_metadata
        template_expected_version = kwargs.pop("_expected_version", None)
        if expected_version == -1 and template_expected_version is not None:
            expected_version = template_expected_version
        kwargs.pop("_version", None)

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise InvalidDataError(_convert_pydantic_errors(e))

        # Store expected version as regular attr (before _initialized is set)
        object.__setattr__(self, "_expected_version", expected_version)

        # Build metadata
        self._build_metadata(incoming_metadata)

        object.__setattr__(self, "_initialized", True)

    def model_post_init(self, __context: Any) -> None:
        if not hasattr(self.__class__, "__type__"):
            raise ConfigurationError(
                f"`{self.__class__.__name__}` should be registered with a domain"
            )

    def _build_metadata(self, incoming: Metadata | None) -> None:
        """Build metadata for the event from incoming metadata or defaults."""
        origin_stream = None
        if hasattr(g, "message_in_context"):
            if (
                g.message_in_context.metadata.domain.kind == "COMMAND"
                and g.message_in_context.metadata.domain.origin_stream is not None
            ):
                origin_stream = g.message_in_context.metadata.domain.origin_stream

        # Use existing headers if they exist, but ensure type is set
        if incoming and hasattr(incoming, "headers") and incoming.headers:
            headers = MessageHeaders(
                id=incoming.headers.id,
                time=incoming.headers.time,
                type=incoming.headers.type or self.__class__.__type__,
                traceparent=incoming.headers.traceparent,
            )
        else:
            headers = MessageHeaders(
                type=self.__class__.__type__, time=datetime.now(timezone.utc)
            )

        # If metadata already has domain with sequence_id and asynchronous set (from raise_),
        # preserve those values
        existing_domain = (
            incoming.domain if incoming and hasattr(incoming, "domain") else None
        )

        # Build domain metadata
        domain_meta = DomainMeta(
            kind="EVENT",
            fqn=fqn(self.__class__),
            origin_stream=origin_stream,
            stream_category=existing_domain.stream_category
            if existing_domain and existing_domain.stream_category is not None
            else None,
            version=self.__class__.__version__,  # Was set in `__init_subclass__`
            sequence_id=existing_domain.sequence_id
            if existing_domain and existing_domain.sequence_id is not None
            else None,
            asynchronous=existing_domain.asynchronous
            if existing_domain and hasattr(existing_domain, "asynchronous")
            else True,
        )

        # Also preserve envelope if it exists
        existing_envelope = (
            incoming.envelope if incoming and hasattr(incoming, "envelope") else None
        )

        # Preserve stream in headers if it exists
        existing_stream = None
        if (
            incoming
            and hasattr(incoming, "headers")
            and incoming.headers
            and hasattr(incoming.headers, "stream")
        ):
            existing_stream = incoming.headers.stream

        # Create new headers with stream if needed
        if existing_stream:
            headers = MessageHeaders(**{**headers.to_dict(), "stream": existing_stream})

        metadata_kwargs = {"headers": headers, "domain": domain_meta}
        if existing_envelope is not None:
            metadata_kwargs["envelope"] = existing_envelope
        self._metadata = Metadata(**metadata_kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def domain_event_factory(element_cls: type, domain: Any, **opts: Any) -> type:
    # Always route to Pydantic base
    base_cls = BaseEvent

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
