"""Tests for subscription configuration access through Domain object.

This module tests that subscription configuration is properly accessible
through the Domain object after initialization.

Note: Tests for the subscription configuration structure and defaults
are in tests/config/test_server_subscription_config.py
"""

import pytest

from protean.domain import Domain


class TestDomainSubscriptionConfig:
    """Tests for subscription configuration access through Domain object."""

    def test_domain_has_server_subscription_config(self, test_domain):
        """Domain should have server subscription configuration."""
        assert "server" in test_domain.config
        assert "default_subscription_type" in test_domain.config["server"]
        assert "default_subscription_profile" in test_domain.config["server"]
        assert "subscriptions" in test_domain.config["server"]

    def test_domain_subscription_config_defaults(self, test_domain):
        """Domain should have default subscription configuration values."""
        server_config = test_domain.config["server"]
        assert server_config["default_subscription_type"] == "event_store"
        assert server_config["default_subscription_profile"] is None
        assert server_config["messages_per_tick"] == 100
        assert server_config["subscriptions"] == {}

    def test_domain_stream_subscription_config(self, test_domain):
        """Domain should have stream_subscription configuration."""
        stream_config = test_domain.config["server"]["stream_subscription"]
        assert "blocking_timeout_ms" in stream_config
        assert "max_retries" in stream_config
        assert "retry_delay_seconds" in stream_config
        assert "enable_dlq" in stream_config

    def test_domain_event_store_subscription_config(self, test_domain):
        """Domain should have event_store_subscription configuration."""
        event_store_config = test_domain.config["server"]["event_store_subscription"]
        assert "position_update_interval" in event_store_config

    @pytest.mark.no_test_domain
    def test_domain_can_override_subscription_config(self):
        """Domain can override subscription configuration."""
        domain = Domain(name="TestOverride")
        domain.config["server"]["default_subscription_type"] = "stream"
        domain.config["server"]["default_subscription_profile"] = "fast"
        domain.config["server"]["subscriptions"]["TestHandler"] = {
            "profile": "production",
            "stream_category": "test",
        }

        assert domain.config["server"]["default_subscription_type"] == "stream"
        assert domain.config["server"]["default_subscription_profile"] == "fast"
        assert (
            domain.config["server"]["subscriptions"]["TestHandler"]["profile"]
            == "production"
        )
