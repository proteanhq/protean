import logging
from typing import Any, ClassVar, Self, TypeVar, cast

from pydantic import ValidationError as PydanticValidationError

from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields.resolved import convert_pydantic_errors
from protean.utils import (
    DomainObjects,
    _check_part_of_kind,
    _derive_element_class,
    _ensure_template_dict,
    fqn,
)
from protean.utils.eventing import (
    BaseMessageType,
    DomainMeta,
    MessageHeaders,
    Metadata,
    _assemble_message_metadata,
    _resolve_message_lineage,
)
from protean.utils.globals import _domain_now, g
from protean.utils.telemetry import inject_traceparent_from_context

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BaseEvent
# ---------------------------------------------------------------------------
class BaseEvent(BaseMessageType):
    """Base class for domain events, immutable facts about state changes that
    have happened in the domain.

    Name events in the past tense (``OrderPlaced``, ``CustomerRegistered``).
    An event cannot be changed after it is created. It carries metadata for
    tracing: correlation ID, causation ID and stream position.

    Fields are declared with Python type annotations and optional ``Field``
    constraints. See the events guide.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate or process manager that raises this event. Required. |
    | ``published`` | ``bool`` | Whether this event is part of the bounded context's published language. Default ``False``. |
    | ``version`` | ``int`` | Message version number (alternative to ``__version__`` class attribute). Default ``1``. |
    """

    element_type: ClassVar[str] = DomainObjects.EVENT

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseEvent:
            raise NotSupportedError("BaseEvent cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a new event instance.

        Accepts keyword arguments matching the declared fields. Optionally,
        a ``dict`` can be passed as a positional argument to serve as a
        template. Keyword arguments take precedence over template values.

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
        rebuild = bool(kwargs.pop("_rebuild", False))
        expected_version = kwargs.pop("_expected_version", -1)

        # Support template dict pattern: Event({"key": "val"}, key2="val2")
        # Keyword args take precedence over template dict values.
        if args:
            merged: dict[str, Any] = {}
            for template in args:
                _ensure_template_dict(template)
                merged.update(template)
            merged.update(kwargs)
            kwargs = merged

        # Template dicts may carry _metadata (to_dict() includes it),
        # _expected_version, and _version; prefer the explicitly passed
        # keyword args.  _version is an aggregate-internal field and is not
        # part of the event schema, so discard it silently.
        template_metadata = kwargs.pop("_metadata", None)
        if incoming_metadata is None:
            incoming_metadata = template_metadata
        kwargs.pop("_rebuild", None)
        template_expected_version = kwargs.pop("_expected_version", None)
        if expected_version == -1 and template_expected_version is not None:
            expected_version = template_expected_version
        kwargs.pop("_version", None)

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise ValidationError(convert_pydantic_errors(e)) from e

        # Store expected version as regular attr (before _initialized is set)
        object.__setattr__(self, "_expected_version", expected_version)

        # Build metadata
        self._build_metadata(incoming_metadata, rebuild=rebuild)

        object.__setattr__(self, "_initialized", True)

    def model_post_init(self, context: Any, /) -> None:
        if not hasattr(self.__class__, "__type__"):
            raise ConfigurationError(
                f"`{self.__class__.__name__}` should be registered with a domain"
            )

    def _build_metadata(
        self, incoming: Metadata | None, *, rebuild: bool = False
    ) -> None:
        """Build metadata for the event from incoming metadata or defaults."""
        headers = _event_headers(self.__class__.__type__, incoming)

        # If metadata already has domain with sequence_id and asynchronous set (from raise_),
        # preserve those values
        existing_domain = (
            incoming.domain if incoming and hasattr(incoming, "domain") else None
        )

        origin_stream, correlation_id, causation_id = _resolve_message_lineage(
            existing_domain, _parent_event_lineage(), rebuild=rebuild
        )

        # Build domain metadata
        domain_meta = DomainMeta(
            kind="EVENT",
            fqn=fqn(self.__class__),
            origin_stream=origin_stream,
            version=self.__class__.__version__,  # Resolved at registration
            correlation_id=correlation_id,
            causation_id=causation_id,
            **_raised_domain_fields(existing_domain),
        )

        self._metadata = _assemble_message_metadata(
            incoming, headers, domain_meta, rebuild=rebuild
        )


def _parent_event_lineage() -> tuple[str | None, str | None, str | None]:
    """Return the ``(origin_stream, correlation_id, causation_id)`` a new
    event takes from the message being handled now, if any.

    The origin stream carries over only from a command that has one.
    """
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
    return origin_stream, correlation_id, causation_id


def _event_headers(type_: str, incoming: Metadata | None) -> MessageHeaders:
    """Return headers built from the incoming ones, with ``type_`` filled in
    if missing, or new headers of type ``type_`` that carry the current trace
    context."""
    # Use existing headers if they exist, but ensure type is set
    if incoming and hasattr(incoming, "headers") and incoming.headers:
        return MessageHeaders(
            id=incoming.headers.id,
            time=incoming.headers.time,
            type=incoming.headers.type or type_,
            traceparent=incoming.headers.traceparent,
        )

    # Inject the current OTEL span context as traceparent so that
    # events raised during handler execution carry the trace forward.
    traceparent = inject_traceparent_from_context()
    return MessageHeaders(type=type_, time=_domain_now(), traceparent=traceparent)


def _raised_domain_fields(existing_domain: DomainMeta | None) -> dict[str, Any]:
    """Return the domain fields ``raise_()`` set, or their defaults."""
    return {
        "stream_category": existing_domain.stream_category
        if existing_domain and existing_domain.stream_category is not None
        else None,
        "sequence_id": existing_domain.sequence_id
        if existing_domain and existing_domain.sequence_id is not None
        else None,
        "asynchronous": existing_domain.asynchronous
        if existing_domain and hasattr(existing_domain, "asynchronous")
        else True,
    }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_T = TypeVar("_T")


def domain_event_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    # Always route to Pydantic base
    base_cls = BaseEvent

    element_cls = _derive_element_class(element_cls, base_cls, **opts)

    # `_derive_element_class` returns a subclass of ``base_cls`` (here
    # ``BaseEvent``); narrow to expose ``meta_`` to the type checkers. The
    # unbounded ``_T`` return contract is preserved via ``element_cls`` below.
    event_cls = cast("type[BaseEvent]", element_cls)

    if not event_cls.meta_.part_of and not event_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Event `{event_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    _check_part_of_kind(event_cls)

    if not isinstance(event_cls.meta_.published, bool):
        raise IncorrectUsageError(
            f"Event `{event_cls.__name__}` has invalid `published` option "
            f"`{event_cls.meta_.published}`. Must be True or False."
        )

    return element_cls
