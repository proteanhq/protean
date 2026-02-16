"""Command Handler module for processing domain commands.

This module provides the base class for command handlers, which are responsible
for processing domain commands and coordinating state changes. Command handlers
can be configured with subscription settings to control how they consume messages.

Example:
    Basic command handler associated with an aggregate::

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler(BaseCommandHandler):
            @handle(PlaceOrder)
            def handle_place_order(self, command: PlaceOrder) -> None:
                # Handle the command
                pass

    Command handler with subscription configuration::

        from protean.server.subscription.profiles import (
            SubscriptionProfile,
            SubscriptionType,
        )

        @domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderCommandHandler(BaseCommandHandler):
            @handle(PlaceOrder)
            def handle_place_order(self, command: PlaceOrder) -> None:
                pass

    Custom subscription configuration overrides::

        @domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={
                "messages_per_tick": 50,
                "max_retries": 5,
            },
        )
        class CustomOrderCommandHandler(BaseCommandHandler):
            pass
"""

from typing import Any, Optional, TypeVar, Union

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin


class BaseCommandHandler(Element, HandlerMixin, OptionsMixin):
    """Base Command Handler class that should be implemented by all Domain CommandHandlers.

    Command handlers process domain commands asynchronously. They can be configured
    with subscription settings to control message consumption behavior.

    Meta Options:
        part_of: The aggregate this handler is associated with. Required.
        stream_category: Read-only. Always derived from the associated aggregate's
            stream category. Cannot be overridden by the user.
        subscription_type: The subscription type to use (STREAM or EVENT_STORE).
            When None, uses the domain's default subscription type.
        subscription_profile: A predefined configuration profile
            (PRODUCTION, FAST, BATCH, DEBUG, PROJECTION).
        subscription_config: A dictionary of custom configuration overrides
            that take precedence over profile defaults.

    Note:
        Unlike event handlers, command handlers cannot have their stream_category
        explicitly set. It is always derived from the aggregate specified in part_of.

    Configuration Priority (highest to lowest):
        1. Handler Meta subscription_config
        2. Handler Meta subscription_profile
        3. Handler Meta subscription_type
        4. Server-level handler-specific config
        5. Server-level defaults
        6. Profile defaults
        7. Hardcoded defaults

    Example:
        >>> @domain.command_handler(
        ...     part_of=Order,
        ...     subscription_profile=SubscriptionProfile.PRODUCTION,
        ...     subscription_config={"messages_per_tick": 50},
        ... )
        ... class OrderCommandHandler(BaseCommandHandler):
        ...     @handle(PlaceOrder)
        ...     def handle_place_order(self, command):
        ...         pass
    """

    element_type = DomainObjects.COMMAND_HANDLER

    @classmethod
    def _default_options(cls) -> list[tuple[str, Optional[Union[str, dict]]]]:
        part_of = (
            getattr(cls.meta_, "part_of") if hasattr(cls.meta_, "part_of") else None
        )

        return [
            ("part_of", part_of),
            ("stream_category", None),  # Will be set by command_handler_factory
            # Subscription configuration options
            ("subscription_type", None),  # SubscriptionType enum or None for default
            ("subscription_profile", None),  # SubscriptionProfile enum or None
            ("subscription_config", {}),  # Dict of custom config overrides
        ]

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseCommandHandler":
        if cls is BaseCommandHandler:
            raise NotSupportedError("BaseCommandHandler cannot be instantiated")
        return super().__new__(cls)


_T = TypeVar("_T")


def command_handler_factory(
    element_cls: type[_T], domain: Any, **opts: Any
) -> type[_T]:
    element_cls = derive_element_class(element_cls, BaseCommandHandler, **opts)

    if not (element_cls.meta_.part_of):
        raise IncorrectUsageError(
            f"Command Handler `{element_cls.__name__}` needs to be associated with an Aggregate"
        )

    # Always derive stream_category from the aggregate - cannot be overridden
    element_cls.meta_.stream_category = (
        f"{element_cls.meta_.part_of.meta_.stream_category}:command"
    )

    return element_cls
