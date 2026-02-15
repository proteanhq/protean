"""Tests for edge cases in core/event.py.

Covers uncovered lines:
- Line 58: AssertionError for non-dict positional arg
- Line 76: expected_version from template metadata
- Line 82: ConfigurationError when event not registered with domain
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Order(BaseAggregate):
    name: str | None = None


class OrderPlaced(BaseEvent):
    order_id: str | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestEventTemplateDictPattern:
    def test_non_dict_positional_arg_raises(self, test_domain):
        """Line 58: AssertionError for non-dict positional arg."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        with pytest.raises(AssertionError) as exc_info:
            OrderPlaced("not a dict")
        assert "must be a dict" in str(exc_info.value)

    def test_dict_positional_arg_merged(self, test_domain):
        """Positional dict merged with kwargs."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        event = OrderPlaced({"order_id": "123"}, name="Test")
        assert event.order_id == "123"
        assert event.name == "Test"


class TestEventExpectedVersion:
    def test_expected_version_from_template_dict(self, test_domain):
        """Line 76: expected_version from template_expected_version."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        # Create event with _expected_version in template dict
        template = {"order_id": "123", "_expected_version": 5}
        event = OrderPlaced(template)
        assert event._expected_version == 5

    def test_explicit_expected_version_overrides_template(self, test_domain):
        """Explicit kwarg takes precedence over template."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        template = {"order_id": "123", "_expected_version": 5}
        event = OrderPlaced(template, _expected_version=10)
        assert event._expected_version == 10


class TestEventModelPostInit:
    def test_unregistered_event_raises_configuration_error(self):
        """Line 82: ConfigurationError when event has no __type__."""
        with pytest.raises(
            ConfigurationError, match="should be registered with a domain"
        ):

            class UnregisteredEvent(BaseEvent):
                data: str | None = None

            UnregisteredEvent(data="test")
