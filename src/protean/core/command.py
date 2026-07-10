from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar, cast

from pydantic import ValidationError as PydanticValidationError

from protean._deprecation import warn_deprecated
from protean.fields.resolved import convert_pydantic_errors
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.utils import (
    DomainObjects,
    _derive_element_class,
    fqn,
)
from protean.utils.eventing import (
    BaseMessageType,
    DomainMeta,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import g


# The ``published`` option a command silently inherited from ``BaseMessageType``
# but never acted on: commands are internal and take no part in the published
# language. Deprecated in 0.17 (warn + ``protean check`` diagnostic), removed at
# 1.0 where ``command_factory`` will raise ``IncorrectUsageError`` naming the
# option instead of dropping it. (``is_fact_event`` is framework-internal and
# rejected outright by ``_derive_element_class``; it is not deprecated here.)
_DEPRECATED_COMMAND_OPTIONS: tuple[str, ...] = ("published",)


# ---------------------------------------------------------------------------
# BaseCommand
# ---------------------------------------------------------------------------
class BaseCommand(BaseMessageType):
    """Base class for domain commands -- immutable DTOs representing an intent
    to change aggregate state.

    Commands are named with imperative verbs (``PlaceOrder``,
    ``RegisterUser``, ``CancelReservation``) and processed by command handlers.
    They are immutable after construction and carry metadata for tracing
    (correlation ID, causation ID, origin stream).

    Fields are declared using standard Python type annotations with optional
    ``Field`` constraints.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate class this command targets. Required. |
    | ``version`` | ``int`` | Message version number (alternative to ``__version__`` class attribute). Default ``1``. |
    """

    element_type: ClassVar[str] = DomainObjects.COMMAND

    # Commands are internal to the bounded context: unlike events, they never
    # participate in the published language. Drop ``published`` from the
    # inherited option set so it is not a valid command option. Filter the parent
    # list rather than re-transcribing it, so future additions to
    # ``BaseMessageType`` are inherited automatically. See ``command_factory`` for
    # the deprecation window that lets existing (no-op) usage warn before it
    # raises. (``is_fact_event`` stays in the inherited options and remains a
    # framework-internal option, so passing it is rejected, not deprecated.)
    _default_options: ClassVar[list[tuple[str, Any]]] = [
        (name, default)
        for (name, default) in BaseMessageType._default_options
        if name not in _DEPRECATED_COMMAND_OPTIONS
    ]

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseCommand":
        if cls is BaseCommand:
            raise NotSupportedError("BaseCommand cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create a new command instance.

        Accepts keyword arguments matching the declared fields. Optionally,
        a ``dict`` can be passed as a positional argument to serve as a
        template — keyword arguments take precedence over template values.

        Args:
            *args (dict): Optional template dictionaries for field values.
            **kwargs (Any): Field values for the command.

        Raises:
            ValidationError: If field validation fails.

        Example::

            # Keyword arguments
            PlaceOrder(order_id="abc", amount=100)

            # Template dict pattern
            PlaceOrder({"order_id": "abc"}, amount=100)
        """
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
            raise ValidationError(convert_pydantic_errors(e))

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
            self.__class__.__version__ if hasattr(self.__class__, "__version__") else 1
        )

        origin_stream = None
        correlation_id = None
        causation_id = None
        if hasattr(g, "message_in_context"):
            msg_ctx = g.message_in_context
            if msg_ctx.metadata.domain.kind == "EVENT":
                origin_stream = msg_ctx.metadata.headers.stream
            # Inherit correlation_id from parent message
            if msg_ctx.metadata.domain:
                correlation_id = msg_ctx.metadata.domain.correlation_id
            # Set causation_id = parent message's ID
            if msg_ctx.metadata.headers:
                causation_id = msg_ctx.metadata.headers.id

        # Use existing headers if they have meaningful content, otherwise create new ones
        has_meaningful_headers = (
            incoming
            and hasattr(incoming, "headers")
            and incoming.headers
            and (
                incoming.headers.type
                or incoming.headers.id
                or incoming.headers.traceparent
            )
        )

        if has_meaningful_headers:
            headers = incoming.headers  # type: ignore[union-attr]
            # Ensure type is set even when headers were kept for traceparent
            if not headers.type:
                headers = MessageHeaders(
                    id=headers.id,
                    time=headers.time or datetime.now(timezone.utc),
                    type=self.__class__.__type__,
                    stream=headers.stream,
                    traceparent=headers.traceparent,
                    idempotency_key=headers.idempotency_key,
                    deadline=headers.deadline,
                )
        else:
            headers = MessageHeaders(
                type=self.__class__.__type__, time=datetime.now(timezone.utc)
            )

        # If metadata already has domain with sequence_id and asynchronous set (from enrich),
        # preserve those values
        existing_domain = (
            incoming.domain if incoming and hasattr(incoming, "domain") else None
        )

        # Build domain metadata — preserve values from _enrich_command() if set
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
            correlation_id=existing_domain.correlation_id
            if existing_domain and existing_domain.correlation_id
            else correlation_id,
            causation_id=existing_domain.causation_id
            if existing_domain and existing_domain.causation_id
            else causation_id,
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

        metadata_kwargs: dict[str, Any] = {"headers": headers, "domain": domain_meta}
        if existing_envelope is not None:
            metadata_kwargs["envelope"] = existing_envelope
        # Preserve extensions from incoming metadata (set by command enrichers,
        # and lenient-deserialization dropped-field records).
        if incoming and hasattr(incoming, "extensions") and incoming.extensions:
            metadata_kwargs["extensions"] = incoming.extensions
        self._metadata = Metadata(**metadata_kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_T = TypeVar("_T")


def command_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    # Always route to Pydantic base
    base_cls = BaseCommand

    # Warn-and-drop options that commands used to inherit but never honoured.
    # This MUST run before ``_derive_element_class``: once these options are no
    # longer in ``BaseCommand._default_options``, that call would raise
    # ``ConfigurationError("Unknown option(s) ...")`` and skip the deprecation
    # window. Both the ``@domain.command`` decorator and ``domain.register()``
    # funnel through here, so one interception covers every entry point.
    deprecated_used: list[str] = []
    for opt in _DEPRECATED_COMMAND_OPTIONS:
        if opt in opts:
            warn_deprecated(
                f"The `{opt}` option on a command",
                removal="1.0.0",
                alternative=(
                    "Commands are internal to the bounded context; only events "
                    "are published. It has no effect."
                ),
            )
            opts.pop(opt)
            deprecated_used.append(opt)

    element_cls = _derive_element_class(element_cls, base_cls, **opts)

    # Record the dropped options on the class so ``protean check`` can surface
    # them as a ``DEPRECATED_OPTION`` diagnostic. The runtime warning above fires
    # transiently at registration and leaves no residue on ``meta_``; this
    # attribute is the only durable trace the IR builder can read at check time.
    # Always assign (even when empty) so this call's outcome shadows any stale
    # value left by an earlier in-place registration of the same class, or one
    # inherited from a base command class.
    element_cls._deprecated_options = tuple(deprecated_used)  # type: ignore[attr-defined]

    # `_derive_element_class` returns a subclass of ``base_cls`` (here
    # ``BaseCommand``); narrow to expose ``meta_`` to the type checkers. The
    # unbounded ``_T`` return contract is preserved via ``element_cls`` below.
    command_cls = cast("type[BaseCommand]", element_cls)

    if not command_cls.meta_.part_of and not command_cls.meta_.abstract:
        raise IncorrectUsageError(
            f"Command `{command_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
