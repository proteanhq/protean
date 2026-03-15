import logging
from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar

from pydantic import ValidationError as PydanticValidationError

from protean.fields.resolved import convert_pydantic_errors
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
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
    """Base class for domain events -- immutable facts representing state
    changes that have occurred in the domain.

    Events are named in past tense (``OrderPlaced``, ``CustomerRegistered``,
    ``PaymentConfirmed``) and enable decoupled communication between system
    components. They are immutable after construction and carry metadata for
    tracing (correlation ID, causation ID, stream position).

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate class that raises this event. Required. |
    | ``published`` | ``bool`` | Whether this event is part of the bounded context's published language. Default ``False``. |
    | ``version`` | ``int`` | Message version number (alternative to ``__version__`` class attribute). Default ``1``. |
    """

    element_type: ClassVar[str] = DomainObjects.EVENT

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseEvent":
        if cls is BaseEvent:
            raise NotSupportedError("BaseEvent cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a new event instance.

        Accepts keyword arguments matching the declared fields. Optionally,
        a ``dict`` can be passed as a positional argument to serve as a
        template — keyword arguments take precedence over template values.

        Events are typically created by calling ``self.raise_()`` inside an
        aggregate method rather than being instantiated directly.

        Args:
            *args (dict): Optional template dictionaries for field values.
            **kwargs (Any): Field values for the event.

        Raises:
            ValidationError: If field validation fails.

        Example::

            # Raised from an aggregate method
            self.raise_(OrderPlaced(order_id=self.id, amount=self.total))

            # Template dict pattern (e.g. during reconstitution)
            OrderPlaced({"order_id": "abc"}, amount=100)
        """
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
            raise ValidationError(convert_pydantic_errors(e))

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
        correlation_id = None
        causation_id = None
        if hasattr(g, "message_in_context"):
            msg_ctx = g.message_in_context
            if (
                msg_ctx.metadata.domain.kind == "COMMAND"
                and msg_ctx.metadata.domain.origin_stream is not None
            ):
                origin_stream = msg_ctx.metadata.domain.origin_stream
            # Inherit correlation_id from the command being processed
            if msg_ctx.metadata.domain:
                correlation_id = msg_ctx.metadata.domain.correlation_id
            # causation_id = the command's message ID
            if msg_ctx.metadata.headers:
                causation_id = msg_ctx.metadata.headers.id

        # Use existing headers if they exist, but ensure type is set
        if incoming and hasattr(incoming, "headers") and incoming.headers:
            headers = MessageHeaders(
                id=incoming.headers.id,
                time=incoming.headers.time,
                type=incoming.headers.type or self.__class__.__type__,
                traceparent=incoming.headers.traceparent,
            )
        else:
            # Inject the current OTEL span context as traceparent so that
            # events raised during handler execution carry the trace forward.
            from protean.utils.telemetry import inject_traceparent_from_context

            traceparent = inject_traceparent_from_context()
            headers = MessageHeaders(
                type=self.__class__.__type__,
                time=datetime.now(timezone.utc),
                traceparent=traceparent,
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
            correlation_id=correlation_id,
            causation_id=causation_id,
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
        # Preserve extensions from incoming metadata (set by event enrichers)
        if incoming and hasattr(incoming, "extensions") and incoming.extensions:
            metadata_kwargs["extensions"] = incoming.extensions
        self._metadata = Metadata(**metadata_kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_T = TypeVar("_T")


def domain_event_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    # Always route to Pydantic base
    base_cls = BaseEvent

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of and not element_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Event `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    if not isinstance(element_cls.meta_.published, bool):
        raise IncorrectUsageError(
            f"Event `{element_cls.__name__}` has invalid `published` option "
            f"`{element_cls.meta_.published}`. Must be True or False."
        )

    return element_cls
