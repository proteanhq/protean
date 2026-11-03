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

    @pytest.mark.parametrize(
        "profile", ["nonexistent_profile", 12345], ids=["unknown_name", "non_string"]
    )
    def test_profile_defaults_unknown_profile_raises(self, test_domain, profile):
        """_profile_defaults raises ConfigurationError for a name it cannot find.

        A non-string, non-enum value does not fall back to a default profile:
        the registry lookup stringifies it, finds no match, and fails fast.
        """
        resolver = ConfigResolver(test_domain)

        with pytest.raises(ConfigurationError, match="Unknown subscription profile"):
            resolver._profile_defaults(profile)
