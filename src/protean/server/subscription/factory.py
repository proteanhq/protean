"""Subscription factory for creating subscriptions with automatic type selection.

This module provides the SubscriptionFactory class which creates subscription instances
based on resolved configuration. It integrates with ConfigResolver to determine the
appropriate subscription type and settings.

Example:
    >>> from protean.server.subscription.factory import SubscriptionFactory
    >>> factory = SubscriptionFactory(engine)
    >>> subscription = factory.create_subscription(
    ...     handler=OrderEventHandler,
    ...     stream_category="orders"
    ... )
"""

import logging
from typing import TYPE_CHECKING, Protocol, Union, cast

from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.event_store_subscription import EventStoreSubscription
from protean.server.subscription.profiles import SubscriptionConfig, SubscriptionType
from protean.server.subscription.stream_subscription import StreamSubscription

if TYPE_CHECKING:
    from protean.core.command import BaseCommand
    from protean.core.command_handler import BaseCommandHandler
    from protean.core.event import BaseEvent
    from protean.core.event_handler import BaseEventHandler
    from protean.server import Engine
    from protean.utils.container import Options
    from protean.utils.eventing import Message
    from protean.utils.mixins import HandlerMixin

    from . import BaseSubscription


class CommandDispatcherProtocol(Protocol):
    """Structural type for the engine's ``CommandDispatcher``.

    The engine may pass a ``CommandDispatcher`` *instance* (rather than a
    handler class) to :meth:`SubscriptionFactory.create_subscription` when
    several command handlers share a stream category. The factory and the
    subscriptions treat the handler purely duck-typed, so this Protocol
    captures the surface actually consumed: an identity (``__name__``), the
    resolved subscription options (``meta_``), and the message-routing methods.
    """

    __name__: str
    __module__: str
    __qualname__: str
    meta_: "Options"

    def resolve_handler(
        self, message: "Message | BaseCommand | BaseEvent"
    ) -> "type[BaseCommandHandler] | None": ...

    def _handle(
        self, message: "Message | BaseCommand | BaseEvent"
    ) -> object | None: ...

    def handle_error(self, exc: Exception, message: "Message") -> None: ...


logger = logging.getLogger(__name__)

# The kinds of handler the factory can build a subscription for: any handler
# *class* — event/command handlers, projectors, and process managers are all
# ``HandlerMixin`` subclasses — or a duck-typed ``CommandDispatcher`` instance
# routing several command handlers on one stream.
HandlerArg = Union[
    "type[HandlerMixin]",
    "CommandDispatcherProtocol",
]


class SubscriptionFactory:
    """Factory for creating subscription instances with automatic type selection.

    The factory uses ConfigResolver to determine the appropriate subscription type
    and configuration based on handler Meta options, server configuration, and
    profile defaults.

    Attributes:
        engine: The Protean engine instance.
        config_resolver: The ConfigResolver instance for resolving configuration.

    Example:
        >>> factory = SubscriptionFactory(engine)
        >>> subscription = factory.create_subscription(
        ...     handler=OrderEventHandler,
        ...     stream_category="orders"
        ... )
        >>> isinstance(subscription, StreamSubscription)
        True
    """

    def __init__(self, engine: "Engine") -> None:
        """Initialize the SubscriptionFactory.

        Args:
            engine: The Protean engine instance.
        """
        self._engine = engine
        self._config_resolver = ConfigResolver(engine.domain)

    @property
    def engine(self) -> "Engine":
        """Get the engine instance."""
        return self._engine

    @property
    def config_resolver(self) -> ConfigResolver:
        """Get the ConfigResolver instance."""
        return self._config_resolver

    def create_subscription(
        self,
        handler: "HandlerArg",
        stream_category: str,
    ) -> "BaseSubscription":
        """Create a subscription for the given handler.

        This method resolves the subscription configuration using the priority
        hierarchy (handler Meta > server config > profile defaults > hardcoded defaults)
        and creates the appropriate subscription type.

        Args:
            handler: The event or command handler class.
            stream_category: The stream category to subscribe to.

        Returns:
            A configured subscription instance (StreamSubscription or EventStoreSubscription).

        Raises:
            ConfigurationError: If the configuration is invalid.

        Example:
            >>> subscription = factory.create_subscription(
            ...     handler=OrderEventHandler,
            ...     stream_category="orders"
            ... )
        """
        handler_name = handler.__name__

        logger.debug(
            "Creating subscription for handler '%s' on stream category '%s'",
            handler_name,
            stream_category,
        )

        # Resolve configuration
        config = self._config_resolver.resolve(handler, stream_category=stream_category)

        # Log the resolved configuration
        self._log_subscription_creation(handler_name, stream_category, config)

        # Create the appropriate subscription type
        subscription = self._create_subscription_from_config(
            handler=handler,
            stream_category=stream_category,
            config=config,
        )

        logger.debug(
            "Created %s for handler '%s' on stream '%s'",
            subscription.__class__.__name__,
            handler_name,
            stream_category,
        )

        return subscription

    def _create_subscription_from_config(
        self,
        handler: "HandlerArg",
        stream_category: str,
        config: SubscriptionConfig,
    ) -> "BaseSubscription":
        """Create a subscription instance from resolved configuration.

        Args:
            handler: The event or command handler class.
            stream_category: The stream category to subscribe to.
            config: The resolved subscription configuration.

        Returns:
            A configured subscription instance.
        """
        # ``from_config`` still declares the narrower handler-class type; the
        # engine's ``CommandDispatcher`` instance is accepted duck-typed at
        # runtime (only ``__name__``/``__module__``/``__qualname__`` and the
        # routing methods are read). Cast to the declared type at this boundary
        # until the subscription classes' signatures are widened in turn.
        handler_arg = cast("type[BaseEventHandler] | type[BaseCommandHandler]", handler)

        if config.subscription_type == SubscriptionType.STREAM:
            return StreamSubscription.from_config(
                engine=self._engine,
                stream_category=stream_category,
                handler=handler_arg,
                config=config,
            )
        else:  # EVENT_STORE
            return EventStoreSubscription.from_config(
                engine=self._engine,
                stream_category=stream_category,
                handler=handler_arg,
                config=config,
            )

    def _log_subscription_creation(
        self,
        handler_name: str,
        stream_category: str,
        config: SubscriptionConfig,
    ) -> None:
        """Log detailed information about subscription creation.

        Args:
            handler_name: The name of the handler.
            stream_category: The stream category.
            config: The resolved configuration.
        """
        subscription_type_name = config.subscription_type.value.upper()

        if config.subscription_type == SubscriptionType.STREAM:
            logger.debug(
                "Subscription configuration for '%s': "
                "type=%s, messages_per_tick=%d, blocking_timeout_ms=%d, "
                "max_retries=%d, enable_dlq=%s",
                handler_name,
                subscription_type_name,
                config.messages_per_tick,
                config.blocking_timeout_ms,
                config.max_retries,
                config.enable_dlq,
            )
        else:  # EVENT_STORE
            logger.debug(
                "Subscription configuration for '%s': "
                "type=%s, messages_per_tick=%d, position_update_interval=%d, "
                "origin_stream=%s",
                handler_name,
                subscription_type_name,
                config.messages_per_tick,
                config.position_update_interval,
                config.origin_stream,
            )


__all__ = ["SubscriptionFactory"]
