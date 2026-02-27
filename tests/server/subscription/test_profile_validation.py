"""Tests for Finding #8: invalid subscription profile raises ConfigurationError.

_resolve_profile() must raise ConfigurationError for unknown profile names
instead of silently falling back to PRODUCTION.
"""

import pytest

from protean.exceptions import ConfigurationError
from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import SubscriptionProfile


class TestProfileValidation:
    """Tests that invalid profile names are rejected with a clear error."""

    def test_valid_profile_string_resolves(self, test_domain):
        """A valid profile name (case-insensitive) resolves correctly."""
        resolver = ConfigResolver(test_domain)

        assert resolver._resolve_profile("production") == SubscriptionProfile.PRODUCTION
        assert resolver._resolve_profile("FAST") == SubscriptionProfile.FAST
        assert resolver._resolve_profile("Debug") == SubscriptionProfile.DEBUG
        assert resolver._resolve_profile("batch") == SubscriptionProfile.BATCH
        assert resolver._resolve_profile("projection") == SubscriptionProfile.PROJECTION

    def test_valid_profile_enum_passes_through(self, test_domain):
        """A SubscriptionProfile enum value is returned as-is."""
        resolver = ConfigResolver(test_domain)

        for profile in SubscriptionProfile:
            assert resolver._resolve_profile(profile) is profile

    def test_invalid_profile_string_raises_error(self, test_domain):
        """An unrecognized profile name raises ConfigurationError."""
        resolver = ConfigResolver(test_domain)

        with pytest.raises(ConfigurationError) as exc:
            resolver._resolve_profile("nonexistent")

        msg = str(exc.value)
        assert "Unknown subscription profile" in msg
        assert "nonexistent" in msg

    def test_error_message_lists_valid_profiles(self, test_domain):
        """The error message enumerates all valid profile names."""
        resolver = ConfigResolver(test_domain)

        with pytest.raises(ConfigurationError) as exc:
            resolver._resolve_profile("invalid_profile")

        msg = str(exc.value)
        for profile in SubscriptionProfile:
            assert profile.value in msg

    def test_empty_string_profile_raises_error(self, test_domain):
        """An empty string is not a valid profile."""
        resolver = ConfigResolver(test_domain)

        with pytest.raises(ConfigurationError, match="Unknown subscription profile"):
            resolver._resolve_profile("")

    def test_non_string_non_enum_falls_back_to_production(self, test_domain):
        """Non-string, non-enum input falls back to PRODUCTION (type guard)."""
        resolver = ConfigResolver(test_domain)

        # This branch handles unexpected types gracefully
        result = resolver._resolve_profile(12345)  # type: ignore
        assert result == SubscriptionProfile.PRODUCTION
