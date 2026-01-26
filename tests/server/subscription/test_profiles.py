"""Tests for subscription configuration profiles system.

This module contains comprehensive tests for the SubscriptionConfig,
SubscriptionType, SubscriptionProfile enums, and profile loading functionality.
"""

import os
from unittest.mock import patch

import pytest

from protean.exceptions import ConfigurationError
from protean.server.subscription.profiles import (
    DEFAULT_CONFIG,
    PROFILE_DEFAULTS,
    SubscriptionConfig,
    SubscriptionProfile,
    SubscriptionType,
)


class TestSubscriptionTypeEnum:
    """Tests for SubscriptionType enum."""

    def test_subscription_type_has_stream_value(self):
        """SubscriptionType should have STREAM member."""
        assert SubscriptionType.STREAM.value == "stream"

    def test_subscription_type_has_event_store_value(self):
        """SubscriptionType should have EVENT_STORE member."""
        assert SubscriptionType.EVENT_STORE.value == "event_store"

    def test_subscription_type_values(self):
        """SubscriptionType should have exactly two values."""
        assert len(SubscriptionType) == 2

    def test_subscription_type_from_string(self):
        """SubscriptionType can be created from string value."""
        assert SubscriptionType("stream") == SubscriptionType.STREAM
        assert SubscriptionType("event_store") == SubscriptionType.EVENT_STORE


class TestSubscriptionProfileEnum:
    """Tests for SubscriptionProfile enum."""

    def test_subscription_profile_has_production(self):
        """SubscriptionProfile should have PRODUCTION member."""
        assert SubscriptionProfile.PRODUCTION.value == "production"

    def test_subscription_profile_has_fast(self):
        """SubscriptionProfile should have FAST member."""
        assert SubscriptionProfile.FAST.value == "fast"

    def test_subscription_profile_has_batch(self):
        """SubscriptionProfile should have BATCH member."""
        assert SubscriptionProfile.BATCH.value == "batch"

    def test_subscription_profile_has_debug(self):
        """SubscriptionProfile should have DEBUG member."""
        assert SubscriptionProfile.DEBUG.value == "debug"

    def test_subscription_profile_has_projection(self):
        """SubscriptionProfile should have PROJECTION member."""
        assert SubscriptionProfile.PROJECTION.value == "projection"

    def test_subscription_profile_values(self):
        """SubscriptionProfile should have exactly five values."""
        assert len(SubscriptionProfile) == 5

    def test_subscription_profile_from_string(self):
        """SubscriptionProfile can be created from string value."""
        assert SubscriptionProfile("production") == SubscriptionProfile.PRODUCTION
        assert SubscriptionProfile("fast") == SubscriptionProfile.FAST
        assert SubscriptionProfile("batch") == SubscriptionProfile.BATCH
        assert SubscriptionProfile("debug") == SubscriptionProfile.DEBUG
        assert SubscriptionProfile("projection") == SubscriptionProfile.PROJECTION


class TestProfileDefaults:
    """Tests for PROFILE_DEFAULTS dictionary."""

    def test_all_profiles_have_defaults(self):
        """All profiles should have entries in PROFILE_DEFAULTS."""
        for profile in SubscriptionProfile:
            assert profile in PROFILE_DEFAULTS

    def test_production_profile_defaults(self):
        """PRODUCTION profile should have correct defaults."""
        defaults = PROFILE_DEFAULTS[SubscriptionProfile.PRODUCTION]
        assert defaults["subscription_type"] == SubscriptionType.STREAM
        assert defaults["messages_per_tick"] == 100
        assert defaults["blocking_timeout_ms"] == 5000
        assert defaults["max_retries"] == 3
        assert defaults["enable_dlq"] is True

    def test_fast_profile_defaults(self):
        """FAST profile should have lower latency settings."""
        defaults = PROFILE_DEFAULTS[SubscriptionProfile.FAST]
        assert defaults["subscription_type"] == SubscriptionType.STREAM
        assert defaults["messages_per_tick"] == 10
        assert defaults["blocking_timeout_ms"] == 100
        assert defaults["retry_delay_seconds"] == 0

    def test_batch_profile_defaults(self):
        """BATCH profile should have high throughput settings."""
        defaults = PROFILE_DEFAULTS[SubscriptionProfile.BATCH]
        assert defaults["subscription_type"] == SubscriptionType.STREAM
        assert defaults["messages_per_tick"] == 500
        assert defaults["blocking_timeout_ms"] == 10000
        assert defaults["max_retries"] == 5

    def test_debug_profile_defaults(self):
        """DEBUG profile should have development-friendly settings."""
        defaults = PROFILE_DEFAULTS[SubscriptionProfile.DEBUG]
        assert defaults["subscription_type"] == SubscriptionType.STREAM
        assert defaults["messages_per_tick"] == 1
        assert defaults["tick_interval"] == 1
        assert defaults["enable_dlq"] is False

    def test_projection_profile_defaults(self):
        """PROJECTION profile should use EVENT_STORE subscription."""
        defaults = PROFILE_DEFAULTS[SubscriptionProfile.PROJECTION]
        assert defaults["subscription_type"] == SubscriptionType.EVENT_STORE
        assert defaults["enable_dlq"] is False


class TestSubscriptionConfigCreation:
    """Tests for SubscriptionConfig creation."""

    def test_default_config_creation(self):
        """SubscriptionConfig can be created with default values."""
        config = SubscriptionConfig()
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == DEFAULT_CONFIG["messages_per_tick"]
        assert config.tick_interval == DEFAULT_CONFIG["tick_interval"]

    def test_config_with_explicit_values(self):
        """SubscriptionConfig can be created with explicit values."""
        config = SubscriptionConfig(
            subscription_type=SubscriptionType.STREAM,
            messages_per_tick=50,
            blocking_timeout_ms=2000,
            enable_dlq=False,
        )
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 50
        assert config.blocking_timeout_ms == 2000
        assert config.enable_dlq is False

    def test_config_with_event_store_type_and_dlq_disabled(self):
        """EVENT_STORE config with enable_dlq=False should be valid."""
        config = SubscriptionConfig(
            subscription_type=SubscriptionType.EVENT_STORE,
            enable_dlq=False,
        )
        assert config.subscription_type == SubscriptionType.EVENT_STORE
        assert config.enable_dlq is False


class TestSubscriptionConfigFromProfile:
    """Tests for SubscriptionConfig.from_profile() method."""

    def test_from_production_profile(self):
        """Creating config from PRODUCTION profile loads correct defaults."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 100
        assert config.blocking_timeout_ms == 5000
        assert config.max_retries == 3
        assert config.enable_dlq is True

    def test_from_fast_profile(self):
        """Creating config from FAST profile loads correct defaults."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.FAST)
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 10
        assert config.blocking_timeout_ms == 100
        assert config.retry_delay_seconds == 0

    def test_from_batch_profile(self):
        """Creating config from BATCH profile loads correct defaults."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.BATCH)
        assert config.messages_per_tick == 500
        assert config.blocking_timeout_ms == 10000
        assert config.max_retries == 5

    def test_from_debug_profile(self):
        """Creating config from DEBUG profile loads correct defaults."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.DEBUG)
        assert config.messages_per_tick == 1
        assert config.tick_interval == 1
        assert config.enable_dlq is False

    def test_from_projection_profile(self):
        """Creating config from PROJECTION profile loads correct defaults."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PROJECTION)
        assert config.subscription_type == SubscriptionType.EVENT_STORE
        assert config.enable_dlq is False

    def test_profile_with_single_override(self):
        """Profile defaults can be overridden with single value."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            messages_per_tick=50,
        )
        # Overridden value
        assert config.messages_per_tick == 50
        # Profile defaults preserved
        assert config.blocking_timeout_ms == 5000
        assert config.max_retries == 3

    def test_profile_with_multiple_overrides(self):
        """Profile defaults can be overridden with multiple values."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            messages_per_tick=25,
            max_retries=5,
            enable_dlq=False,
        )
        assert config.messages_per_tick == 25
        assert config.max_retries == 5
        assert config.enable_dlq is False
        # Profile default preserved
        assert config.blocking_timeout_ms == 5000

    def test_profile_override_subscription_type(self):
        """Profile subscription_type can be overridden."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            subscription_type=SubscriptionType.EVENT_STORE,
            enable_dlq=False,  # Must disable DLQ for EVENT_STORE
        )
        assert config.subscription_type == SubscriptionType.EVENT_STORE

    def test_profile_with_origin_stream(self):
        """Profile can include origin_stream filter."""
        config = SubscriptionConfig.from_profile(
            SubscriptionProfile.PROJECTION,
            origin_stream="order",
        )
        assert config.origin_stream == "order"


class TestSubscriptionConfigFromDict:
    """Tests for SubscriptionConfig.from_dict() method."""

    def test_from_empty_dict(self):
        """Creating config from empty dict uses default values."""
        config = SubscriptionConfig.from_dict({})
        assert config.subscription_type == DEFAULT_CONFIG["subscription_type"]
        assert config.messages_per_tick == DEFAULT_CONFIG["messages_per_tick"]

    def test_from_dict_with_profile_string(self):
        """Creating config from dict with profile string loads profile defaults."""
        config = SubscriptionConfig.from_dict({"profile": "production"})
        assert config.messages_per_tick == 100
        assert config.blocking_timeout_ms == 5000

    def test_from_dict_with_profile_and_overrides(self):
        """Creating config from dict with profile and overrides."""
        config = SubscriptionConfig.from_dict(
            {
                "profile": "production",
                "messages_per_tick": 50,
                "max_retries": 10,
            }
        )
        assert config.messages_per_tick == 50
        assert config.max_retries == 10
        # Profile default preserved
        assert config.blocking_timeout_ms == 5000

    def test_from_dict_with_subscription_type_string(self):
        """Creating config from dict with subscription_type as string."""
        config = SubscriptionConfig.from_dict(
            {
                "subscription_type": "stream",
                "messages_per_tick": 20,
            }
        )
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 20

    def test_from_dict_with_subscription_type_enum(self):
        """Creating config from dict with subscription_type as enum."""
        config = SubscriptionConfig.from_dict(
            {
                "subscription_type": SubscriptionType.EVENT_STORE,
                "enable_dlq": False,
            }
        )
        assert config.subscription_type == SubscriptionType.EVENT_STORE

    def test_from_dict_with_all_options(self):
        """Creating config from dict with all options specified."""
        config = SubscriptionConfig.from_dict(
            {
                "subscription_type": "stream",
                "messages_per_tick": 75,
                "tick_interval": 2,
                "blocking_timeout_ms": 3000,
                "max_retries": 4,
                "retry_delay_seconds": 2,
                "enable_dlq": True,
                "position_update_interval": 20,
                "origin_stream": "test-stream",
            }
        )
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 75
        assert config.tick_interval == 2
        assert config.blocking_timeout_ms == 3000
        assert config.max_retries == 4
        assert config.retry_delay_seconds == 2
        assert config.enable_dlq is True
        assert config.position_update_interval == 20
        assert config.origin_stream == "test-stream"

    def test_from_dict_case_insensitive_profile(self):
        """Profile names should be case-insensitive."""
        config_lower = SubscriptionConfig.from_dict({"profile": "production"})
        config_upper = SubscriptionConfig.from_dict({"profile": "PRODUCTION"})
        config_mixed = SubscriptionConfig.from_dict({"profile": "Production"})

        assert config_lower.messages_per_tick == config_upper.messages_per_tick
        assert config_lower.messages_per_tick == config_mixed.messages_per_tick

    def test_from_dict_case_insensitive_subscription_type(self):
        """Subscription type names should be case-insensitive."""
        config_lower = SubscriptionConfig.from_dict({"subscription_type": "stream"})
        config_upper = SubscriptionConfig.from_dict({"subscription_type": "STREAM"})

        assert config_lower.subscription_type == config_upper.subscription_type

    def test_from_dict_type_coercion_int(self):
        """Integer values can be passed as floats."""
        config = SubscriptionConfig.from_dict(
            {
                "messages_per_tick": 50.0,
            }
        )
        assert config.messages_per_tick == 50
        assert isinstance(config.messages_per_tick, int)

    def test_from_dict_does_not_modify_original(self):
        """from_dict should not modify the original dictionary."""
        original = {"profile": "production", "messages_per_tick": 50}
        original_copy = dict(original)
        SubscriptionConfig.from_dict(original)
        assert original == original_copy


class TestSubscriptionConfigValidation:
    """Tests for SubscriptionConfig validation rules."""

    def test_event_store_with_dlq_raises_error(self):
        """EVENT_STORE subscription type with enable_dlq=True should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(
                subscription_type=SubscriptionType.EVENT_STORE,
                enable_dlq=True,
            )
        assert "enable_dlq is not supported for EVENT_STORE" in str(exc_info.value)

    def test_negative_messages_per_tick_raises_error(self):
        """Negative messages_per_tick should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(messages_per_tick=-1)
        assert "messages_per_tick must be positive" in str(exc_info.value)

    def test_zero_messages_per_tick_raises_error(self):
        """Zero messages_per_tick should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(messages_per_tick=0)
        assert "messages_per_tick must be positive" in str(exc_info.value)

    def test_negative_tick_interval_raises_error(self):
        """Negative tick_interval should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(tick_interval=-1)
        assert "tick_interval must be non-negative" in str(exc_info.value)

    def test_zero_tick_interval_is_valid(self):
        """Zero tick_interval should be valid (for blocking reads)."""
        config = SubscriptionConfig(tick_interval=0)
        assert config.tick_interval == 0

    def test_negative_blocking_timeout_raises_error(self):
        """Negative blocking_timeout_ms should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(blocking_timeout_ms=-1)
        assert "blocking_timeout_ms must be non-negative" in str(exc_info.value)

    def test_negative_max_retries_raises_error(self):
        """Negative max_retries should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(max_retries=-1)
        assert "max_retries must be non-negative" in str(exc_info.value)

    def test_zero_max_retries_is_valid(self):
        """Zero max_retries should be valid (no retries)."""
        config = SubscriptionConfig(max_retries=0)
        assert config.max_retries == 0

    def test_negative_retry_delay_raises_error(self):
        """Negative retry_delay_seconds should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(retry_delay_seconds=-1)
        assert "retry_delay_seconds must be non-negative" in str(exc_info.value)

    def test_negative_position_update_interval_raises_error(self):
        """Negative position_update_interval should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(
                subscription_type=SubscriptionType.EVENT_STORE,
                enable_dlq=False,
                position_update_interval=-1,
            )
        assert "position_update_interval must be positive" in str(exc_info.value)

    def test_zero_position_update_interval_raises_error(self):
        """Zero position_update_interval should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig(
                subscription_type=SubscriptionType.EVENT_STORE,
                enable_dlq=False,
                position_update_interval=0,
            )
        assert "position_update_interval must be positive" in str(exc_info.value)

    def test_unknown_profile_raises_error(self):
        """Unknown profile string should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig.from_dict({"profile": "unknown"})
        assert "Unknown subscription profile" in str(exc_info.value)

    def test_unknown_subscription_type_raises_error(self):
        """Unknown subscription type string should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig.from_dict({"subscription_type": "unknown"})
        assert "Unknown subscription type" in str(exc_info.value)

    def test_invalid_profile_type_raises_error(self):
        """Invalid profile type (not string or enum) should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig._resolve_profile(123)  # type: ignore
        assert "Profile must be a string or SubscriptionProfile" in str(exc_info.value)

    def test_invalid_subscription_type_type_raises_error(self):
        """Invalid subscription type type should raise error."""
        with pytest.raises(ConfigurationError) as exc_info:
            SubscriptionConfig._resolve_subscription_type(123)  # type: ignore
        assert "Subscription type must be a string or SubscriptionType" in str(
            exc_info.value
        )


class TestSubscriptionConfigToDict:
    """Tests for SubscriptionConfig.to_dict() method."""

    def test_to_dict_returns_all_fields(self):
        """to_dict should return all configuration fields."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        result = config.to_dict()

        assert "subscription_type" in result
        assert "messages_per_tick" in result
        assert "tick_interval" in result
        assert "blocking_timeout_ms" in result
        assert "max_retries" in result
        assert "retry_delay_seconds" in result
        assert "enable_dlq" in result
        assert "position_update_interval" in result
        assert "origin_stream" in result

    def test_to_dict_subscription_type_is_string(self):
        """to_dict should return subscription_type as string value."""
        config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
        result = config.to_dict()
        assert result["subscription_type"] == "stream"

    def test_to_dict_roundtrip(self):
        """Config can be recreated from to_dict output."""
        original = SubscriptionConfig.from_profile(
            SubscriptionProfile.PRODUCTION,
            messages_per_tick=50,
            origin_stream="test-stream",
        )
        dict_repr = original.to_dict()
        recreated = SubscriptionConfig.from_dict(dict_repr)

        assert recreated.subscription_type == original.subscription_type
        assert recreated.messages_per_tick == original.messages_per_tick
        assert recreated.origin_stream == original.origin_stream


class TestProductionEnvironmentDetection:
    """Tests for production environment detection."""

    def test_detects_protean_env_production(self):
        """Should detect PROTEAN_ENV=production as production."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}):
            assert SubscriptionConfig._is_production_environment() is True

    def test_detects_protean_env_prod(self):
        """Should detect PROTEAN_ENV=prod as production."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "prod"}):
            assert SubscriptionConfig._is_production_environment() is True

    def test_detects_python_env_production(self):
        """Should detect PYTHON_ENV=production as production."""
        with patch.dict(os.environ, {"PYTHON_ENV": "production"}):
            assert SubscriptionConfig._is_production_environment() is True

    def test_detects_env_production(self):
        """Should detect ENV=production as production."""
        with patch.dict(os.environ, {"ENV": "production"}):
            assert SubscriptionConfig._is_production_environment() is True

    def test_detects_environment_production(self):
        """Should detect ENVIRONMENT=production as production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            assert SubscriptionConfig._is_production_environment() is True

    def test_case_insensitive_detection(self):
        """Should detect production case-insensitively."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "PRODUCTION"}):
            assert SubscriptionConfig._is_production_environment() is True

        with patch.dict(os.environ, {"PROTEAN_ENV": "Production"}):
            assert SubscriptionConfig._is_production_environment() is True

    def test_non_production_env(self):
        """Should not detect non-production environments."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "development"}, clear=True):
            assert SubscriptionConfig._is_production_environment() is False

        with patch.dict(os.environ, {"PROTEAN_ENV": "staging"}, clear=True):
            assert SubscriptionConfig._is_production_environment() is False

    def test_no_env_vars_set(self):
        """Should not detect production when no env vars are set."""
        with patch.dict(os.environ, {}, clear=True):
            assert SubscriptionConfig._is_production_environment() is False


class TestEventStoreWarning:
    """Tests for EVENT_STORE usage warnings."""

    def test_logs_warning_in_production(self, caplog):
        """Should log warning when using EVENT_STORE in production environment."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}):
            SubscriptionConfig(
                subscription_type=SubscriptionType.EVENT_STORE,
                enable_dlq=False,
            )

        assert "EventStoreSubscription is being used in production" in caplog.text

    def test_no_warning_in_development(self, caplog):
        """Should not log warning when using EVENT_STORE in non-production."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "development"}, clear=True):
            SubscriptionConfig(
                subscription_type=SubscriptionType.EVENT_STORE,
                enable_dlq=False,
            )

        assert "EventStoreSubscription is being used in production" not in caplog.text

    def test_no_warning_for_stream_subscription(self, caplog):
        """Should not log warning when using STREAM subscription."""
        with patch.dict(os.environ, {"PROTEAN_ENV": "production"}):
            SubscriptionConfig(subscription_type=SubscriptionType.STREAM)

        assert "EventStoreSubscription is being used in production" not in caplog.text
