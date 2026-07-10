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
from protean.domain import Domain
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
        with pytest.warns(
            RemovedInProtean10Warning,
            match=r"Use `event_sourced` instead\. Will be removed in v1\.0\.0",
        ):

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

    def test_canonical_wins_when_both_supplied_reverse(self, test_domain):
        # The reverse precedence: canonical `event_sourced=False` must win over
        # `is_event_sourced=True`, guarding against a "canonical only overrides
        # when truthy" bug that would let the alias win here.
        with pytest.warns(RemovedInProtean10Warning):

            @test_domain.aggregate(event_sourced=False, is_event_sourced=True)
            class Person(BaseAggregate):
                name: String()

        assert Person.meta_.is_event_sourced is False

    def test_non_bool_value_coerced_to_bool(self, test_domain):
        # `event_sourced=None` must land on `meta_` as the documented `bool`
        # (False), not leak `None` onto the IR wire node.
        @test_domain.aggregate(event_sourced=None)
        class Person(BaseAggregate):
            name: String()

        assert Person.meta_.is_event_sourced is False


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

    @pytest.mark.no_test_domain
    def test_re_registering_same_class_with_canonical_clears_marker(self):
        # The same aggregate class object can be shared across bounded contexts.
        # Registering it with the alias in one domain must not leave a stale
        # marker that makes a second domain (using the canonical spelling)
        # falsely report the already-migrated code as deprecated.
        widget = _alias_aggregate()

        domain_a = Domain(name="AliasDomain", root_path=__file__)
        with pytest.warns(RemovedInProtean10Warning):
            domain_a.register(widget, is_event_sourced=True)
        domain_a.check(traverse=False)

        domain_b = Domain(name="CanonicalDomain", root_path=__file__)
        domain_b.register(widget, event_sourced=True)
        report = domain_b.check(traverse=False)

        diagnostics = [
            d for d in report["diagnostics"] if d["code"] == "DEPRECATED_OPTION"
        ]
        assert diagnostics == []


def _alias_aggregate() -> type[BaseAggregate]:
    """Build a fresh aggregate class so each diagnostic test registers its own."""

    class Widget(BaseAggregate):
        name: String()

    return Widget
