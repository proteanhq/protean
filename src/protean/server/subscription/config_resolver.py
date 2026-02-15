"""Configuration resolution for subscription settings.

This module provides the ConfigResolver class which resolves subscription configuration
from multiple sources with a defined priority hierarchy.

Configuration Priority (highest to lowest):
    1. Handler Meta subscription_config dict
    2. Handler Meta subscription_profile
    3. Handler Meta subscription_type
    4. Server-level handler-specific config (server.subscriptions.HandlerName)
    5. Server-level defaults (server.default_subscription_type, server.default_subscription_profile)
    6. Profile defaults
    7. Hardcoded defaults

Example:
    >>> from protean.server.subscription.config_resolver import ConfigResolver
    >>> resolver = ConfigResolver(domain)
    >>> config = resolver.resolve(handler_cls)
    >>> config.subscription_type
    <SubscriptionType.STREAM: 'stream'>
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Optional, Type

from protean.server.subscription.profiles import (
    DEFAULT_CONFIG,
    PROFILE_DEFAULTS,
    SubscriptionConfig,
    SubscriptionProfile,
    SubscriptionType,
)

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.utils.mixins import HandlerMixin

logger = logging.getLogger(__name__)


class ConfigResolver:
    """Resolves subscription configuration from multiple sources.

    This class implements configuration resolution with a priority hierarchy,
    allowing configuration to be specified at multiple levels while maintaining
    clear precedence rules.

    Attributes:
        domain: The domain instance containing server configuration.

    Example:
        >>> resolver = ConfigResolver(domain)
        >>> config = resolver.resolve(OrderEventHandler)
        >>> print(config.messages_per_tick)
        100
    """

    def __init__(self, domain: "Domain") -> None:
        """Initialize the ConfigResolver.

        Args:
            domain: The domain instance containing server configuration.
        """
        self._domain = domain

    @property
    def server_config(self) -> dict[str, Any]:
        """Get the server configuration from the domain."""
        return self._domain.config.get("server", {})

    def resolve(
        self,
        handler_cls: Type["HandlerMixin"],
        *,
        stream_category: Optional[str] = None,
    ) -> SubscriptionConfig:
        """Resolve the final subscription configuration for a handler.

        This method implements the configuration priority hierarchy by merging
        configurations from multiple sources. Profile expansion inherits the
        priority of the level where the profile was specified.

        Args:
            handler_cls: The handler class to resolve configuration for.
            stream_category: Optional stream category override.

        Returns:
            A fully resolved SubscriptionConfig instance.

        Example:
            >>> config = resolver.resolve(OrderEventHandler)
            >>> config.subscription_type
            <SubscriptionType.STREAM: 'stream'>
        """
        handler_name = handler_cls.__name__

        logger.debug(
            "Resolving subscription configuration for handler '%s'", handler_name
        )

        # Get configs from each level and extract profiles
        server_defaults = self._get_server_defaults()
        handler_server_config = self._get_handler_server_config(handler_name)
        handler_meta_config = self._get_handler_meta_config(handler_cls)

        # Extract profiles from each level (pop to remove from config dicts)
        server_default_profile = (
            server_defaults.pop("profile", None) if server_defaults else None
        )
        handler_server_profile = (
            handler_server_config.pop("profile", None)
            if handler_server_config
            else None
        )
        handler_meta_profile = (
            handler_meta_config.pop("profile", None) if handler_meta_config else None
        )

        # Start with hardcoded defaults (Priority 7)
        resolved: dict[str, Any] = dict(DEFAULT_CONFIG)
        logger.debug("Starting with hardcoded defaults: %s", resolved)

        # Priority 6: Apply server default profile (lowest profile priority)
        # Only if no higher-priority profile is specified
        if (
            server_default_profile
            and not handler_server_profile
            and not handler_meta_profile
        ):
            profile_defaults = PROFILE_DEFAULTS.get(
                self._resolve_profile(server_default_profile), {}
            )
            resolved = self._merge_configs(resolved, profile_defaults)
            logger.debug(
                "After applying server default profile '%s': %s",
                server_default_profile,
                resolved,
            )

        # Priority 5: Apply server-level defaults
        if server_defaults:
            resolved = self._merge_configs(resolved, server_defaults)
            logger.debug("After applying server defaults: %s", resolved)

        # Priority 4: Apply server-level handler-specific config
        # If handler server config has a profile, expand it first (unless handler Meta has profile)
        if handler_server_profile and not handler_meta_profile:
            profile_defaults = PROFILE_DEFAULTS.get(
                self._resolve_profile(handler_server_profile), {}
            )
            resolved = self._merge_configs(resolved, profile_defaults)
            logger.debug(
                "After applying handler server profile '%s': %s",
                handler_server_profile,
                resolved,
            )

        if handler_server_config:
            resolved = self._merge_configs(resolved, handler_server_config)
            logger.debug("After applying handler-specific server config: %s", resolved)

        # Priority 2-3: Apply handler Meta profile (high priority, overrides server config)
        if handler_meta_profile:
            profile_defaults = PROFILE_DEFAULTS.get(
                self._resolve_profile(handler_meta_profile), {}
            )
            resolved = self._merge_configs(resolved, profile_defaults)
            logger.debug(
                "After applying handler Meta profile '%s': %s",
                handler_meta_profile,
                resolved,
            )

        # Priority 1: Apply handler Meta configuration (highest priority)
        if handler_meta_config:
            resolved = self._merge_configs(resolved, handler_meta_config)
            logger.debug("After applying handler Meta config: %s", resolved)

        # Resolve subscription_type to enum
        subscription_type = self._resolve_subscription_type(
            resolved.get("subscription_type", DEFAULT_CONFIG["subscription_type"])
        )
        resolved["subscription_type"] = subscription_type

        # Sanitize config for subscription type compatibility
        self._sanitize_for_subscription_type(resolved)

        # Log warning if using EVENT_STORE in production
        if subscription_type == SubscriptionType.EVENT_STORE:
            self._log_event_store_warning(handler_name)

        # Create the final SubscriptionConfig
        config = self._create_subscription_config(resolved)

        logger.debug(
            "Final resolved configuration for '%s': %s", handler_name, config.to_dict()
        )

        return config

    def _get_server_defaults(self) -> dict[str, Any]:
        """Extract server-level default configuration.

        Returns:
            Dictionary of server-level defaults.
        """
        config: dict[str, Any] = {}
        server = self.server_config

        # Extract default subscription type
        default_type = server.get("default_subscription_type")
        if default_type is not None:
            config["subscription_type"] = default_type

        # Extract default subscription profile
        default_profile = server.get("default_subscription_profile")
        if default_profile is not None:
            config["profile"] = default_profile

        # Extract common server settings
        for key in ["messages_per_tick", "tick_interval"]:
            if key in server:
                config[key] = server[key]

        # Extract stream subscription settings
        stream_config = server.get("stream_subscription", {})
        for key in [
            "blocking_timeout_ms",
            "max_retries",
            "retry_delay_seconds",
            "enable_dlq",
        ]:
            if key in stream_config:
                config[key] = stream_config[key]

        # Extract event store subscription settings
        event_store_config = server.get("event_store_subscription", {})
        for key in ["position_update_interval"]:
            if key in event_store_config:
                config[key] = event_store_config[key]

        return config

    def _get_handler_server_config(self, handler_name: str) -> dict[str, Any]:
        """Get server-level configuration specific to a handler.

        Args:
            handler_name: The name of the handler class.

        Returns:
            Dictionary of handler-specific server configuration.
        """
        subscriptions = self.server_config.get("subscriptions", {})
        return dict(subscriptions.get(handler_name, {}))

    def _get_handler_meta_config(
        self, handler_cls: Type["HandlerMixin"]
    ) -> dict[str, Any]:
        """Extract subscription configuration from handler's Meta options.

        Args:
            handler_cls: The handler class to extract configuration from.

        Returns:
            Dictionary of handler Meta configuration.
        """
        config: dict[str, Any] = {}

        # Get meta_ attribute if it exists
        meta = getattr(handler_cls, "meta_", None)
        if meta is None:
            return config

        # Extract subscription_type
        subscription_type = getattr(meta, "subscription_type", None)
        if subscription_type is not None:
            config["subscription_type"] = subscription_type

        # Extract subscription_profile
        subscription_profile = getattr(meta, "subscription_profile", None)
        if subscription_profile is not None:
            config["profile"] = subscription_profile

        # Extract subscription_config dict and merge it
        subscription_config = getattr(meta, "subscription_config", None)
        if subscription_config:
            config.update(subscription_config)

        # Extract stream_category if present
        stream_category = getattr(meta, "stream_category", None)
        if stream_category is not None:
            config["stream_category"] = stream_category

        # Extract source_stream / origin_stream if present
        source_stream = getattr(meta, "source_stream", None)
        if source_stream is not None:
            config["origin_stream"] = source_stream

        return config

    def _merge_configs(
        self, base: dict[str, Any], override: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge two configuration dictionaries.

        Values from override take precedence over base. Only non-None values
        from override are applied.

        Args:
            base: The base configuration dictionary.
            override: The override configuration dictionary.

        Returns:
            A new merged configuration dictionary.
        """
        result = dict(base)
        for key, value in override.items():
            if value is not None:
                result[key] = value
        return result

    def _resolve_profile(
        self, profile: str | SubscriptionProfile
    ) -> SubscriptionProfile:
        """Resolve a profile from string or enum.

        Args:
            profile: Profile name as string or SubscriptionProfile enum.

        Returns:
            The resolved SubscriptionProfile enum value.
        """
        if isinstance(profile, SubscriptionProfile):
            return profile

        if isinstance(profile, str):
            try:
                return SubscriptionProfile(profile.lower())
            except ValueError:
                logger.warning(
                    "Unknown subscription profile '%s', using defaults", profile
                )
                # Return a default-like behavior by returning PRODUCTION
                # But we won't apply its defaults since the profile lookup will fail
                return SubscriptionProfile.PRODUCTION

        return SubscriptionProfile.PRODUCTION

    def _resolve_subscription_type(
        self, sub_type: str | SubscriptionType
    ) -> SubscriptionType:
        """Resolve a subscription type from string or enum.

        Args:
            sub_type: Subscription type as string or SubscriptionType enum.

        Returns:
            The resolved SubscriptionType enum value.
        """
        if isinstance(sub_type, SubscriptionType):
            return sub_type

        if isinstance(sub_type, str):
            try:
                return SubscriptionType(sub_type.lower())
            except ValueError:
                logger.warning(
                    "Unknown subscription type '%s', defaulting to EVENT_STORE",
                    sub_type,
                )
                return SubscriptionType.EVENT_STORE

        return SubscriptionType.EVENT_STORE

    def _sanitize_for_subscription_type(self, resolved: dict[str, Any]) -> None:
        """Sanitize configuration for subscription type compatibility.

        Adjusts configuration values that are incompatible with the resolved
        subscription type. Modifies the dictionary in place.

        Args:
            resolved: The configuration dictionary to sanitize.
        """
        subscription_type = resolved.get("subscription_type")

        if subscription_type == SubscriptionType.EVENT_STORE:
            # EVENT_STORE does not support DLQ
            if resolved.get("enable_dlq"):
                resolved["enable_dlq"] = False
                logger.debug("Disabled enable_dlq for EVENT_STORE subscription type")

    def _log_event_store_warning(self, handler_name: str) -> None:
        """Log a warning when using EVENT_STORE subscription type in production.

        Args:
            handler_name: Name of the handler for logging context.
        """
        if self._is_production_environment():
            logger.warning(
                "Handler '%s' is using EventStoreSubscription in production. "
                "For production workloads, consider using StreamSubscription which provides: "
                "transactional outbox pattern, automatic retry mechanisms, "
                "dead letter queue, and horizontal scaling with consumer groups.",
                handler_name,
            )

    @staticmethod
    def _is_production_environment() -> bool:
        """Detect if running in a production environment.

        Checks common environment variables used to indicate production:
        - PROTEAN_ENV
        - PYTHON_ENV
        - ENV
        - ENVIRONMENT

        Returns:
            True if any environment variable indicates production.
        """
        env_vars = ["PROTEAN_ENV", "PYTHON_ENV", "ENV", "ENVIRONMENT"]
        production_values = {"production", "prod", "prd"}

        for var in env_vars:
            value = os.environ.get(var, "").lower()
            if value in production_values:
                return True

        return False

    def _create_subscription_config(
        self, resolved: dict[str, Any]
    ) -> SubscriptionConfig:
        """Create a SubscriptionConfig from resolved configuration.

        Args:
            resolved: The fully resolved configuration dictionary.

        Returns:
            A SubscriptionConfig instance.
        """
        # Filter to only known SubscriptionConfig fields
        known_fields = {
            "subscription_type",
            "messages_per_tick",
            "tick_interval",
            "blocking_timeout_ms",
            "max_retries",
            "retry_delay_seconds",
            "enable_dlq",
            "position_update_interval",
            "origin_stream",
        }

        config_kwargs = {
            key: value for key, value in resolved.items() if key in known_fields
        }

        return SubscriptionConfig(**config_kwargs)


__all__ = ["ConfigResolver"]
