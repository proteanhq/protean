"""Tests that the resolver rejects unknown subscription profile names.

`ConfigResolver._profile_defaults` looks a profile up (built-in or custom) in
the merged registry and raises `ConfigurationError` when the name is not found,
instead of silently falling back to a default profile.
"""

import pytest

from protean.exceptions import ConfigurationError
from protean.server.subscription.config_resolver import ConfigResolver


class TestProfileValidation:
    """The resolver fails fast on a profile name it cannot resolve."""

    def test_profile_defaults_unknown_name_raises_error(self, test_domain):
        """_profile_defaults raises ConfigurationError for an unknown profile name."""
        resolver = ConfigResolver(test_domain)

        with pytest.raises(ConfigurationError, match="Unknown subscription profile"):
            resolver._profile_defaults("nonexistent_profile")

    def test_profile_defaults_non_string_non_enum_raises(self, test_domain):
        """A non-string, non-enum profile no longer silently falls back to a default.

        The old _resolve_profile returned PRODUCTION for such input; the registry
        lookup instead stringifies it, finds no match, and fails fast.
        """
        resolver = ConfigResolver(test_domain)

        with pytest.raises(ConfigurationError, match="Unknown subscription profile"):
            resolver._profile_defaults(12345)  # type: ignore
