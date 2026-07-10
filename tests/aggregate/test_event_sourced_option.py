"""Tests for the ``event_sourced`` aggregate option and its deprecated
``is_event_sourced`` alias (#1107).

``event_sourced`` is the canonical, user-facing spelling. ``is_event_sourced``
is retained as a deprecated alias that maps to the same internal
``meta_.is_event_sourced`` storage key. The alias emits a
``RemovedInProtean10Warning`` and surfaces a ``DEPRECATED_OPTION`` diagnostic
from ``domain.check()``.
"""

import warnings

import pytest

from protean._deprecation import (
    ProteanDeprecationWarning,
    RemovedInProtean10Warning,
)
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class TestEventSourcedCanonicalOption:
    def test_event_sourced_true_sets_internal_flag(self, test_domain):
        @test_domain.aggregate(event_sourced=True)
        class Person(BaseAggregate):
            name: String()
            age: Integer()

        assert Person.meta_.is_event_sourced is True

    def test_event_sourced_false_sets_internal_flag(self, test_domain):
        @test_domain.aggregate(event_sourced=False)
        class Person(BaseAggregate):
            name: String()

        assert Person.meta_.is_event_sourced is False

    def test_event_sourced_via_register(self, test_domain):
        class Person(BaseAggregate):
            name: String()

        test_domain.register(Person, event_sourced=True)

        assert Person.meta_.is_event_sourced is True

    def test_event_sourced_emits_no_deprecation_warning(self, test_domain):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            @test_domain.aggregate(event_sourced=True)
            class Person(BaseAggregate):
                name: String()

        assert not any(
            issubclass(w.category, ProteanDeprecationWarning) for w in caught
        )

    def test_no_option_emits_no_deprecation_warning(self, test_domain):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            @test_domain.aggregate
            class Person(BaseAggregate):
                name: String()

        assert not any(
            issubclass(w.category, ProteanDeprecationWarning) for w in caught
        )


class TestIsEventSourcedAlias:
    def test_alias_still_sets_internal_flag(self, test_domain):
        with pytest.warns(RemovedInProtean10Warning):

            @test_domain.aggregate(is_event_sourced=True)
            class Person(BaseAggregate):
                name: String()

        assert Person.meta_.is_event_sourced is True

    def test_alias_via_register_warns(self, test_domain):
        class Person(BaseAggregate):
            name: String()

        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(Person, is_event_sourced=True)

        assert Person.meta_.is_event_sourced is True

    def test_canonical_wins_when_both_supplied(self, test_domain):
        # Alias still warns, but the canonical `event_sourced` value takes
        # precedence over the alias.
        with pytest.warns(RemovedInProtean10Warning):

            @test_domain.aggregate(event_sourced=True, is_event_sourced=False)
            class Person(BaseAggregate):
                name: String()

        assert Person.meta_.is_event_sourced is True


class TestDeprecatedOptionDiagnostic:
    def test_alias_yields_deprecated_option_diagnostic(self, test_domain):
        with pytest.warns(RemovedInProtean10Warning):
            test_domain.register(_alias_aggregate(), is_event_sourced=True)

        report = test_domain.check(traverse=False)

        diagnostics = [
            d for d in report["diagnostics"] if d["code"] == "DEPRECATED_OPTION"
        ]
        assert len(diagnostics) == 1
        assert diagnostics[0]["level"] == "info"
        assert "is_event_sourced" in diagnostics[0]["message"]

    def test_canonical_yields_no_deprecated_option_diagnostic(self, test_domain):
        test_domain.register(_alias_aggregate(), event_sourced=True)

        report = test_domain.check(traverse=False)

        diagnostics = [
            d for d in report["diagnostics"] if d["code"] == "DEPRECATED_OPTION"
        ]
        assert diagnostics == []


def _alias_aggregate() -> type[BaseAggregate]:
    """Build a fresh aggregate class so each diagnostic test registers its own."""

    class Widget(BaseAggregate):
        name: String()

    return Widget
