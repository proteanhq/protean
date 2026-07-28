"""Tests for subscription configuration resolution.

This module tests the ConfigResolver class which resolves subscription
configuration from multiple sources with a defined priority hierarchy.
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
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
    order_id: Identifier(identifier=True)
    customer_name: String()


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
    """Tests for unknown subscription type resolution.

    Unknown profile-name resolution is covered in test_profile_validation.py.
    """

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


class TestConfigResolverCustomProfiles:
    """End-to-end resolution of custom `[server.profiles.<name>]` profiles."""

    def test_custom_profile_via_default_subscription_profile(self, test_domain):
        """A custom profile named by default_subscription_profile resolves end-to-end."""
        test_domain.config["server"]["profiles"]["myfast"] = {
            "inherits": "fast",
            "messages_per_tick": 25,
        }
        test_domain.config["server"]["default_subscription_profile"] = "myfast"
        # The profile sits at priority 6; clear the priority-5 server-level
        # defaults that would otherwise shadow the fields it should govern.
        test_domain.config["server"].pop("messages_per_tick", None)
        test_domain.config["server"].pop("default_subscription_type", None)
        test_domain.config["server"]["stream_subscription"] = {}

        @test_domain.event_handler(part_of=Order)
        class PlainHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(PlainHandler)

        fast = PROFILE_DEFAULTS[SubscriptionProfile.FAST]
        # The one override plus the rest of fast's defaults carried by inheritance.
        assert config.messages_per_tick == 25
        assert config.subscription_type == fast["subscription_type"]
        assert config.blocking_timeout_ms == fast["blocking_timeout_ms"]
        assert config.max_retries == fast["max_retries"]

    def test_custom_profile_via_handler_server_config(self, test_domain):
        """A custom profile named in server.subscriptions.<Handler> resolves."""
        test_domain.config["server"]["profiles"]["myfast"] = {
            "inherits": "fast",
            "messages_per_tick": 25,
        }
        test_domain.config["server"]["subscriptions"]["ServerProfHandler"] = {
            "profile": "myfast",
        }

        @test_domain.event_handler(part_of=Order)
        class ServerProfHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(ServerProfHandler)

        assert config.messages_per_tick == 25
        assert (
            config.blocking_timeout_ms
            == PROFILE_DEFAULTS[SubscriptionProfile.FAST]["blocking_timeout_ms"]
        )

    def test_custom_profile_via_handler_meta_profile(self, test_domain):
        """A custom profile named in a handler's Meta subscription_profile resolves."""
        test_domain.config["server"]["profiles"]["myfast"] = {
            "inherits": "fast",
            "messages_per_tick": 25,
        }

        @test_domain.event_handler(part_of=Order, subscription_profile="myfast")
        class MetaProfHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(MetaProfHandler)

        assert config.messages_per_tick == 25

    def test_same_level_override_beats_custom_profile_defaults(self, test_domain):
        """An explicit field at the same level wins over the custom profile's default."""
        test_domain.config["server"]["profiles"]["myfast"] = {
            "inherits": "fast",
            "messages_per_tick": 25,
        }
        test_domain.config["server"]["subscriptions"]["OverrideHandler"] = {
            "profile": "myfast",
            "messages_per_tick": 77,
        }

        @test_domain.event_handler(part_of=Order)
        class OverrideHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(OverrideHandler)

        # The same-level explicit override wins on its field...
        assert config.messages_per_tick == 77
        # ...but the profile still had to be expanded: max_retries is a field the
        # profile inherits from fast (2) and it differs from the priority-5 server
        # default (3), so seeing 2 proves the custom profile's defaults were
        # applied and then only messages_per_tick was overridden. If profile
        # expansion had no-op'd, max_retries would be 3.
        fast = PROFILE_DEFAULTS[SubscriptionProfile.FAST]
        assert config.max_retries == fast["max_retries"] == 2

    def test_higher_level_custom_profile_beats_lower_level(self, test_domain):
        """When a profile is named at two levels, only the higher level's applies.

        Profiles do not stack: the highest-priority level that names one wins
        outright, and lower-level profiles contribute nothing. Here `lowprof`
        (inherits fast) is named at the per-handler server config and `highprof`
        (inherits batch) at the handler's Meta. The two inherit fields that
        differ (max_retries 2 vs 5, blocking_timeout_ms 100 vs 10000), so the
        resolved values pin which profile actually applied — not just the
        overlapping messages_per_tick.
        """
        test_domain.config["server"]["profiles"]["lowprof"] = {
            "inherits": "fast",
            "messages_per_tick": 11,
        }
        test_domain.config["server"]["profiles"]["highprof"] = {
            "inherits": "batch",
            "messages_per_tick": 88,
        }
        test_domain.config["server"]["subscriptions"]["HighHandler"] = {
            "profile": "lowprof",
        }

        @test_domain.event_handler(part_of=Order, subscription_profile="highprof")
        class HighHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(HighHandler)

        fast = PROFILE_DEFAULTS[SubscriptionProfile.FAST]
        batch = PROFILE_DEFAULTS[SubscriptionProfile.BATCH]
        # highprof (Meta, priority 2-3) wins on the overlapping field...
        assert config.messages_per_tick == 88
        # ...and its inherited batch defaults surface, not lowprof's fast ones.
        assert config.max_retries == batch["max_retries"]
        assert config.blocking_timeout_ms == batch["blocking_timeout_ms"]
        assert config.max_retries != fast["max_retries"]
        assert config.blocking_timeout_ms != fast["blocking_timeout_ms"]

    def test_custom_profile_with_event_store_type(self, test_domain):
        """A custom profile carrying subscription_type as a string resolves to the enum."""
        test_domain.config["server"]["profiles"]["myproj"] = {
            "inherits": "projection",
            "subscription_type": "event_store",
            "position_update_interval": 3,
        }
        test_domain.config["server"]["default_subscription_profile"] = "myproj"
        # Clear the priority-5 event-store defaults so the priority-6 profile's
        # position_update_interval is what surfaces.
        test_domain.config["server"].pop("default_subscription_type", None)
        test_domain.config["server"]["event_store_subscription"] = {}

        @test_domain.event_handler(part_of=Order)
        class ProjHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(ProjHandler)

        # subscription_type given as a string in the profile resolves to the enum.
        assert config.subscription_type == SubscriptionType.EVENT_STORE
        assert config.position_update_interval == 3

    def test_undefined_profile_name_raises(self, test_domain):
        """Referencing a name that is neither built-in nor custom raises."""
        from protean.exceptions import ConfigurationError

        test_domain.config["server"]["default_subscription_profile"] = "ghost"

        @test_domain.event_handler(part_of=Order)
        class GhostHandler(BaseEventHandler):
            pass

        with pytest.raises(ConfigurationError):
            ConfigResolver(test_domain).resolve(GhostHandler)

    def test_invalid_profiles_section_fails_fast_on_resolve(self, test_domain):
        """An invalid [server.profiles] section raises even if the handler names no profile."""
        from protean.exceptions import ConfigurationError

        test_domain.config["server"]["profiles"]["production"] = {
            "messages_per_tick": 1,
        }

        @test_domain.event_handler(part_of=Order)
        class NoProfileHandler(BaseEventHandler):
            pass

        with pytest.raises(ConfigurationError):
            ConfigResolver(test_domain).resolve(NoProfileHandler)

    def test_builtin_profile_unchanged_when_profiles_absent(self, test_domain):
        """With no [server.profiles], a built-in profile resolves exactly as before."""
        test_domain.config["server"]["default_subscription_profile"] = "batch"
        test_domain.config["server"].pop("messages_per_tick", None)

        @test_domain.event_handler(part_of=Order)
        class BatchHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(BatchHandler)

        assert (
            config.messages_per_tick
            == PROFILE_DEFAULTS[SubscriptionProfile.BATCH]["messages_per_tick"]
        )

    def test_custom_profile_referenced_by_different_case_resolves(self, test_domain):
        """A profile registered lowercased resolves when referenced in another case.

        Registration lowercases the section name; a reference in a different case
        must still round-trip through `_profile_defaults` (which also lowercases).
        """
        test_domain.config["server"]["profiles"]["myfast"] = {
            "inherits": "fast",
            "messages_per_tick": 25,
        }
        test_domain.config["server"]["default_subscription_profile"] = "MyFast"
        # Clear the priority-5 defaults that would otherwise shadow the field.
        test_domain.config["server"].pop("messages_per_tick", None)
        test_domain.config["server"].pop("default_subscription_type", None)
        test_domain.config["server"]["stream_subscription"] = {}

        @test_domain.event_handler(part_of=Order)
        class CaseHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(CaseHandler)

        assert config.messages_per_tick == 25

    def test_custom_event_store_profile_dlq_is_sanitized(self, test_domain):
        """enable_dlq is forced off for an event_store custom profile, not left to raise.

        A profile that carries subscription_type=event_store with enable_dlq=True
        is sanitized to enable_dlq=False before the config is built; without that
        step SubscriptionConfig.validate would reject the combination.
        """
        test_domain.config["server"]["profiles"]["dlqproj"] = {
            "inherits": "projection",
            "subscription_type": "event_store",
            "enable_dlq": True,
        }
        test_domain.config["server"]["default_subscription_profile"] = "dlqproj"
        test_domain.config["server"].pop("default_subscription_type", None)
        test_domain.config["server"]["stream_subscription"] = {}

        @test_domain.event_handler(part_of=Order)
        class DlqProjHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(DlqProjHandler)

        assert config.subscription_type == SubscriptionType.EVENT_STORE
        assert config.enable_dlq is False


class TestConfigResolverRetention:
    """Resolution of the retention_maxlen field through the resolver.

    These tests guard the config_resolver `known_fields` filter: retention_maxlen
    is dropped before it reaches SubscriptionConfig if the filter omits it.
    """

    def test_builtin_profile_retention_survives_resolution(self, test_domain):
        """A built-in profile's retention_maxlen reaches the resolved config."""
        test_domain.config["server"]["profiles"]  # ensure the slot exists
        test_domain.config["server"]["subscriptions"]["RetHandler"] = {
            "profile": "production",
        }

        @test_domain.event_handler(part_of=Order)
        class RetHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(RetHandler)

        assert (
            config.retention_maxlen
            == PROFILE_DEFAULTS[SubscriptionProfile.PRODUCTION]["retention_maxlen"]
            == 100_000
        )

    def test_custom_profile_retention_survives_resolution(self, test_domain):
        """A custom profile's retention_maxlen flows through the known_fields filter.

        This is the binding oracle for the resolver gap: `myret` sets a value
        (42) that differs from every built-in default, so seeing 42 proves the
        per-profile retention value was neither dropped by the resolver filter
        nor shadowed by a default.
        """
        test_domain.config["server"]["profiles"]["myret"] = {
            "inherits": "production",
            "retention_maxlen": 42,
        }
        test_domain.config["server"]["subscriptions"]["MyRetHandler"] = {
            "profile": "myret",
        }

        @test_domain.event_handler(part_of=Order)
        class MyRetHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(MyRetHandler)

        assert config.retention_maxlen == 42

    def test_retention_defaults_off_without_profile(self, test_domain):
        """With no profile setting retention, the resolved config leaves it off."""

        @test_domain.event_handler(part_of=Order)
        class PlainRetHandler(BaseEventHandler):
            pass

        config = ConfigResolver(test_domain).resolve(PlainRetHandler)

        assert config.retention_maxlen is None
