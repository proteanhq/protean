"""Tests for subscription configuration resolution.

This module tests the ConfigResolver class which resolves subscription
configuration from multiple sources with a defined priority hierarchy.
"""

import logging

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import (
    DEFAULT_CONFIG,
    PROFILE_DEFAULTS,
    SubscriptionProfile,
    SubscriptionType,
)


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer_name = String()


class TestConfigResolverInitialization:
    """Tests for ConfigResolver initialization."""

    def test_resolver_initializes_with_domain(self, test_domain):
        """ConfigResolver can be initialized with a domain."""
        resolver = ConfigResolver(test_domain)
        assert resolver._domain is test_domain

    def test_resolver_accesses_server_config(self, test_domain):
        """ConfigResolver can access server configuration."""
        resolver = ConfigResolver(test_domain)
        assert isinstance(resolver.server_config, dict)
        assert "default_subscription_type" in resolver.server_config


class TestConfigResolverHardcodedDefaults:
    """Tests for hardcoded default configuration."""

    def test_uses_hardcoded_defaults_when_no_config(self, test_domain):
        """Resolver uses hardcoded defaults when not overridden by server config."""

        @test_domain.event_handler(part_of=Order)
        class MinimalHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(MinimalHandler)

        # Server config has messages_per_tick=100 which overrides hardcoded default
        # But other values not in server config use hardcoded defaults
        assert config.max_retries == DEFAULT_CONFIG["max_retries"]
        assert config.retry_delay_seconds == DEFAULT_CONFIG["retry_delay_seconds"]
        assert (
            config.position_update_interval
            == DEFAULT_CONFIG["position_update_interval"]
        )

    @pytest.mark.no_test_domain
    def test_pure_hardcoded_defaults_without_server_config(self):
        """Resolver uses pure hardcoded defaults when server config is empty."""
        from protean.domain import Domain

        domain = Domain(name="Minimal")
        # Clear server config to test pure defaults
        domain.config["server"] = {}

        @domain.event_handler(stream_category="$all")
        class MinimalHandler(BaseEventHandler):
            pass

        domain._initialize()

        resolver = ConfigResolver(domain)
        config = resolver.resolve(MinimalHandler)

        # Should use DEFAULT_CONFIG values (STREAM subscription type with DLQ)
        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == DEFAULT_CONFIG["messages_per_tick"]
        assert config.tick_interval == DEFAULT_CONFIG["tick_interval"]
        assert config.max_retries == DEFAULT_CONFIG["max_retries"]
        assert config.enable_dlq == DEFAULT_CONFIG["enable_dlq"]


class TestConfigResolverServerDefaults:
    """Tests for server-level default configuration."""

    def test_applies_server_default_subscription_type(self, test_domain):
        """Server default_subscription_type is applied."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.subscription_type == SubscriptionType.STREAM

    @pytest.mark.no_test_domain
    def test_applies_server_default_subscription_profile(self):
        """Server default_subscription_profile is expanded when no explicit override."""
        from protean.domain import Domain

        domain = Domain(name="ProfileTest")
        # Set profile but clear explicit messages_per_tick so profile value is used
        domain.config["server"]["default_subscription_profile"] = "fast"
        domain.config["server"].pop("messages_per_tick", None)

        @domain.event_handler(stream_category="$all")
        class TestHandler(BaseEventHandler):
            pass

        domain._initialize()

        resolver = ConfigResolver(domain)
        config = resolver.resolve(TestHandler)

        # FAST profile has messages_per_tick = 10 and blocking_timeout_ms = 100
        assert (
            config.messages_per_tick
            == PROFILE_DEFAULTS[SubscriptionProfile.FAST]["messages_per_tick"]
        )
        assert (
            config.blocking_timeout_ms
            == PROFILE_DEFAULTS[SubscriptionProfile.FAST]["blocking_timeout_ms"]
        )

    def test_applies_server_stream_subscription_settings(self, test_domain):
        """Server stream_subscription settings are applied."""
        test_domain.config["server"]["stream_subscription"]["blocking_timeout_ms"] = (
            8000
        )
        test_domain.config["server"]["stream_subscription"]["max_retries"] = 7

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.blocking_timeout_ms == 8000
        assert config.max_retries == 7

    def test_applies_server_event_store_subscription_settings(self, test_domain):
        """Server event_store_subscription settings are applied."""
        test_domain.config["server"]["event_store_subscription"][
            "position_update_interval"
        ] = 25

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.position_update_interval == 25

    def test_applies_server_messages_per_tick(self, test_domain):
        """Server messages_per_tick is applied."""
        test_domain.config["server"]["messages_per_tick"] = 75

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.messages_per_tick == 75


class TestConfigResolverHandlerServerConfig:
    """Tests for handler-specific server configuration."""

    def test_applies_handler_specific_server_config(self, test_domain):
        """Handler-specific server config is applied."""
        test_domain.config["server"]["subscriptions"]["OrderHandler"] = {
            "profile": "production",
            "messages_per_tick": 200,
        }

        @test_domain.event_handler(part_of=Order)
        class OrderHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(OrderHandler)

        assert config.messages_per_tick == 200

    def test_handler_server_config_overrides_server_defaults(self, test_domain):
        """Handler-specific server config overrides server defaults."""
        test_domain.config["server"]["messages_per_tick"] = 50
        test_domain.config["server"]["subscriptions"]["OrderHandler"] = {
            "messages_per_tick": 150,
        }

        @test_domain.event_handler(part_of=Order)
        class OrderHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(OrderHandler)

        # Handler-specific should override server default
        assert config.messages_per_tick == 150

    def test_different_handlers_get_different_configs(self, test_domain):
        """Different handlers get their own configurations."""
        test_domain.config["server"]["subscriptions"]["FastHandler"] = {
            "messages_per_tick": 10,
        }
        test_domain.config["server"]["subscriptions"]["SlowHandler"] = {
            "messages_per_tick": 500,
        }

        @test_domain.event_handler(part_of=Order)
        class FastHandler(BaseEventHandler):
            pass

        @test_domain.event_handler(part_of=Order)
        class SlowHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)

        fast_config = resolver.resolve(FastHandler)
        slow_config = resolver.resolve(SlowHandler)

        assert fast_config.messages_per_tick == 10
        assert slow_config.messages_per_tick == 500


class TestConfigResolverHandlerMetaConfig:
    """Tests for handler Meta configuration."""

    def test_applies_handler_meta_subscription_type(self, test_domain):
        """Handler Meta subscription_type is applied."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.subscription_type == SubscriptionType.EVENT_STORE

    def test_applies_handler_meta_subscription_profile(self, test_domain):
        """Handler Meta subscription_profile is applied."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.BATCH,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        # BATCH profile has messages_per_tick = 500
        assert (
            config.messages_per_tick
            == PROFILE_DEFAULTS[SubscriptionProfile.BATCH]["messages_per_tick"]
        )

    def test_applies_handler_meta_subscription_config(self, test_domain):
        """Handler Meta subscription_config dict is applied."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_config={
                "messages_per_tick": 42,
                "max_retries": 7,
            },
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.messages_per_tick == 42
        assert config.max_retries == 7

    def test_handler_meta_overrides_server_config(self, test_domain):
        """Handler Meta overrides server configuration."""
        test_domain.config["server"]["messages_per_tick"] = 50
        test_domain.config["server"]["subscriptions"]["TestHandler"] = {
            "messages_per_tick": 100,
        }

        @test_domain.event_handler(
            part_of=Order,
            subscription_config={"messages_per_tick": 200},
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        # Handler Meta should have highest priority
        assert config.messages_per_tick == 200

    def test_handler_meta_source_stream_becomes_origin_stream(self, test_domain):
        """Handler Meta source_stream is mapped to origin_stream."""

        @test_domain.event_handler(
            part_of=Order,
            source_stream="external",
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.origin_stream == "external"


class TestConfigResolverPriorityOrder:
    """Tests for configuration priority order."""

    def test_full_priority_chain(self, test_domain):
        """Configuration respects full priority chain."""
        # Set at all levels with different values
        test_domain.config["server"]["messages_per_tick"] = 1  # Server default
        test_domain.config["server"]["subscriptions"]["PriorityHandler"] = {
            "messages_per_tick": 2,  # Handler server config
        }

        @test_domain.event_handler(
            part_of=Order,
            subscription_config={"messages_per_tick": 3},  # Handler Meta (highest)
        )
        class PriorityHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(PriorityHandler)

        # Handler Meta has highest priority
        assert config.messages_per_tick == 3

    def test_server_handler_config_over_server_default(self, test_domain):
        """Handler server config takes priority over server defaults."""
        test_domain.config["server"]["messages_per_tick"] = 10
        test_domain.config["server"]["subscriptions"]["TestHandler"] = {
            "messages_per_tick": 20,
        }

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.messages_per_tick == 20

    def test_profile_values_can_be_overridden(self, test_domain):
        """Profile values can be overridden by explicit settings."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
            subscription_config={"messages_per_tick": 999},
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        # Explicit value overrides profile default
        assert config.messages_per_tick == 999
        # Other profile values should still apply
        assert config.enable_dlq is True  # From PRODUCTION profile


class TestConfigResolverProfileExpansion:
    """Tests for profile expansion."""

    def test_production_profile_expansion(self, test_domain):
        """PRODUCTION profile expands to correct values."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 100
        assert config.enable_dlq is True

    def test_fast_profile_expansion(self, test_domain):
        """FAST profile expands to correct values."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.FAST,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 10
        assert config.blocking_timeout_ms == 100

    def test_batch_profile_expansion(self, test_domain):
        """BATCH profile expands to correct values."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.BATCH,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.messages_per_tick == 500
        assert config.blocking_timeout_ms == 10000

    def test_debug_profile_expansion(self, test_domain):
        """DEBUG profile expands to correct values."""

        @test_domain.event_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.DEBUG,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.messages_per_tick == 1
        assert config.enable_dlq is False

    def test_projection_profile_expansion(self, test_domain):
        """PROJECTION profile expands to correct values."""

        @test_domain.event_handler(
            stream_category="$all",
            subscription_profile=SubscriptionProfile.PROJECTION,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        assert config.subscription_type == SubscriptionType.EVENT_STORE
        assert config.enable_dlq is False

    def test_profile_from_server_config_string(self, test_domain):
        """Profile specified as string in server config is resolved."""
        test_domain.config["server"]["subscriptions"]["TestHandler"] = {
            "profile": "fast",
        }

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(TestHandler)

        # FAST profile values should be applied
        assert (
            config.messages_per_tick
            == PROFILE_DEFAULTS[SubscriptionProfile.FAST]["messages_per_tick"]
        )


class TestConfigResolverProductionWarning:
    """Tests for production environment detection and warnings."""

    def test_logs_warning_for_event_store_in_production(
        self, test_domain, monkeypatch, caplog
    ):
        """Warning is logged when using EVENT_STORE in production."""
        monkeypatch.setenv("PROTEAN_ENV", "production")

        @test_domain.event_handler(
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        with caplog.at_level(logging.WARNING):
            resolver.resolve(TestHandler)

        assert any(
            "EventStoreSubscription in production" in record.message
            for record in caplog.records
        )

    def test_no_warning_for_event_store_in_development(
        self, test_domain, monkeypatch, caplog
    ):
        """No warning when using EVENT_STORE in development."""
        monkeypatch.setenv("PROTEAN_ENV", "development")

        @test_domain.event_handler(
            stream_category="$all",
            subscription_type=SubscriptionType.EVENT_STORE,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        with caplog.at_level(logging.WARNING):
            resolver.resolve(TestHandler)

        assert not any(
            "EventStoreSubscription in production" in record.message
            for record in caplog.records
        )

    def test_no_warning_for_stream_in_production(
        self, test_domain, monkeypatch, caplog
    ):
        """No warning when using STREAM in production."""
        monkeypatch.setenv("PROTEAN_ENV", "production")

        @test_domain.event_handler(
            part_of=Order,
            subscription_type=SubscriptionType.STREAM,
        )
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        with caplog.at_level(logging.WARNING):
            resolver.resolve(TestHandler)

        assert not any(
            "EventStoreSubscription in production" in record.message
            for record in caplog.records
        )


class TestConfigResolverProductionDetection:
    """Tests for production environment detection."""

    @pytest.mark.parametrize(
        "env_var", ["PROTEAN_ENV", "PYTHON_ENV", "ENV", "ENVIRONMENT"]
    )
    def test_detects_production_from_various_env_vars(self, monkeypatch, env_var):
        """Production is detected from various environment variables."""
        monkeypatch.setenv(env_var, "production")
        assert ConfigResolver._is_production_environment() is True

    @pytest.mark.parametrize("value", ["production", "prod", "prd"])
    def test_detects_production_values(self, monkeypatch, value):
        """Production is detected for various production value strings."""
        monkeypatch.setenv("PROTEAN_ENV", value)
        assert ConfigResolver._is_production_environment() is True

    def test_case_insensitive_detection(self, monkeypatch):
        """Production detection is case-insensitive."""
        monkeypatch.setenv("PROTEAN_ENV", "PRODUCTION")
        assert ConfigResolver._is_production_environment() is True

    def test_non_production_env(self, monkeypatch):
        """Non-production environments return False."""
        monkeypatch.setenv("PROTEAN_ENV", "development")
        assert ConfigResolver._is_production_environment() is False

    def test_no_env_vars_set(self, monkeypatch):
        """Returns False when no environment variables are set."""
        for var in ["PROTEAN_ENV", "PYTHON_ENV", "ENV", "ENVIRONMENT"]:
            monkeypatch.delenv(var, raising=False)
        assert ConfigResolver._is_production_environment() is False


class TestConfigResolverMergeConfigs:
    """Tests for configuration merging logic."""

    def test_merge_preserves_base_values(self, test_domain):
        """Merge preserves base values not in override."""
        resolver = ConfigResolver(test_domain)
        base = {"a": 1, "b": 2, "c": 3}
        override = {"b": 20}

        result = resolver._merge_configs(base, override)

        assert result["a"] == 1
        assert result["b"] == 20
        assert result["c"] == 3

    def test_merge_ignores_none_values(self, test_domain):
        """Merge ignores None values in override."""
        resolver = ConfigResolver(test_domain)
        base = {"a": 1, "b": 2}
        override = {"a": None, "b": 20}

        result = resolver._merge_configs(base, override)

        assert result["a"] == 1  # None is ignored
        assert result["b"] == 20

    def test_merge_adds_new_keys(self, test_domain):
        """Merge adds new keys from override."""
        resolver = ConfigResolver(test_domain)
        base = {"a": 1}
        override = {"b": 2}

        result = resolver._merge_configs(base, override)

        assert result["a"] == 1
        assert result["b"] == 2

    def test_merge_does_not_modify_original(self, test_domain):
        """Merge does not modify the original dictionaries."""
        resolver = ConfigResolver(test_domain)
        base = {"a": 1, "b": 2}
        override = {"b": 20}

        resolver._merge_configs(base, override)

        assert base["b"] == 2  # Original unchanged


class TestConfigResolverCommandHandler:
    """Tests for ConfigResolver with command handlers."""

    def test_resolves_command_handler_config(self, test_domain):
        """ConfigResolver works with command handlers."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_profile=SubscriptionProfile.PRODUCTION,
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(OrderCommandHandler)

        assert config.subscription_type == SubscriptionType.STREAM
        assert config.messages_per_tick == 100

    def test_command_handler_meta_config(self, test_domain):
        """Command handler Meta config is applied."""

        @test_domain.command_handler(
            part_of=Order,
            subscription_config={"messages_per_tick": 75},
        )
        class OrderCommandHandler(BaseCommandHandler):
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver.resolve(OrderCommandHandler)

        assert config.messages_per_tick == 75


class TestConfigResolverHandlerWithNoMeta:
    """Tests for handler with no meta_ attribute."""

    def test_get_handler_meta_config_returns_empty_for_no_meta(self, test_domain):
        """_get_handler_meta_config returns empty dict when handler has no meta_."""

        class NoMetaHandler:
            pass

        resolver = ConfigResolver(test_domain)
        config = resolver._get_handler_meta_config(NoMetaHandler)

        assert config == {}


class TestConfigResolverUnknownProfileAndType:
    """Tests for unknown profile and subscription type resolution."""

    def test_resolve_unknown_profile_string_falls_back(self, test_domain, caplog):
        """_resolve_profile logs warning and returns PRODUCTION for unknown profile string."""
        resolver = ConfigResolver(test_domain)

        with caplog.at_level(
            logging.WARNING, logger="protean.server.subscription.config_resolver"
        ):
            result = resolver._resolve_profile("nonexistent_profile")

        assert result == SubscriptionProfile.PRODUCTION
        assert any(
            "Unknown subscription profile" in record.message
            for record in caplog.records
        )

    def test_resolve_non_string_non_enum_profile_falls_back(self, test_domain):
        """_resolve_profile returns PRODUCTION for non-string, non-enum input."""
        resolver = ConfigResolver(test_domain)

        result = resolver._resolve_profile(12345)  # type: ignore
        assert result == SubscriptionProfile.PRODUCTION

    def test_resolve_unknown_subscription_type_string_falls_back(
        self, test_domain, caplog
    ):
        """_resolve_subscription_type logs warning and returns EVENT_STORE for unknown type string."""
        resolver = ConfigResolver(test_domain)

        with caplog.at_level(
            logging.WARNING, logger="protean.server.subscription.config_resolver"
        ):
            result = resolver._resolve_subscription_type("nonexistent_type")

        assert result == SubscriptionType.EVENT_STORE
        assert any(
            "Unknown subscription type" in record.message for record in caplog.records
        )

    def test_resolve_non_string_non_enum_subscription_type_falls_back(
        self, test_domain
    ):
        """_resolve_subscription_type returns EVENT_STORE for non-string, non-enum input."""
        resolver = ConfigResolver(test_domain)

        result = resolver._resolve_subscription_type(12345)  # type: ignore
        assert result == SubscriptionType.EVENT_STORE


class TestConfigResolverDebugLogging:
    """Tests for debug logging in configuration resolution."""

    def test_logs_debug_messages_during_resolution(self, test_domain, caplog):
        """Debug messages are logged during configuration resolution."""

        @test_domain.event_handler(part_of=Order)
        class TestHandler(BaseEventHandler):
            pass

        resolver = ConfigResolver(test_domain)
        # Specify the logger name to ensure we capture debug logs from the specific module
        with caplog.at_level(
            logging.DEBUG, logger="protean.server.subscription.config_resolver"
        ):
            resolver.resolve(TestHandler)

        # Check that debug messages were logged
        debug_messages = [
            r.message for r in caplog.records if r.levelno == logging.DEBUG
        ]
        assert any(
            "Resolving subscription configuration" in msg for msg in debug_messages
        )
        assert any("Final resolved configuration" in msg for msg in debug_messages)
