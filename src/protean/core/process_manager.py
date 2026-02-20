"""Process Manager module for coordinating multi-aggregate business processes.

A Process Manager is a stateful event-driven coordinator that reacts to events
from multiple aggregate streams, correlates them to the correct process instance,
and issues commands to drive the process forward. State is persisted as
auto-generated transition events in the event store.

Example::

    @domain.process_manager(stream_categories=["ecommerce::order", "ecommerce::payment"])
    class OrderFulfillmentPM:
        order_id = Identifier()
        status = String(default="new")

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_order_placed(self, event: OrderPlaced) -> None:
            self.order_id = event.order_id
            self.status = "awaiting_payment"
            current_domain.process(RequestPayment(order_id=event.order_id))

        @handle(PaymentConfirmed, correlate="order_id")
        def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
            self.status = "completed"
            self.mark_as_complete()
"""

import logging
from datetime import date, datetime
from typing import Any, ClassVar, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic_core import PydanticUndefined

from protean.core.event import BaseEvent
from protean.exceptions import (
    ConfigurationError,
    NotSupportedError,
)
from protean.fields.resolved import ResolvedField
from protean.fields.spec import FieldSpec
from protean.utils import (
    DomainObjects,
    derive_element_class,
    fqn,
    inflection,
)
from protean.utils.container import OptionsMixin
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import current_domain
from protean.utils.mixins import HandlerMixin
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME

logger = logging.getLogger(__name__)


def _resolve_correlation_value(
    event: BaseEvent, correlate_spec: Union[str, dict[str, str]]
) -> str:
    """Extract the correlation value from an event using the correlate spec.

    Args:
        event: The domain event to extract the correlation value from.
        correlate_spec: Either a string (same field name on event and PM) or
            a dict mapping ``{pm_field: event_field}``.

    Returns:
        The correlation value as a string.
    """
    if isinstance(correlate_spec, str):
        return str(getattr(event, correlate_spec))
    elif isinstance(correlate_spec, dict):
        event_field = next(iter(correlate_spec.values()))
        return str(getattr(event, event_field))
    else:
        raise ConfigurationError(f"Invalid correlate spec: {correlate_spec}")


def _generate_pm_transition_event(pm_cls: type) -> type:
    """Auto-generate a transition event class for a process manager.

    The transition event captures the PM's full field state after each handler
    invocation, enabling event-sourced reconstitution.

    Args:
        pm_cls: The process manager class to generate the transition event for.

    Returns:
        A dynamically created BaseEvent subclass.
    """
    ns: dict[str, Any] = {
        "__annotations__": {
            "state": dict,
            "handler_name": str,
            "is_complete": bool,
        },
        "state": ...,
        "handler_name": ...,
        "is_complete": False,
    }

    event_cls = type(
        f"_{pm_cls.__name__}Transition",
        (BaseEvent,),
        ns,
    )

    return event_cls


class BaseProcessManager(BaseModel, HandlerMixin, OptionsMixin):
    """Base class for Process Managers.

    A Process Manager combines handler-like event dispatch (from multiple
    aggregate streams) with aggregate-like stateful persistence (via
    auto-generated transition events in the event store).

    Meta Options:
        stream_categories: List of stream categories to subscribe to.
        aggregates: List of aggregate classes to listen to (alternative to
            stream_categories — categories are derived from aggregates).
        subscription_type: The subscription type to use.
        subscription_profile: A predefined configuration profile.
        subscription_config: Dictionary of custom configuration overrides.
    """

    element_type: ClassVar[str] = DomainObjects.PROCESS_MANAGER

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        ignored_types=(FieldSpec, str, int, float, bool, list, dict, tuple, set, type),
    )

    # Internal state (PrivateAttr — excluded from model_dump/schema)
    _version: int = PrivateAttr(default=-1)
    _is_complete: bool = PrivateAttr(default=False)
    _correlation_value: Optional[str] = PrivateAttr(default=None)

    # ClassVar set during _setup_process_managers — the auto-generated transition event
    _transition_event_cls: ClassVar[Optional[type]] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseProcessManager":
        if cls is BaseProcessManager:
            raise NotSupportedError("BaseProcessManager cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        # Use aggregates if specified, otherwise default to empty list
        aggregates = (
            getattr(cls.meta_, "aggregates") if hasattr(cls.meta_, "aggregates") else []
        )

        # Use stream categories if specified; otherwise derive from aggregates
        stream_categories = (
            getattr(cls.meta_, "stream_categories")
            if hasattr(cls.meta_, "stream_categories")
            else []
        )

        if aggregates and not stream_categories:
            stream_categories = [
                aggregate.meta_.stream_category for aggregate in aggregates
            ]

        return [
            ("abstract", False),
            ("auto_add_id_field", True),
            ("stream_category", inflection.underscore(cls.__name__)),
            ("stream_categories", stream_categories),
            ("aggregates", aggregates),
            # Subscription configuration options
            ("subscription_type", None),
            ("subscription_profile", None),
            ("subscription_config", {}),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Set empty __container_fields__ placeholder
        setattr(cls, _FIELDS, {})

        # Resolve FieldSpec declarations before Pydantic processes annotations
        cls._resolve_fieldspecs()

    @classmethod
    def _resolve_fieldspecs(cls) -> None:
        from protean.fields.spec import resolve_fieldspecs

        resolve_fieldspecs(cls)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, ResolvedField] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = ResolvedField(fname, finfo, finfo.annotation)
        setattr(cls, _FIELDS, fields_dict)

        # Track identity field
        if not cls.meta_.abstract:
            cls.__track_id_field()

    @classmethod
    def __track_id_field(cls) -> None:
        """Find the field marked ``identifier=True`` and record its name."""
        try:
            id_fld = next(
                field
                for _, field in getattr(cls, _FIELDS, {}).items()
                if getattr(field, "identifier", False)
            )
            setattr(cls, _ID_FIELD_NAME, id_fld.field_name)
        except StopIteration:
            pass

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Support template dict pattern
        if args:
            merged: dict[str, Any] = {}
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict."
                    )
                merged.update(template)
            merged.update(kwargs)
            kwargs = merged

        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def mark_as_complete(self) -> None:
        """Mark this process manager as complete.

        Once complete, no further events will be processed for this instance.
        """
        self._is_complete = True

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return process manager data as a dictionary."""
        result: dict[str, Any] = {}
        for fname, shim in getattr(self, _FIELDS, {}).items():
            if fname.startswith("_"):
                continue
            result[fname] = shim.as_dict(getattr(self, fname, None))
        return result

    # ------------------------------------------------------------------
    # Identity-based equality
    # ------------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name is None:
            return False
        return getattr(self, id_field_name) == getattr(other, id_field_name)

    def __hash__(self) -> int:
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name is None:
            return id(self)
        return hash(getattr(self, id_field_name))

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}".format(self.to_dict()),
        )

    # ------------------------------------------------------------------
    # Handler dispatch (overrides HandlerMixin._handle)
    # ------------------------------------------------------------------
    @classmethod
    def _handle(cls, item: Union[Message, BaseEvent]) -> Any:
        """Process manager dispatch: load → dispatch → persist lifecycle.

        Unlike stateless event handlers, the PM loads an existing instance
        (or creates a new one) based on the event's correlation value, runs
        the handler method on that instance, then persists the resulting
        state as a transition event in the PM's own event store stream.
        """
        from protean.core.unit_of_work import UnitOfWork

        # Deserialize
        item = item.to_domain_object() if isinstance(item, Message) else item

        # Find matching handler methods
        handlers = cls._handlers.get(item.__class__.__type__) or cls._handlers.get(
            "$any"
        )
        if not handlers:
            return None

        for handler_method in handlers:
            correlate_spec = getattr(handler_method, "_correlate", None)
            is_start = getattr(handler_method, "_start", False)
            is_end = getattr(handler_method, "_end", False)

            if correlate_spec is None:
                raise ConfigurationError(
                    f"Handler `{handler_method.__name__}` in Process Manager "
                    f"`{cls.__name__}` must specify a `correlate` parameter"
                )

            correlation_value = _resolve_correlation_value(item, correlate_spec)

            # Load or create PM instance
            pm_instance = cls._load_or_create(correlation_value, is_start)
            if pm_instance is None:
                logger.debug(
                    "Process Manager `%s` with correlation `%s` not found; "
                    "skipping event `%s`",
                    cls.__name__,
                    correlation_value,
                    item.__class__.__name__,
                )
                continue

            if pm_instance._is_complete:
                logger.debug(
                    "Process Manager `%s` with correlation `%s` is already "
                    "complete; skipping event `%s`",
                    cls.__name__,
                    correlation_value,
                    item.__class__.__name__,
                )
                continue

            # Run handler within UoW, then persist transition
            with UnitOfWork():
                # Call the ORIGINAL function, bypassing the @handle wrapper's UoW
                handler_method.__wrapped__(pm_instance, item)

                if is_end:
                    pm_instance._is_complete = True

                # Persist state transition to event store
                cls._persist_transition(pm_instance, handler_method.__name__)

        return None

    # ------------------------------------------------------------------
    # Event-sourced state management
    # ------------------------------------------------------------------
    @classmethod
    def _load_or_create(
        cls, correlation_value: str, is_start: bool
    ) -> Optional["BaseProcessManager"]:
        """Load an existing PM from its event store stream, or create a new one.

        Args:
            correlation_value: The value used to identify this PM instance.
            is_start: If True and no existing PM is found, create a new instance.

        Returns:
            The loaded or newly created PM instance, or None if not found and
            not a start event.
        """
        stream_name = f"{cls.meta_.stream_category}-{correlation_value}"
        messages = current_domain.event_store.store.read(stream_name)

        if messages:
            return cls._from_transitions(messages, correlation_value)
        elif is_start:
            pm = cls.__new__(cls)
            # Initialize Pydantic internals
            object.__setattr__(pm, "__dict__", {})
            object.__setattr__(pm, "__pydantic_extra__", None)
            object.__setattr__(pm, "__pydantic_fields_set__", set())
            object.__setattr__(
                pm,
                "__pydantic_private__",
                {
                    "_version": -1,
                    "_is_complete": False,
                    "_correlation_value": correlation_value,
                },
            )

            # Initialize all model fields to defaults
            for fname, finfo in cls.model_fields.items():
                if finfo.default is not PydanticUndefined:
                    pm.__dict__[fname] = finfo.default
                elif finfo.default_factory is not None:
                    pm.__dict__[fname] = finfo.default_factory()
                else:
                    pm.__dict__[fname] = None

            # Set the id field to the correlation value
            id_field_name = getattr(cls, _ID_FIELD_NAME, None)
            if id_field_name:
                pm.__dict__[id_field_name] = correlation_value

            return pm
        else:
            return None

    @classmethod
    def _from_transitions(
        cls, messages: list, correlation_value: str
    ) -> "BaseProcessManager":
        """Reconstitute a PM from its transition events.

        Args:
            messages: List of Message objects from the PM's event store stream.
            correlation_value: The correlation value for this PM instance.

        Returns:
            The fully reconstituted PM instance.
        """
        pm = cls.__new__(cls)
        # Initialize Pydantic internals
        object.__setattr__(pm, "__dict__", {})
        object.__setattr__(pm, "__pydantic_extra__", None)
        object.__setattr__(pm, "__pydantic_fields_set__", set())
        object.__setattr__(
            pm,
            "__pydantic_private__",
            {
                "_version": -1,
                "_is_complete": False,
                "_correlation_value": correlation_value,
            },
        )

        # Initialize all model fields to None
        for fname in cls.model_fields:
            pm.__dict__[fname] = None

        # Apply each transition event in order
        for message in messages:
            domain_obj = message.to_domain_object()
            state = domain_obj.state
            for key, value in state.items():
                if key in cls.model_fields:
                    pm.__dict__[key] = value
            pm._version += 1
            if domain_obj.is_complete:
                pm._is_complete = True

        return pm

    @classmethod
    def _persist_transition(
        cls, pm_instance: "BaseProcessManager", handler_name: str
    ) -> None:
        """Persist a state transition event for the PM to its event store stream.

        Captures the PM's current field state and writes it as a transition
        event to the PM's own stream.

        Args:
            pm_instance: The PM instance whose state should be persisted.
            handler_name: The name of the handler method that triggered this transition.
        """
        # Capture current state, serializing non-JSON-safe types
        state: dict[str, Any] = {}
        for fname in cls.model_fields:
            value = getattr(pm_instance, fname, None)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, date):
                value = value.isoformat()
            state[fname] = value

        transition_cls = cls._transition_event_cls
        if transition_cls is None:
            raise ConfigurationError(
                f"Process Manager `{cls.__name__}` has no transition event class. "
                f"Ensure domain.init() has been called."
            )

        # Build metadata
        # Capture the expected_version BEFORE incrementing (matches stream's current version)
        expected_version = pm_instance._version
        pm_instance._version += 1
        stream_name = f"{cls.meta_.stream_category}-{pm_instance._correlation_value}"
        event_id = f"{stream_name}-{pm_instance._version}"

        headers = MessageHeaders(
            id=event_id,
            type=transition_cls.__type__,
            stream=stream_name,
        )

        transition_payload = {
            "state": state,
            "handler_name": handler_name,
            "is_complete": pm_instance._is_complete,
        }

        envelope = MessageEnvelope.build(transition_payload)

        domain_meta = DomainMeta(
            fqn=fqn(transition_cls),
            kind="EVENT",
            stream_category=cls.meta_.stream_category,
            version=getattr(transition_cls, "__version__", "v1"),
            sequence_id=str(pm_instance._version),
            expected_version=expected_version,
        )

        metadata = Metadata(
            headers=headers,
            envelope=envelope,
            domain=domain_meta,
        )

        # Create event with metadata and expected_version for optimistic concurrency
        transition_event = transition_cls(
            transition_payload,
            _metadata=metadata,
            _expected_version=expected_version,
        )

        # Write directly to event store
        current_domain.event_store.store.append(transition_event)


_T = TypeVar("_T")


def process_manager_factory(
    element_cls: type[_T], domain: Any, **opts: Any
) -> type[_T]:
    """Factory function to create a process manager class.

    Called during domain registration. Derives the element class from
    BaseProcessManager and configures stream categories.

    Args:
        element_cls: The user-defined process manager class.
        domain: The domain instance.
        **opts: Options passed to the decorator.

    Returns:
        The fully configured process manager class.
    """
    element_cls = derive_element_class(element_cls, BaseProcessManager, **opts)

    # Prefix stream_category with domain name
    element_cls.meta_.stream_category = (
        f"{domain.normalized_name}::{element_cls.meta_.stream_category}"
    )

    # Prefix stream_categories with domain name if not already prefixed
    prefixed: list[str] = []
    for sc in element_cls.meta_.stream_categories:
        if "::" not in sc:
            prefixed.append(f"{domain.normalized_name}::{sc}")
        else:
            prefixed.append(sc)
    element_cls.meta_.stream_categories = prefixed

    return element_cls
