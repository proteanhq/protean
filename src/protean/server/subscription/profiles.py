"""Subscription configuration profiles system.

This module provides a configuration profile system for subscriptions, allowing users to
easily configure their subscriptions with sensible defaults while maintaining the ability
to customize specific options.

The profile system follows a priority hierarchy:
1. Explicit parameters (highest priority)
2. Profile defaults
3. Hardcoded defaults (lowest priority)
"""

import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from protean.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class SubscriptionType(Enum):
    """Enumeration of available subscription types.

    Attributes:
        STREAM: Stream-based subscription using Redis Streams with blocking reads.
            This is the production-recommended subscription type that provides:
            - Transactional outbox pattern
            - Automatic retry mechanisms
            - Dead letter queue support
            - Horizontal scaling with consumer groups

        EVENT_STORE: Event store subscription reading directly from the event store.
            This is suited for specialized use cases like:
            - Projections
            - Event replay
            - Development/debugging
            - Single-worker scenarios
    """

    STREAM = "stream"
    EVENT_STORE = "event_store"


class CircuitBreakerState(Enum):
    """States of a subscription's circuit breaker.

    The breaker counts consecutive handler-outcome failures per subscription
    and gates reads when a downstream dependency looks unhealthy.

    Attributes:
        CLOSED: Normal operation. Reads and processing proceed; each failure
            increments the counter, each success resets it to zero.
        OPEN: Reads are paused. Pending messages stay in the stream/PEL for
            redelivery. On the next poll turn after
            ``circuit_breaker_reset_seconds`` has elapsed, the breaker moves to
            HALF_OPEN (the transition is lazy, driven by the poll loop, not a
            timer).
        HALF_OPEN: A single probe message is allowed through. A successful
            probe closes the breaker; a failing probe re-opens it and restarts
            the reset timer.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class SubscriptionProfile(Enum):
    """Pre-configured subscription profiles for common use cases.

    Each profile provides sensible defaults optimized for specific scenarios.
    Users can override individual settings while using a profile as a base.

    Attributes:
        PRODUCTION: Optimized for production workloads with reliability guarantees.
            - Higher batch sizes for throughput
            - DLQ enabled for error handling
            - Standard retry settings

        FAST: Optimized for low-latency processing.
            - Smaller batch sizes for quicker processing
            - Shorter blocking timeouts
            - Minimal retry delays

        BATCH: Optimized for high-throughput batch processing.
            - Large batch sizes
            - Higher blocking timeouts
            - Aggressive batching

        DEBUG: Optimized for development and debugging.
            - Small batch sizes for easier debugging
            - Verbose logging friendly
            - Quick iteration

        PROJECTION: Optimized for building read models and projections.
            - Uses EVENT_STORE subscription type
            - Processes from event store directly
            - Suitable for catch-up subscriptions
    """

    PRODUCTION = "production"
    FAST = "fast"
    BATCH = "batch"
    DEBUG = "debug"
    PROJECTION = "projection"


# Profile default configurations
# Each profile defines sensible defaults that can be overridden
PROFILE_DEFAULTS: dict[SubscriptionProfile, dict[str, Any]] = {
    SubscriptionProfile.PRODUCTION: {
        "subscription_type": SubscriptionType.STREAM,
        "messages_per_tick": 100,
        "tick_interval": 0,
        # Stream subscription options
        "blocking_timeout_ms": 5000,
        "max_retries": 3,
        "retry_delay_seconds": 1,
        "enable_dlq": True,
        # Event store subscription options
        "position_update_interval": 10,
        # Optional filtering
        "origin_stream": None,
        # Circuit breaker options
        "circuit_breaker_threshold": 10,
        "circuit_breaker_reset_seconds": 60,
    },
    SubscriptionProfile.FAST: {
        "subscription_type": SubscriptionType.STREAM,
        "messages_per_tick": 10,
        "tick_interval": 0,
        # Stream subscription options
        "blocking_timeout_ms": 100,
        "max_retries": 2,
        "retry_delay_seconds": 0,
        "enable_dlq": True,
        # Event store subscription options
        "position_update_interval": 5,
        # Optional filtering
        "origin_stream": None,
        # Circuit breaker options
        "circuit_breaker_threshold": 10,
        "circuit_breaker_reset_seconds": 60,
    },
    SubscriptionProfile.BATCH: {
        "subscription_type": SubscriptionType.STREAM,
        "messages_per_tick": 500,
        "tick_interval": 0,
        # Stream subscription options
        "blocking_timeout_ms": 10000,
        "max_retries": 5,
        "retry_delay_seconds": 2,
        "enable_dlq": True,
        # Event store subscription options
        "position_update_interval": 50,
        # Optional filtering
        "origin_stream": None,
        # Circuit breaker options
        "circuit_breaker_threshold": 10,
        "circuit_breaker_reset_seconds": 60,
    },
    SubscriptionProfile.DEBUG: {
        "subscription_type": SubscriptionType.STREAM,
        "messages_per_tick": 1,
        "tick_interval": 1,
        # Stream subscription options
        "blocking_timeout_ms": 1000,
        "max_retries": 1,
        "retry_delay_seconds": 0,
        "enable_dlq": False,
        # Event store subscription options
        "position_update_interval": 1,
        # Optional filtering
        "origin_stream": None,
        # Circuit breaker options
        "circuit_breaker_threshold": 10,
        "circuit_breaker_reset_seconds": 60,
    },
    SubscriptionProfile.PROJECTION: {
        "subscription_type": SubscriptionType.EVENT_STORE,
        "messages_per_tick": 100,
        "tick_interval": 0,
        # Stream subscription options (not used but included for completeness)
        "blocking_timeout_ms": 5000,
        "max_retries": 3,
        "retry_delay_seconds": 1,
        "enable_dlq": False,  # Not applicable for event store
        # Event store subscription options
        "position_update_interval": 10,
        # Optional filtering
        "origin_stream": None,
        # Circuit breaker options
        "circuit_breaker_threshold": 10,
        "circuit_breaker_reset_seconds": 60,
    },
}

# Hardcoded defaults used when no profile is specified.
# tick_interval is 0 because the default subscription type (STREAM) uses
# blocking reads for pacing, making a tick-based sleep unnecessary.
DEFAULT_CONFIG: dict[str, Any] = {
    "subscription_type": SubscriptionType.STREAM,
    "messages_per_tick": 10,
    "tick_interval": 0,
    "blocking_timeout_ms": 5000,
    "max_retries": 3,
    "retry_delay_seconds": 1,
    "enable_dlq": True,
    "position_update_interval": 10,
    "origin_stream": None,
    "circuit_breaker_threshold": 10,
    "circuit_breaker_reset_seconds": 60,
}

# Built-in profile names, normalized to lowercase. These are reserved: a custom
# profile may not reuse one of these names.
BUILTIN_PROFILE_NAMES: frozenset[str] = frozenset(p.value for p in SubscriptionProfile)

# Fields a custom profile may set, derived from the built-in defaults schema so
# the allow-list can't drift from the fields the resolver actually applies.
# ``inherits`` is a meta-key handled separately, not a config field.
PROFILE_FIELDS: frozenset[str] = frozenset(DEFAULT_CONFIG)


def build_profile_registry(
    custom_profiles: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a string-keyed profile registry.

    The registry is seeded with the built-in profiles (keyed by their lowercase
    ``.value`` names) and extended with validated custom profiles read from the
    ``[server.profiles.<name>]`` sections of ``domain.toml``.

    A custom profile is a dict of subscription config overrides. It may set
    ``inherits = "<built-in>"`` to base its defaults on a built-in profile;
    without ``inherits`` the base is :data:`DEFAULT_CONFIG`. Validation is
    fail-fast: a reserved built-in name, an unknown field, or an ``inherits``
    target that is not a built-in each raises :class:`ConfigurationError`.

    Args:
        custom_profiles: The raw ``[server.profiles]`` mapping (profile name to
            its config dict). ``None`` or empty yields just the built-ins.

    Returns:
        A mapping of profile name to its resolved defaults dict. Built-in entries
        are fresh copies, so callers never mutate :data:`PROFILE_DEFAULTS`.

    Raises:
        ConfigurationError: If a custom profile shadows a built-in name, sets an
            unknown field, or inherits from anything other than a built-in.
    """
    # Seed with built-ins. Copy each defaults dict so the returned registry never
    # aliases (and so a later merge never mutates) the shared PROFILE_DEFAULTS.
    registry: dict[str, dict[str, Any]] = {
        profile.value: dict(defaults) for profile, defaults in PROFILE_DEFAULTS.items()
    }

    if not custom_profiles:
        return registry

    # The profiles slot must itself be a table of named sections. A mis-typed
    # scalar (e.g. ``profiles = "x"``) is truthy and would otherwise blow up on
    # ``.items()`` with a raw AttributeError.
    if not isinstance(custom_profiles, Mapping):
        raise ConfigurationError(
            f"[server.profiles] must be a table of named profile sections, got "
            f"{type(custom_profiles).__name__}."
        )

    for raw_name, raw_config in custom_profiles.items():
        # TOML keys are always strings, but a programmatic config could use a
        # non-string key; normalize only after confirming it is a string.
        if not isinstance(raw_name, str):
            raise ConfigurationError(
                f"Custom subscription profile names must be strings, got "
                f"{type(raw_name).__name__} ({raw_name!r})."
            )
        name = raw_name.lower()

        if name in BUILTIN_PROFILE_NAMES:
            raise ConfigurationError(
                f"Custom subscription profile '{raw_name}' shadows a built-in "
                f"profile name. Built-in names are reserved: "
                f"{', '.join(sorted(BUILTIN_PROFILE_NAMES))}."
            )

        if not isinstance(raw_config, dict):
            raise ConfigurationError(
                f"Custom subscription profile '{raw_name}' must be a table of "
                f"config overrides, got {type(raw_config).__name__}."
            )

        overrides = dict(raw_config)
        inherits = overrides.pop("inherits", None)

        # Inheritance is a single level onto a built-in base. A custom or self
        # name is not a built-in, so this rule also rejects the only reachable
        # cycle shapes (self-inherit, custom -> custom).
        if inherits is not None:
            # ``inherits`` must name a built-in. A non-string value (TOML array
            # or inline table) is not a name; catch it here so the membership
            # test below never sees an unhashable value.
            if not isinstance(inherits, str):
                raise ConfigurationError(
                    f"Custom subscription profile '{raw_name}' has a non-string "
                    f"'inherits' value ({inherits!r}). 'inherits' must name a "
                    f"built-in profile: "
                    f"{', '.join(sorted(BUILTIN_PROFILE_NAMES))}."
                )
            inherits_name = inherits.lower()
            if inherits_name not in BUILTIN_PROFILE_NAMES:
                raise ConfigurationError(
                    f"Custom subscription profile '{raw_name}' inherits from "
                    f"'{inherits}', which is not a built-in profile. Inheritance "
                    f"is a single level onto a built-in base: "
                    f"{', '.join(sorted(BUILTIN_PROFILE_NAMES))}."
                )
            base = dict(registry[inherits_name])
        else:
            base = dict(DEFAULT_CONFIG)

        # Field names are always strings from TOML, but a programmatic config
        # could use a non-string key. Catch it here so the unknown-field check
        # below never has to ``sorted()``/``join()`` a mix of strings and
        # other types, which would raise a raw TypeError instead of a clean
        # ConfigurationError.
        non_string_fields = [key for key in overrides if not isinstance(key, str)]
        if non_string_fields:
            raise ConfigurationError(
                f"Custom subscription profile '{raw_name}' has non-string "
                f"field name(s): {non_string_fields!r}. Field names must be "
                "strings."
            )

        unknown = set(overrides) - PROFILE_FIELDS
        if unknown:
            raise ConfigurationError(
                f"Custom subscription profile '{raw_name}' has unknown "
                f"field(s): {', '.join(sorted(unknown))}. Allowed fields: "
                f"{', '.join(sorted(PROFILE_FIELDS))}."
            )

        # Skip None overrides so a None value means "keep the inherited (or
        # default) value" rather than silently reverting the field to the
        # hardcoded default once the resolver's _merge_configs drops it. This
        # matches how _merge_configs treats None overrides downstream.
        base.update(
            {key: value for key, value in overrides.items() if value is not None}
        )
        registry[name] = base

    return registry


@dataclass
class SubscriptionConfig:
    """Configuration object for subscriptions.

    This dataclass encapsulates all configuration options for both StreamSubscription
    and EventStoreSubscription. Not all options apply to both subscription types;
    validation ensures only applicable options are used.

    Attributes:
        subscription_type: The type of subscription (STREAM or EVENT_STORE).
        messages_per_tick: Number of messages to process per tick.
        tick_interval: Interval between processing ticks in seconds.
        blocking_timeout_ms: Timeout for blocking reads in milliseconds (STREAM only).
        max_retries: Maximum retry attempts before moving to DLQ (STREAM only).
        retry_delay_seconds: Delay between retries in seconds (STREAM only).
        enable_dlq: Whether to enable dead letter queue (STREAM only).
        position_update_interval: How often to persist position (EVENT_STORE only).
        origin_stream: Optional filter for origin stream name.
        circuit_breaker_threshold: Consecutive handler failures that trip the
            circuit breaker OPEN (STREAM only).
        circuit_breaker_reset_seconds: Seconds an OPEN breaker waits before it
            allows a single HALF_OPEN probe (STREAM only).

    Example:
        >>> config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        >>> config.messages_per_tick
        100

        >>> config = SubscriptionConfig.from_profile(
        ...     SubscriptionProfile.PRODUCTION,
        ...     messages_per_tick=50  # Override default
        ... )
        >>> config.messages_per_tick
        50

        >>> config = SubscriptionConfig.from_dict({
        ...     "profile": "fast",
        ...     "enable_dlq": False
        ... })
        >>> config.subscription_type
        <SubscriptionType.STREAM: 'stream'>
    """

    subscription_type: SubscriptionType = field(
        default_factory=lambda: DEFAULT_CONFIG["subscription_type"]
    )
    messages_per_tick: int = field(
        default_factory=lambda: DEFAULT_CONFIG["messages_per_tick"]
    )
    tick_interval: int = field(default_factory=lambda: DEFAULT_CONFIG["tick_interval"])

    # Stream subscription options
    blocking_timeout_ms: int = field(
        default_factory=lambda: DEFAULT_CONFIG["blocking_timeout_ms"]
    )
    max_retries: int = field(default_factory=lambda: DEFAULT_CONFIG["max_retries"])
    retry_delay_seconds: float = field(
        default_factory=lambda: DEFAULT_CONFIG["retry_delay_seconds"]
    )
    enable_dlq: bool = field(default_factory=lambda: DEFAULT_CONFIG["enable_dlq"])

    # Event store subscription options
    position_update_interval: int = field(
        default_factory=lambda: DEFAULT_CONFIG["position_update_interval"]
    )

    # Filtering options
    origin_stream: str | None = None

    # Per-subscription DLQ overrides (None = inherit global [server.dlq] values)
    dlq_retention_hours: int | None = None
    dlq_alert_threshold: int | None = None

    # Circuit breaker options (STREAM only)
    circuit_breaker_threshold: int = field(
        default_factory=lambda: DEFAULT_CONFIG["circuit_breaker_threshold"]
    )
    circuit_breaker_reset_seconds: float = field(
        default_factory=lambda: DEFAULT_CONFIG["circuit_breaker_reset_seconds"]
    )

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        self.validate()

    def validate(self) -> None:
        """Validate configuration options.

        Raises:
            ConfigurationError: If validation fails due to incompatible options.
        """
        errors: list[str] = []

        # Validate numeric fields
        if self.messages_per_tick <= 0:
            errors.append("messages_per_tick must be positive")

        if self.tick_interval < 0:
            errors.append("tick_interval must be non-negative")

        if self.blocking_timeout_ms < 0:
            errors.append("blocking_timeout_ms must be non-negative")

        if self.max_retries < 0:
            errors.append("max_retries must be non-negative")

        if self.retry_delay_seconds < 0:
            errors.append("retry_delay_seconds must be non-negative")

        if self.position_update_interval <= 0:
            errors.append("position_update_interval must be positive")

        if self.dlq_retention_hours is not None and self.dlq_retention_hours <= 0:
            errors.append("dlq_retention_hours must be positive when set")

        if self.dlq_alert_threshold is not None and self.dlq_alert_threshold <= 0:
            errors.append("dlq_alert_threshold must be positive when set")

        if self.circuit_breaker_threshold < 1:
            errors.append("circuit_breaker_threshold must be at least 1")

        if self.circuit_breaker_reset_seconds <= 0 or not math.isfinite(
            self.circuit_breaker_reset_seconds
        ):
            # Reject inf/nan too: inf would OPEN the breaker forever (it never
            # reaches HALF_OPEN), and nan slips past ``> 0`` in the gate and
            # silently disables the pause.
            errors.append("circuit_breaker_reset_seconds must be positive and finite")

        # Validate DLQ is not enabled for EVENT_STORE
        if self.subscription_type == SubscriptionType.EVENT_STORE and self.enable_dlq:
            errors.append(
                "enable_dlq is not supported for EVENT_STORE subscription type. "
                "EventStoreSubscription handles messages without DLQ support."
            )

        # Log warning if using EVENT_STORE in production
        if self.subscription_type == SubscriptionType.EVENT_STORE:
            self._log_event_store_warning()

        if errors:
            raise ConfigurationError(
                f"Invalid subscription configuration: {'; '.join(errors)}"
            )

    def _log_event_store_warning(self) -> None:
        """Log a warning when using EVENT_STORE subscription type in production."""
        if self._is_production_environment():
            logger.warning(
                "⚠️ EventStoreSubscription is being used in production. "
                "For production workloads, consider using StreamSubscription which provides: "
                "transactional outbox pattern, automatic retry mechanisms, "
                "dead letter queue, and horizontal scaling with consumer groups."
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

    @classmethod
    def from_profile(
        cls,
        profile: SubscriptionProfile,
        *,
        subscription_type: SubscriptionType | None = None,
        messages_per_tick: int | None = None,
        tick_interval: int | None = None,
        blocking_timeout_ms: int | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        enable_dlq: bool | None = None,
        position_update_interval: int | None = None,
        origin_stream: str | None = None,
        dlq_retention_hours: int | None = None,
        dlq_alert_threshold: int | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_reset_seconds: float | None = None,
    ) -> "SubscriptionConfig":
        """Create a configuration from a profile with optional overrides.

        Args:
            profile: The base profile to use for defaults.
            subscription_type: Override for subscription type.
            messages_per_tick: Override for messages per tick.
            tick_interval: Override for tick interval.
            blocking_timeout_ms: Override for blocking timeout.
            max_retries: Override for max retries.
            retry_delay_seconds: Override for retry delay.
            enable_dlq: Override for DLQ setting.
            position_update_interval: Override for position update interval.
            origin_stream: Override for origin stream filter.

        Returns:
            A SubscriptionConfig instance with profile defaults and overrides applied.

        Example:
            >>> config = SubscriptionConfig.from_profile(
            ...     SubscriptionProfile.PRODUCTION,
            ...     messages_per_tick=50
            ... )
            >>> config.messages_per_tick
            50
            >>> config.max_retries  # From profile
            3
        """
        if profile not in PROFILE_DEFAULTS:
            raise ConfigurationError(f"Unknown subscription profile: {profile}")

        profile_defaults = PROFILE_DEFAULTS[profile]

        # Build configuration with profile defaults, overriding with explicit values
        config_kwargs: dict[str, Any] = {}

        # Handle subscription_type specially to maintain enum type
        if subscription_type is not None:
            config_kwargs["subscription_type"] = subscription_type
        else:
            config_kwargs["subscription_type"] = profile_defaults["subscription_type"]

        # Apply other overrides or profile defaults
        config_kwargs["messages_per_tick"] = (
            messages_per_tick
            if messages_per_tick is not None
            else profile_defaults["messages_per_tick"]
        )
        config_kwargs["tick_interval"] = (
            tick_interval
            if tick_interval is not None
            else profile_defaults["tick_interval"]
        )
        config_kwargs["blocking_timeout_ms"] = (
            blocking_timeout_ms
            if blocking_timeout_ms is not None
            else profile_defaults["blocking_timeout_ms"]
        )
        config_kwargs["max_retries"] = (
            max_retries if max_retries is not None else profile_defaults["max_retries"]
        )
        config_kwargs["retry_delay_seconds"] = (
            retry_delay_seconds
            if retry_delay_seconds is not None
            else profile_defaults["retry_delay_seconds"]
        )
        config_kwargs["enable_dlq"] = (
            enable_dlq if enable_dlq is not None else profile_defaults["enable_dlq"]
        )
        config_kwargs["position_update_interval"] = (
            position_update_interval
            if position_update_interval is not None
            else profile_defaults["position_update_interval"]
        )
        config_kwargs["origin_stream"] = (
            origin_stream
            if origin_stream is not None
            else profile_defaults["origin_stream"]
        )
        config_kwargs["circuit_breaker_threshold"] = (
            circuit_breaker_threshold
            if circuit_breaker_threshold is not None
            else profile_defaults["circuit_breaker_threshold"]
        )
        config_kwargs["circuit_breaker_reset_seconds"] = (
            circuit_breaker_reset_seconds
            if circuit_breaker_reset_seconds is not None
            else profile_defaults["circuit_breaker_reset_seconds"]
        )

        # DLQ overrides are pass-through (None means inherit global)
        if dlq_retention_hours is not None:
            config_kwargs["dlq_retention_hours"] = dlq_retention_hours
        if dlq_alert_threshold is not None:
            config_kwargs["dlq_alert_threshold"] = dlq_alert_threshold

        return cls(**config_kwargs)

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "SubscriptionConfig":
        """Create a configuration from a dictionary.

        If the dictionary contains a 'profile' key, that profile's defaults are used
        as a base, with other keys in the dictionary acting as overrides.

        Args:
            config_dict: Dictionary containing configuration values.
                Supported keys:
                - profile: Profile name (string) to use as base
                - subscription_type: Type of subscription (string or SubscriptionType)
                - messages_per_tick: Number of messages per tick
                - tick_interval: Interval between ticks
                - blocking_timeout_ms: Blocking read timeout
                - max_retries: Maximum retry attempts
                - retry_delay_seconds: Delay between retries
                - enable_dlq: Enable dead letter queue
                - position_update_interval: Position update frequency
                - origin_stream: Origin stream filter

        Returns:
            A SubscriptionConfig instance.

        Raises:
            ConfigurationError: If the configuration is invalid.

        Example:
            >>> config = SubscriptionConfig.from_dict({
            ...     "profile": "production",
            ...     "messages_per_tick": 50
            ... })
            >>> config.messages_per_tick
            50
        """
        # Make a copy to avoid modifying the original
        config_dict = dict(config_dict)

        # Extract and resolve profile if present
        profile_name = config_dict.pop("profile", None)

        if profile_name is not None:
            profile = cls._resolve_profile(profile_name)
            profile_defaults = PROFILE_DEFAULTS[profile]
        else:
            profile_defaults = DEFAULT_CONFIG

        # Resolve subscription_type if present
        subscription_type = config_dict.pop("subscription_type", None)
        if subscription_type is not None:
            subscription_type = cls._resolve_subscription_type(subscription_type)
        else:
            subscription_type = profile_defaults["subscription_type"]

        # Build final configuration
        config_kwargs: dict[str, Any] = {"subscription_type": subscription_type}

        # Known configuration keys with their types
        config_keys = [
            ("messages_per_tick", int),
            ("tick_interval", int),
            ("blocking_timeout_ms", int),
            ("max_retries", int),
            ("retry_delay_seconds", float),
            ("enable_dlq", bool),
            ("position_update_interval", int),
            ("origin_stream", str),
            ("dlq_retention_hours", int),
            ("dlq_alert_threshold", int),
            ("circuit_breaker_threshold", int),
            ("circuit_breaker_reset_seconds", float),
        ]

        for key, expected_type in config_keys:
            if key in config_dict:
                value = config_dict[key]
                # Type coercion for common cases
                if expected_type is int and isinstance(value, (int, float)):
                    value = int(value)
                elif expected_type is float and isinstance(value, (int, float)):
                    value = float(value)
                elif expected_type is bool:
                    value = bool(value)
                config_kwargs[key] = value
            elif key in profile_defaults:
                config_kwargs[key] = profile_defaults[key]

        return cls(**config_kwargs)

    @staticmethod
    def _resolve_profile(profile: str | SubscriptionProfile) -> SubscriptionProfile:
        """Resolve a profile from string or enum.

        Args:
            profile: Profile name as string or SubscriptionProfile enum.

        Returns:
            The resolved SubscriptionProfile enum value.

        Raises:
            ConfigurationError: If the profile cannot be resolved.
        """
        if isinstance(profile, SubscriptionProfile):
            return profile

        if isinstance(profile, str):
            try:
                return SubscriptionProfile(profile.lower())
            except ValueError as e:
                valid_profiles = ", ".join(p.value for p in SubscriptionProfile)
                raise ConfigurationError(
                    f"Unknown subscription profile: '{profile}'. "
                    f"Valid profiles are: {valid_profiles}"
                ) from e

        raise ConfigurationError(
            f"Profile must be a string or SubscriptionProfile, got {type(profile)}"
        )

    @staticmethod
    def _resolve_subscription_type(
        sub_type: str | SubscriptionType,
    ) -> SubscriptionType:
        """Resolve a subscription type from string or enum.

        Args:
            sub_type: Subscription type as string or SubscriptionType enum.

        Returns:
            The resolved SubscriptionType enum value.

        Raises:
            ConfigurationError: If the subscription type cannot be resolved.
        """
        if isinstance(sub_type, SubscriptionType):
            return sub_type

        if isinstance(sub_type, str):
            try:
                return SubscriptionType(sub_type.lower())
            except ValueError as e:
                valid_types = ", ".join(t.value for t in SubscriptionType)
                raise ConfigurationError(
                    f"Unknown subscription type: '{sub_type}'. "
                    f"Valid types are: {valid_types}"
                ) from e

        raise ConfigurationError(
            f"Subscription type must be a string or SubscriptionType, "
            f"got {type(sub_type)}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary.

        Returns:
            A dictionary representation of the configuration.
        """
        return {
            "subscription_type": self.subscription_type.value,
            "messages_per_tick": self.messages_per_tick,
            "tick_interval": self.tick_interval,
            "blocking_timeout_ms": self.blocking_timeout_ms,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "enable_dlq": self.enable_dlq,
            "position_update_interval": self.position_update_interval,
            "origin_stream": self.origin_stream,
            "dlq_retention_hours": self.dlq_retention_hours,
            "dlq_alert_threshold": self.dlq_alert_threshold,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_reset_seconds": self.circuit_breaker_reset_seconds,
        }


__all__ = [
    "BUILTIN_PROFILE_NAMES",
    "DEFAULT_CONFIG",
    "PROFILE_DEFAULTS",
    "PROFILE_FIELDS",
    "CircuitBreakerState",
    "SubscriptionConfig",
    "SubscriptionProfile",
    "SubscriptionType",
    "build_profile_registry",
]
