"""Tests for server subscription configuration in domain config.

This module tests the subscription configuration structure and defaults
in the server section of domain configuration.
"""

import tempfile
from pathlib import Path

import pytest

from protean.domain.config import Config2, _default_config


class TestServerSubscriptionConfigDefaults:
    """Tests for default subscription configuration values."""

    def test_default_subscription_type_is_event_store(self):
        """Default subscription type should be 'event_store' for simplicity.

        event_store is simpler and good for getting started. Users should
        explicitly switch to 'stream' for production with scaling needs.
        """
        config = _default_config()
        assert config["server"]["default_subscription_type"] == "event_store"

    def test_default_subscription_profile_is_none(self):
        """Default subscription profile should be None (use hardcoded defaults)."""
        config = _default_config()
        assert config["server"]["default_subscription_profile"] is None

    def test_default_messages_per_tick(self):
        """Default messages_per_tick should be 100."""
        config = _default_config()
        assert config["server"]["messages_per_tick"] == 100

    def test_default_tick_interval(self):
        """Default tick_interval should be 0 (pure blocking reads)."""
        config = _default_config()
        assert config["server"]["tick_interval"] == 0

    def test_default_stream_subscription_settings(self):
        """Stream subscription should have default settings."""
        config = _default_config()
        stream_config = config["server"]["stream_subscription"]
        assert stream_config["blocking_timeout_ms"] == 100
        assert stream_config["max_retries"] == 3
        assert stream_config["retry_delay_seconds"] == 1
        assert stream_config["enable_dlq"] is True

    def test_default_event_store_subscription_settings(self):
        """Event store subscription should have default settings."""
        config = _default_config()
        event_store_config = config["server"]["event_store_subscription"]
        assert event_store_config["position_update_interval"] == 10

    def test_default_subscriptions_is_empty_dict(self):
        """Handler-specific subscriptions should be empty by default."""
        config = _default_config()
        assert config["server"]["subscriptions"] == {}


class TestSubscriptionConfigFromDict:
    """Tests for loading subscription configuration from dictionary."""

    def test_load_custom_default_subscription_type(self):
        """Custom default_subscription_type can be loaded from dict."""
        config_dict = _default_config()
        config_dict["server"]["default_subscription_type"] = "stream"
        config = Config2.load_from_dict(config_dict)
        assert config["server"]["default_subscription_type"] == "stream"

    def test_load_custom_default_subscription_profile(self):
        """Custom default_subscription_profile can be loaded from dict."""
        config_dict = _default_config()
        config_dict["server"]["default_subscription_profile"] = "production"
        config = Config2.load_from_dict(config_dict)
        assert config["server"]["default_subscription_profile"] == "production"

    def test_load_custom_stream_subscription_settings(self):
        """Custom stream_subscription settings can be loaded from dict."""
        config_dict = _default_config()
        config_dict["server"]["stream_subscription"]["blocking_timeout_ms"] = 5000
        config_dict["server"]["stream_subscription"]["max_retries"] = 5
        config = Config2.load_from_dict(config_dict)
        assert config["server"]["stream_subscription"]["blocking_timeout_ms"] == 5000
        assert config["server"]["stream_subscription"]["max_retries"] == 5

    def test_load_handler_specific_subscriptions(self):
        """Handler-specific subscriptions can be loaded from dict."""
        config_dict = _default_config()
        config_dict["server"]["subscriptions"] = {
            "OrderEventHandler": {
                "profile": "production",
                "stream_category": "order",
            },
            "NotificationHandler": {
                "profile": "fast",
                "messages_per_tick": 200,
            },
        }
        config = Config2.load_from_dict(config_dict)
        assert (
            config["server"]["subscriptions"]["OrderEventHandler"]["profile"]
            == "production"
        )
        assert (
            config["server"]["subscriptions"]["NotificationHandler"][
                "messages_per_tick"
            ]
            == 200
        )


class TestSubscriptionConfigFromToml:
    """Tests for loading subscription configuration from TOML files."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for test config files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_load_subscription_config_from_toml(self, temp_config_dir):
        """Subscription config can be loaded from TOML file."""
        toml_content = """
[server]
default_subscription_type = "stream"
default_subscription_profile = "production"
messages_per_tick = 50

[server.stream_subscription]
blocking_timeout_ms = 5000
max_retries = 5

[server.subscriptions.OrderEventHandler]
profile = "production"
stream_category = "order"
"""
        config_file = temp_config_dir / "domain.toml"
        config_file.write_text(toml_content)

        config = Config2.load_from_path(str(temp_config_dir))
        assert config["server"]["default_subscription_type"] == "stream"
        assert config["server"]["default_subscription_profile"] == "production"
        assert config["server"]["messages_per_tick"] == 50
        assert config["server"]["stream_subscription"]["blocking_timeout_ms"] == 5000
        assert (
            config["server"]["subscriptions"]["OrderEventHandler"]["profile"]
            == "production"
        )

    def test_load_partial_subscription_config(self, temp_config_dir):
        """Partial subscription config merges with defaults."""
        toml_content = """
[server]
default_subscription_type = "stream"
"""
        config_file = temp_config_dir / "domain.toml"
        config_file.write_text(toml_content)

        config = Config2.load_from_path(str(temp_config_dir))
        # Specified value should be used
        assert config["server"]["default_subscription_type"] == "stream"
        # Unspecified values should use defaults
        assert config["server"]["default_subscription_profile"] is None
        assert config["server"]["messages_per_tick"] == 100

    def test_load_multiple_handler_subscriptions(self, temp_config_dir):
        """Multiple handler-specific subscriptions can be loaded."""
        toml_content = """
[server.subscriptions.OrderEventHandler]
profile = "production"
stream_category = "order"

[server.subscriptions.PaymentHandler]
profile = "fast"
messages_per_tick = 200

[server.subscriptions.AnalyticsProjector]
profile = "projection"
stream_category = "$all"
"""
        config_file = temp_config_dir / "domain.toml"
        config_file.write_text(toml_content)

        config = Config2.load_from_path(str(temp_config_dir))
        subscriptions = config["server"]["subscriptions"]
        assert len(subscriptions) == 3
        assert subscriptions["OrderEventHandler"]["profile"] == "production"
        assert subscriptions["PaymentHandler"]["messages_per_tick"] == 200
        assert subscriptions["AnalyticsProjector"]["stream_category"] == "$all"


class TestSubscriptionConfigValidValues:
    """Tests for valid subscription configuration values."""

    def test_stream_is_valid_subscription_type(self):
        """'stream' is a valid subscription type."""
        config_dict = _default_config()
        config_dict["server"]["default_subscription_type"] = "stream"
        config = Config2.load_from_dict(config_dict)
        assert config["server"]["default_subscription_type"] == "stream"

    def test_event_store_is_valid_subscription_type(self):
        """'event_store' is a valid subscription type."""
        config_dict = _default_config()
        config_dict["server"]["default_subscription_type"] = "event_store"
        config = Config2.load_from_dict(config_dict)
        assert config["server"]["default_subscription_type"] == "event_store"

    @pytest.mark.parametrize(
        "profile", ["production", "fast", "batch", "debug", "projection"]
    )
    def test_valid_profiles_can_be_set(self, profile):
        """All valid profile names can be set."""
        config_dict = _default_config()
        config_dict["server"]["default_subscription_profile"] = profile
        config = Config2.load_from_dict(config_dict)
        assert config["server"]["default_subscription_profile"] == profile


class TestHandlerSpecificSubscriptionConfig:
    """Tests for handler-specific subscription configuration options."""

    def test_handler_subscription_with_profile_only(self):
        """Handler subscription can specify just a profile."""
        config_dict = _default_config()
        config_dict["server"]["subscriptions"] = {
            "TestHandler": {"profile": "production"},
        }
        config = Config2.load_from_dict(config_dict)
        assert (
            config["server"]["subscriptions"]["TestHandler"]["profile"] == "production"
        )

    def test_handler_subscription_with_stream_category(self):
        """Handler subscription can specify a stream_category."""
        config_dict = _default_config()
        config_dict["server"]["subscriptions"] = {
            "TestHandler": {"stream_category": "custom::stream"},
        }
        config = Config2.load_from_dict(config_dict)
        assert (
            config["server"]["subscriptions"]["TestHandler"]["stream_category"]
            == "custom::stream"
        )

    def test_handler_subscription_with_custom_config_values(self):
        """Handler subscription can specify custom config values."""
        config_dict = _default_config()
        config_dict["server"]["subscriptions"] = {
            "TestHandler": {
                "messages_per_tick": 50,
                "max_retries": 5,
                "retry_delay_seconds": 2,
                "enable_dlq": False,
            },
        }
        config = Config2.load_from_dict(config_dict)
        handler_config = config["server"]["subscriptions"]["TestHandler"]
        assert handler_config["messages_per_tick"] == 50
        assert handler_config["max_retries"] == 5
        assert handler_config["enable_dlq"] is False

    def test_handler_subscription_with_all_options(self):
        """Handler subscription can specify all available options."""
        config_dict = _default_config()
        config_dict["server"]["subscriptions"] = {
            "OrderEventHandler": {
                "profile": "production",
                "subscription_type": "stream",
                "stream_category": "order",
                "messages_per_tick": 100,
                "max_retries": 5,
            },
        }
        config = Config2.load_from_dict(config_dict)
        handler_config = config["server"]["subscriptions"]["OrderEventHandler"]
        assert handler_config["profile"] == "production"
        assert handler_config["subscription_type"] == "stream"
        assert handler_config["stream_category"] == "order"
        assert handler_config["messages_per_tick"] == 100
