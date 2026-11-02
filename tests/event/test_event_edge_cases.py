"""Tests for building events from template dicts and for unregistered events.

- An event rejects a positional argument that is not a dict.
- An event merges a positional template dict with keyword arguments.
- An event class that is not registered with a domain cannot be instantiated.
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


class UnregisteredEvent(BaseEvent):
    data: str | None = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestEventTemplateDictPattern:
    def test_non_dict_positional_arg_raises_type_error(self, test_domain):
        """An event raises TypeError when its positional argument is not a dict."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        with pytest.raises(TypeError) as exc_info:
            OrderPlaced("not a dict")
        assert str(exc_info.value) == (
            "Positional argument not a dict passed must be a dict. "
            "This argument serves as a template for loading common values."
        )

    def test_dict_positional_arg_merged_with_kwargs(self, test_domain):
        """An event takes field values from both a template dict and kwargs."""
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        event = OrderPlaced({"order_id": "123"}, name="Test")
        assert event.order_id == "123"
        assert event.name == "Test"


class TestUnregisteredEvent:
    def test_unregistered_event_raises_configuration_error(self):
        """An event class not registered with a domain raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            UnregisteredEvent(data="test")
        assert exc_info.value.args[0] == (
            "`UnregisteredEvent` should be registered with a domain"
        )
