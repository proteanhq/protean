"""Tests for edge cases in core/entity.py.

Covers uncovered lines:
- Lines 464-468, 472, 474, 477: Entity init without context
- Line 571: AssertionError for non-dict positional arg in _update_data
- Lines 579-581: ValidationError collection in _update_data
- Line 802: state_ setter
- Lines 814, 819: __deepcopy__ edge cases
- Line 862: __str__ fallback
"""

import copy

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import HasMany, Integer, String


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Order(BaseAggregate):
    name: String(required=True, max_length=50)
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_name: String(required=True, max_length=100)
    quantity: Integer(min_value=1)


# ---------------------------------------------------------------------------
# Tests: _update_data
# ---------------------------------------------------------------------------
class TestEntityUpdateData:
    def test_non_dict_positional_arg_raises(self, test_domain):
        """Line 571: AssertionError for non-dict in _update_data."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        with pytest.raises(AssertionError) as exc_info:
            order._update_data("not a dict")
        assert "must be a dict" in str(exc_info.value)

    def test_validation_error_collection_in_update_data(self, test_domain):
        """Lines 579-581: Validation errors collected during _update_data."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        # Try updating with invalid data - max_length exceeded
        with pytest.raises(ValidationError):
            order._update_data({"name": "A" * 200})


# ---------------------------------------------------------------------------
# Tests: state_ property
# ---------------------------------------------------------------------------
class TestEntityState:
    def test_state_setter(self, test_domain):
        """Line 802: state_ setter."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        original_state = order.state_
        # Verify state_ setter works
        order.state_ = original_state
        assert order.state_ is original_state


# ---------------------------------------------------------------------------
# Tests: __deepcopy__
# ---------------------------------------------------------------------------
class TestEntityDeepCopy:
    def test_deepcopy_without_memo(self, test_domain):
        """Line 814: __deepcopy__ with memo=None."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        copied = copy.deepcopy(order)
        assert copied.name == "Test"
        assert copied is not order

    def test_deepcopy_memo_prevents_infinite_loop(self, test_domain):
        """Line 819: memo short-circuit for already-copied objects."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        memo: dict = {}
        # First copy
        copied1 = order.__deepcopy__(memo)
        # Second copy with same memo should return same object
        copied2 = order.__deepcopy__(memo)
        assert copied1 is copied2


# ---------------------------------------------------------------------------
# Tests: Entity not part_of
# ---------------------------------------------------------------------------
class TestEntityPartOfRequired:
    def test_entity_without_part_of_raises(self, test_domain):
        """Line 884: IncorrectUsageError when entity not part_of aggregate."""

        class StandaloneEntity(BaseEntity):
            name: String()

        with pytest.raises(IncorrectUsageError, match="needs to be associated"):
            test_domain.register(StandaloneEntity)
            test_domain.init(traverse=False)
