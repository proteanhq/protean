from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from pydantic import ValidationError as PydanticValidationError

from protean.core.value_object import _convert_pydantic_errors
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    InvalidDataError,
    NotSupportedError,
    ValidationError,
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


# ---------------------------------------------------------------------------
# Legacy BaseCommand (old BaseContainer-based implementation)
# ---------------------------------------------------------------------------
class _LegacyBaseCommand(_LegacyBaseMessageType):
    """Legacy Base Command class backed by BaseContainer and Protean field descriptors.

    This class preserves the original implementation for:
    - Commands created dynamically or using old-style field descriptors
    - Internal framework usage that relies on BaseContainer patterns
    """

    element_type = DomainObjects.COMMAND

    def __new__(cls, *args: Any, **kwargs: Any) -> _LegacyBaseCommand:
        if cls is _LegacyBaseCommand:
            raise NotSupportedError("_LegacyBaseCommand cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
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


# ---------------------------------------------------------------------------
# New Pydantic-based BaseCommand
# ---------------------------------------------------------------------------
class BaseCommand(BaseMessageType):
    """Base Command class that all commands should inherit from.

    Uses Pydantic v2 BaseModel for field declaration, validation, and serialization.
    Fields are declared using standard Python type annotations with optional
    pydantic.Field constraints.
    """

    element_type: ClassVar[str] = DomainObjects.COMMAND

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseCommand:
        if cls is BaseCommand:
            raise NotSupportedError("BaseCommand cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        incoming_metadata = kwargs.pop("_metadata", None)

        # Support template dict pattern: Command({"key": "val"}, key2="val2")
        if args:
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                kwargs.update(template)

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise InvalidDataError(_convert_pydantic_errors(e))

        # Build metadata
        self._build_metadata(incoming_metadata)

        object.__setattr__(self, "_initialized", True)

    def model_post_init(self, __context: Any) -> None:
        if not hasattr(self.__class__, "__type__"):
            raise ConfigurationError(
                f"`{self.__class__.__name__}` should be registered with a domain"
            )

    def _build_metadata(self, incoming: Metadata | None) -> None:
        """Build metadata for the command from incoming metadata or defaults."""
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
            incoming
            and hasattr(incoming, "headers")
            and incoming.headers
            and (incoming.headers.type or incoming.headers.id)
        )

        headers = (
            incoming.headers
            if has_meaningful_headers
            else MessageHeaders(
                type=self.__class__.__type__, time=datetime.now(timezone.utc)
            )
        )

        # If metadata already has domain with sequence_id and asynchronous set (from enrich),
        # preserve those values
        existing_domain = (
            incoming.domain if incoming and hasattr(incoming, "domain") else None
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

        self._metadata = Metadata(
            headers=headers,
            envelope=existing_envelope,
            domain=domain_meta,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def command_factory(element_cls: type, domain: Any, **opts: Any) -> type:
    # Determine the correct base class:
    # 1. Explicit Pydantic inheritance → Pydantic
    # 2. Already inherits from legacy base → Legacy
    # 3. Has legacy data fields (String, Integer, etc.) → Legacy
    # 4. Otherwise (annotation-based or empty) → Pydantic
    if issubclass(element_cls, BaseCommand):
        base_cls = BaseCommand
    elif issubclass(element_cls, _LegacyBaseCommand):
        base_cls = _LegacyBaseCommand
    elif _has_legacy_data_fields(element_cls):
        base_cls = _LegacyBaseCommand
    else:
        base_cls = BaseCommand

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Command `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
