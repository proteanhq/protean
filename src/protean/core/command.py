from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar

from pydantic import ValidationError as PydanticValidationError

from protean.fields.resolved import convert_pydantic_errors
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


# ---------------------------------------------------------------------------
# BaseCommand
# ---------------------------------------------------------------------------
class BaseCommand(BaseMessageType):
    """Base Command class that all commands should inherit from.

    Fields are declared using standard Python type annotations with optional
    Field constraints.
    """

    element_type: ClassVar[str] = DomainObjects.COMMAND

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseCommand:
        if cls is BaseCommand:
            raise NotSupportedError("BaseCommand cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        incoming_metadata = kwargs.pop("_metadata", None)

        # Support template dict pattern: Command({"key": "val"}, key2="val2")
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

        # Template dicts (e.g. from to_dict()) may re-introduce _metadata
        # and _version; prefer the explicitly passed keyword arg, fall back
        # to template value.  _version is an aggregate-internal field and is
        # not part of the command schema, so discard it silently.
        template_metadata = kwargs.pop("_metadata", None)
        if incoming_metadata is None:
            incoming_metadata = template_metadata
        kwargs.pop("_version", None)

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise InvalidDataError(convert_pydantic_errors(e))

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

        metadata_kwargs = {"headers": headers, "domain": domain_meta}
        if existing_envelope is not None:
            metadata_kwargs["envelope"] = existing_envelope
        self._metadata = Metadata(**metadata_kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def command_factory(element_cls: type, domain: Any, **opts: Any) -> type:
    # Always route to Pydantic base
    base_cls = BaseCommand

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Command `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
