"""Event Handler module for processing domain events.

This module provides the base class for event handlers, which are responsible
for reacting to domain events. Event handlers can be configured with subscription
settings to control how they consume messages.

Example:
    Basic event handler associated with an aggregate::

        @domain.event_handler(part_of=Order)
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def handle_order_placed(self, event: OrderPlaced) -> None:
                # Handle the event
                pass

    Event handler with subscription configuration::

        from protean.server.subscription.profiles import (
            SubscriptionProfile,
            SubscriptionType,
        )

        @domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def handle_order_placed(self, event: OrderPlaced) -> None:
                pass

    Projection builder with EVENT_STORE subscription::

        @domain.event_handler(
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
            subscription_profile=SubscriptionProfile.PROJECTION,
        )
        class ProjectionBuilder(BaseEventHandler):
            @handle(OrderPlaced)
            def handle_order_placed(self, event: OrderPlaced) -> None:
                # Build projection
                pass

    Custom subscription configuration overrides::

        @domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={
                "messages_per_tick": 50,
                "max_retries": 5,
            },
        )
        class CustomOrderHandler(BaseEventHandler):
            pass
"""

import logging
from typing import Any, ClassVar, TypeVar

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, _derive_element_class
from protean.utils.container import DerivedDefault, Element, OptionsMixin
from protean.utils.mixins import HandlerMixin

logger = logging.getLogger(__name__)


class BaseEventHandler(Element, HandlerMixin, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers.

    Event handlers process domain events asynchronously. They can be configured
    with subscription settings to control message consumption behavior.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate this handler is associated with. |
    | ``source_stream`` | ``str`` | Optional source stream filter for origin filtering. |
    | ``stream_category`` | ``str`` | The stream category to subscribe to. Defaults to aggregate's category. |
    | ``subscription_type`` | ``str`` | The subscription type (STREAM or EVENT_STORE). |
    | ``subscription_profile`` | ``str`` | A predefined profile (PRODUCTION, FAST, BATCH, DEBUG, PROJECTION). |
    | ``subscription_config`` | ``dict`` | Custom configuration overrides that take precedence over profile defaults. |

    Configuration Priority (highest to lowest):
        1. Handler Meta subscription_config
        2. Handler Meta subscription_profile
        3. Handler Meta subscription_type
        4. Server-level handler-specific config
        5. Server-level defaults
        6. Profile defaults
        7. Hardcoded defaults

    Example::

        @domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={"messages_per_tick": 50},
        )
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def handle_order_placed(self, event):
                pass
    """

    element_type = DomainObjects.EVENT_HANDLER

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseEventHandler":
        if cls is BaseEventHandler:
            raise NotSupportedError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("part_of", None),
        ("source_stream", None),
        # ``stream_category`` is derived from ``part_of``. When ``part_of`` is a
        # string reference, the aggregate is not yet resolved, so its
        # stream_category cannot be derived here; the ElementResolver fills it
        # in once the reference is resolved. This default is only consulted when
        # ``stream_category`` is unset, by which point ``part_of`` has already
        # been resolved onto ``meta_``.
        (
            "stream_category",
            DerivedDefault(
                lambda cls: (
                    cls.meta_.part_of.meta_.stream_category
                    if getattr(cls.meta_, "part_of", None)
                    and not isinstance(cls.meta_.part_of, str)
                    else None
                )
            ),
        ),
        # Transient-failure retry policy. ``retries`` (int) sets the max
        # retry attempts on transient exceptions and overrides the
        # domain-level ``server.transient_retry`` config; ``None`` defers to
        # it. ``backoff`` selects the delay strategy ("exponential" |
        # "linear" | "fixed"). ``retry_exceptions`` overrides which
        # exception types are treated as transient (classes or dotted paths).
        ("retries", None),
        ("backoff", None),
        ("retry_exceptions", None),
        # Subscription configuration options
        ("subscription_type", None),  # SubscriptionType enum or None for default
        ("subscription_profile", None),  # SubscriptionProfile enum or None
        ("subscription_config", {}),  # Dict of custom config overrides
    ]


_T = TypeVar("_T", bound=OptionsMixin)


def event_handler_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = _derive_element_class(element_cls, BaseEventHandler, **opts)

    if not (element_cls.meta_.part_of or element_cls.meta_.stream_category):
        raise IncorrectUsageError(
            f"Event Handler `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
