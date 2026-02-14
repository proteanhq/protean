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
    _has_legacy_data_fields,
    derive_element_class,
    fqn,
)
from protean.utils.eventing import (
    BaseMessageType,
    DomainMeta,
    MessageHeaders,
    Metadata,
    _LegacyBaseMessageType,
)
from protean.utils.globals import g

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy BaseEvent (old BaseContainer-based implementation)
# ---------------------------------------------------------------------------
class _LegacyBaseEvent(_LegacyBaseMessageType):
    """Legacy Base Event class backed by BaseContainer and Protean field descriptors.

    This class preserves the original implementation for:
    - Events created dynamically (element_to_fact_event)
    - Internal framework usage that relies on BaseContainer patterns
    """

    element_type = DomainObjects.EVENT

    def __new__(cls, *args: Any, **kwargs: Any) -> _LegacyBaseEvent:
        if cls is _LegacyBaseEvent:
            raise NotSupportedError("_LegacyBaseEvent cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Store the expected version temporarily for use during persistence
        self._expected_version = kwargs.pop("_expected_version", -1)

        origin_stream = None
        if hasattr(g, "message_in_context"):
            if (
                g.message_in_context.metadata.domain.kind == "COMMAND"
                and g.message_in_context.metadata.domain.origin_stream is not None
            ):
                origin_stream = g.message_in_context.metadata.domain.origin_stream

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

        # If metadata already has domain with sequence_id and asynchronous set (from raise_),
        # preserve those values
        existing_domain = (
            self._metadata.domain if hasattr(self._metadata, "domain") else None
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
            headers = MessageHeaders(**{**headers.to_dict(), "stream": existing_stream})

        metadata_kwargs = {"headers": headers, "domain": domain_meta}
        if existing_envelope is not None:
            metadata_kwargs["envelope"] = existing_envelope
        self._metadata = Metadata(**metadata_kwargs)

        # Finally lock the event and make it immutable
        self._initialized = True


# ---------------------------------------------------------------------------
# New Pydantic-based BaseEvent
# ---------------------------------------------------------------------------
class BaseEvent(BaseMessageType):
    """Base Event class that all Events should inherit from.

    Uses Pydantic v2 BaseModel for field declaration, validation, and serialization.
    Fields are declared using standard Python type annotations with optional
    pydantic.Field constraints.
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
        if args:
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                kwargs.update(template)

        # Template dicts (e.g. from to_dict()) may re-introduce _metadata
        # and _expected_version; prefer the explicitly passed keyword args.
        template_metadata = kwargs.pop("_metadata", None)
        if incoming_metadata is None:
            incoming_metadata = template_metadata
        template_expected_version = kwargs.pop("_expected_version", None)
        if expected_version == -1 and template_expected_version is not None:
            expected_version = template_expected_version

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
    # Determine the correct base class:
    # 1. Explicit Pydantic inheritance → Pydantic
    # 2. Already inherits from legacy base → Legacy
    # 3. Has legacy data fields (String, Integer, etc.) → Legacy
    # 4. Otherwise (annotation-based or empty) → Pydantic
    if issubclass(element_cls, BaseEvent):
        base_cls = BaseEvent
    elif issubclass(element_cls, _LegacyBaseEvent):
        base_cls = _LegacyBaseEvent
    elif _has_legacy_data_fields(element_cls):
        base_cls = _LegacyBaseEvent
    else:
        base_cls = BaseEvent

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
