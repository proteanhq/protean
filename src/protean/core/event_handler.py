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
from typing import Any, Optional, Union

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin

logger = logging.getLogger(__name__)


class BaseEventHandler(Element, HandlerMixin, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers.

    Event handlers process domain events asynchronously. They can be configured
    with subscription settings to control message consumption behavior.

    Meta Options:
        part_of: The aggregate this handler is associated with.
        source_stream: Optional source stream filter for origin filtering.
        stream_category: The stream category to subscribe to. Defaults to the
            aggregate's stream category if part_of is specified.
        subscription_type: The subscription type to use (STREAM or EVENT_STORE).
            When None, uses the domain's default subscription type.
        subscription_profile: A predefined configuration profile
            (PRODUCTION, FAST, BATCH, DEBUG, PROJECTION).
        subscription_config: A dictionary of custom configuration overrides
            that take precedence over profile defaults.

    Configuration Priority (highest to lowest):
        1. Handler Meta subscription_config
        2. Handler Meta subscription_profile
        3. Handler Meta subscription_type
        4. Server-level handler-specific config
        5. Server-level defaults
        6. Profile defaults
        7. Hardcoded defaults

    Example:
        >>> @domain.event_handler(
        ...     part_of=Order,
        ...     subscription_profile=SubscriptionProfile.PRODUCTION,
        ...     subscription_config={"messages_per_tick": 50},
        ... )
        ... class OrderEventHandler(BaseEventHandler):
        ...     @handle(OrderPlaced)
        ...     def handle_order_placed(self, event):
        ...         pass
    """

    element_type = DomainObjects.EVENT_HANDLER

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseEventHandler":
        if cls is BaseEventHandler:
            raise NotSupportedError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Optional[Union[str, dict]]]]:
        part_of = (
            getattr(cls.meta_, "part_of") if hasattr(cls.meta_, "part_of") else None
        )

        return [
            ("part_of", part_of),
            ("source_stream", None),
            ("stream_category", part_of.meta_.stream_category if part_of else None),
            # Subscription configuration options
            ("subscription_type", None),  # SubscriptionType enum or None for default
            ("subscription_profile", None),  # SubscriptionProfile enum or None
            ("subscription_config", {}),  # Dict of custom config overrides
        ]


def event_handler_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **opts)

    if not (element_cls.meta_.part_of or element_cls.meta_.stream_category):
        raise IncorrectUsageError(
            f"Event Handler `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
        )

    return element_cls
