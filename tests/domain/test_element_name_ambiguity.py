"""Tests for Finding #7: ambiguous element name resolution.

When multiple elements of the same type share a class name (e.g. orders.Status
and payments.Status), _get_element_by_name() must fail explicitly instead of
returning the first match non-deterministically.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.utils import DomainObjects, fqn


class StatusA(BaseAggregate):
    label: String()


class StatusB(BaseAggregate):
    label: String()


class TestAmbiguousElementNameLookup:
    """Tests for _get_element_by_name() with ambiguous names."""

    def test_single_element_resolves_normally(self, test_domain):
        """A unique name resolves to the single matching element."""
        test_domain.register(StatusA)
        test_domain.init(traverse=False)

        record = test_domain._get_element_by_name((DomainObjects.AGGREGATE,), "StatusA")
        assert record.cls is StatusA

    def test_ambiguous_name_raises_configuration_error(self, test_domain):
        """When two elements of the same type share a class name, lookup fails."""
        StatusB.__name__ = "StatusA"
        StatusB.__module__ = "payments.models"

        test_domain.register(StatusA)
        test_domain.register(StatusB)
        test_domain.init(traverse=False)

        with pytest.raises(ConfigurationError) as exc:
            test_domain._get_element_by_name((DomainObjects.AGGREGATE,), "StatusA")

        error_msg = exc.value.args[0]["element"]
        assert "Multiple elements" in error_msg
        assert "StatusA" in error_msg
        assert "fully qualified name" in error_msg

        # Reset for other tests
        StatusB.__name__ = "StatusB"
        StatusB.__module__ = __name__

    def test_same_name_different_type_resolves_correctly(self, test_domain):
        """Elements with the same name but different types do not conflict."""
        from protean.core.event import BaseEvent

        class Notification(BaseAggregate):
            message: String()

        class NotificationEvent(BaseEvent):
            message: String()

        # Give the event the same simple name as the aggregate
        NotificationEvent.__name__ = "Notification"

        test_domain.register(Notification)
        test_domain.register(NotificationEvent, part_of=Notification)
        test_domain.init(traverse=False)

        # Should resolve unambiguously since only one is an AGGREGATE
        record = test_domain._get_element_by_name(
            (DomainObjects.AGGREGATE,), "Notification"
        )
        assert record.cls is Notification

    def test_nonexistent_name_raises_configuration_error(self, test_domain):
        """A name that matches nothing raises ConfigurationError."""
        test_domain.register(StatusA)
        test_domain.init(traverse=False)

        with pytest.raises(ConfigurationError) as exc:
            test_domain._get_element_by_name((DomainObjects.AGGREGATE,), "NonExistent")

        assert "not registered" in exc.value.args[0]["element"]

    def test_fqn_lookup_bypasses_ambiguity(self, test_domain):
        """Fully qualified name lookup works even when simple names are ambiguous."""
        StatusB.__name__ = "StatusA"
        StatusB.__module__ = "payments.models"

        test_domain.register(StatusA)
        test_domain.register(StatusB)
        test_domain.init(traverse=False)

        # FQN lookup should still work
        record = test_domain._get_element_by_fully_qualified_name(
            (DomainObjects.AGGREGATE,), fqn(StatusA)
        )
        assert record.cls is StatusA

        # Reset
        StatusB.__name__ = "StatusB"
        StatusB.__module__ = __name__

    def test_ambiguous_error_lists_all_qualified_names(self, test_domain):
        """The error message includes all conflicting fully qualified names."""
        StatusB.__name__ = "StatusA"
        StatusB.__module__ = "payments.models"

        test_domain.register(StatusA)
        test_domain.register(StatusB)
        test_domain.init(traverse=False)

        with pytest.raises(ConfigurationError) as exc:
            test_domain._get_element_by_name((DomainObjects.AGGREGATE,), "StatusA")

        error_msg = exc.value.args[0]["element"]
        # Both FQ names should appear in the error
        assert fqn(StatusA) in error_msg
        assert fqn(StatusB) in error_msg

        # Reset
        StatusB.__name__ = "StatusB"
        StatusB.__module__ = __name__
