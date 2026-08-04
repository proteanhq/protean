"""Every subscription config key must be documented.

A tuning option nobody can find is an option nobody uses. `SubscriptionConfig`
is the authoritative set of per-subscription settings, so each of its fields has
to appear in the server configuration reference, and each shipped profile has to
be named there too. These fail when someone adds a knob and forgets the docs.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from protean.server.subscription.profiles import (
    BUILTIN_PROFILE_NAMES,
    SubscriptionConfig,
)

# These read a markdown file and static metadata. Nothing here needs a domain,
# so skip the autouse fixture that builds one per test.
pytestmark = pytest.mark.no_test_domain

DOCS = Path(__file__).resolve().parents[2] / "docs"
CONFIG_REFERENCE = DOCS / "reference" / "server" / "configuration.md"
TUNING_GUIDE = DOCS / "guides" / "server" / "tuning-subscriptions.md"

CONFIG_FIELDS = sorted(f.name for f in dataclasses.fields(SubscriptionConfig))


@pytest.fixture(scope="module")
def reference_text() -> str:
    assert CONFIG_REFERENCE.is_file(), f"{CONFIG_REFERENCE} is missing"
    return CONFIG_REFERENCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide_text() -> str:
    assert TUNING_GUIDE.is_file(), f"{TUNING_GUIDE} is missing"
    return TUNING_GUIDE.read_text(encoding="utf-8")


class TestConfigKeysAreDocumented:
    def test_there_are_fields_to_check(self):
        # Without this, an import or refactor that empties the field list would
        # turn every parametrised case below into a silent pass.
        assert len(CONFIG_FIELDS) >= 10

    @pytest.mark.parametrize("field", CONFIG_FIELDS)
    def test_field_appears_in_the_configuration_reference(self, field, reference_text):
        assert field in reference_text, (
            f"`{field}` is a SubscriptionConfig option but does not appear in "
            f"docs/reference/server/configuration.md. Document it there."
        )


class TestProfilesAreDocumented:
    @pytest.mark.parametrize("profile", sorted(BUILTIN_PROFILE_NAMES))
    def test_profile_appears_in_the_configuration_reference(
        self, profile, reference_text
    ):
        assert profile in reference_text, (
            f"Built-in profile '{profile}' is not named in "
            f"docs/reference/server/configuration.md."
        )

    @pytest.mark.parametrize("profile", sorted(BUILTIN_PROFILE_NAMES))
    def test_profile_appears_in_the_tuning_guide(self, profile, guide_text):
        assert profile in guide_text, (
            f"Built-in profile '{profile}' is not named in the tuning guide, so "
            f"a reader choosing a profile would not know it exists."
        )


class TestTuningGuideCoversTheTuningFeatures:
    """The guide is the entry point for 5.2's features; keep it honest."""

    @pytest.mark.parametrize(
        "topic",
        [
            "subscription_profile",
            "server.profiles",
            "retention_maxlen",
            "circuit_breaker_threshold",
            "sequential_by",
            "protean subscriptions status",
        ],
    )
    def test_guide_covers(self, topic, guide_text):
        assert topic in guide_text, f"The tuning guide does not mention {topic!r}."


class TestCustomProfileFieldListIsCurrent:
    """The documented allowed-field list drifted from `PROFILE_FIELDS`.

    The reference listed 10 of the 12 fields a custom profile may set, omitting
    both circuit-breaker keys, so a user following it would think those could
    only be set per handler. The per-field test above did not catch it because
    the names appear elsewhere on the page; this one reads the actual list.
    """

    def test_every_allowed_field_appears_in_the_allowed_list(self, reference_text):
        from protean.server.subscription.profiles import PROFILE_FIELDS

        start = reference_text.index("**Allowed fields.**")
        end = reference_text.index("**Validation**", start)
        listed = reference_text[start:end]

        missing = sorted(f for f in PROFILE_FIELDS if f"`{f}`" not in listed)
        assert not missing, (
            "A custom profile may set these fields, but the 'Allowed fields' "
            f"paragraph in the reference does not list them: {missing}"
        )
