"""Tests for entity internals: init, equality, deepcopy, raise_, state in core/entity.py."""

import copy

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, _ID_FIELD_NAME
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    ValidationError,
)
from protean.fields import HasMany, Integer, Reference, String, ValueObject


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Order(BaseAggregate):
    name: String(required=True, max_length=50)
    items = HasMany("OrderItem")


class OrderItem(BaseEntity):
    product_name: String(required=True, max_length=100)
    quantity: Integer(min_value=1)


class Address(BaseValueObject):
    street: String(max_length=100)
    city: String(max_length=50)


class Customer(BaseAggregate):
    name: String(required=True, max_length=100)
    address = ValueObject(Address)


class CustomerEvent(BaseEvent):
    name: String(required=True)

    class Meta:
        part_of = Customer


# ---------------------------------------------------------------------------
# Test: Template dict with descriptor and shadow kwargs
# ---------------------------------------------------------------------------
class TestEntityInitTemplateDict:
    def test_template_dict_with_descriptor_kwargs(self, test_domain):
        """Descriptor kwargs extracted from positional template dict."""
        test_domain.register(Customer)
        test_domain.register(Address)
        test_domain.init(traverse=False)

        addr = Address(street="123 Main St", city="Boston")
        # Pass descriptor kwarg 'address' via template dict
        customer = Customer({"name": "Alice", "address": addr})
        assert customer.name == "Alice"
        assert customer.address.street == "123 Main St"

    def test_template_dict_with_shadow_kwargs(self, test_domain):
        """Shadow kwargs extracted from positional template dict."""

        class Post(BaseAggregate):
            title: String(required=True, max_length=100)
            author = Reference("Author")

        class Author(BaseEntity):
            name: String(required=True, max_length=50)

        test_domain.register(Post)
        test_domain.register(Author, part_of=Post)
        test_domain.init(traverse=False)

        # Pass shadow field 'author_id' via template dict
        post = Post({"title": "Hello", "author_id": "auth-123"})
        assert post.title == "Hello"
        assert post.author_id == "auth-123"


# ---------------------------------------------------------------------------
# Tests: _update_data
# ---------------------------------------------------------------------------
class TestEntityUpdateData:
    def test_non_dict_positional_arg_raises(self, test_domain):
        """AssertionError for non-dict in _update_data."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        with pytest.raises(AssertionError) as exc_info:
            order._update_data("not a dict")
        assert "must be a dict" in str(exc_info.value)

    def test_validation_error_collection_in_update_data(self, test_domain):
        """Validation errors collected during _update_data."""
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
        """state_ setter."""
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
        """__deepcopy__ with memo=None."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        copied = copy.deepcopy(order)
        assert copied.name == "Test"
        assert copied is not order

    def test_deepcopy_memo_prevents_infinite_loop(self, test_domain):
        """memo short-circuit for already-copied objects."""
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

    def test_deepcopy_with_none_pydantic_private(self, test_domain):
        """__deepcopy__ when __pydantic_private__ is None."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        # Force __pydantic_private__ to None
        object.__setattr__(order, "__pydantic_private__", None)
        copied = order.__deepcopy__({})
        assert copied is not order
        assert getattr(copied, "__pydantic_private__") is None


# ---------------------------------------------------------------------------
# Tests: __eq__, __hash__, __str__ fallbacks
# ---------------------------------------------------------------------------
class TestEntityEqualityEdgeCases:
    def test_eq_with_different_type(self, test_domain):
        """__eq__ returns False for different types."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        assert order != "not an entity"
        assert order != 42
        assert order != None  # noqa: E711

    def test_eq_without_id_field(self, test_domain):
        """__eq__ returns False when no id field."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order1 = Order(name="Test")
        order2 = Order(name="Test")
        # Temporarily remove _ID_FIELD_NAME
        saved = getattr(Order, _ID_FIELD_NAME, None)
        try:
            delattr(Order, _ID_FIELD_NAME)
            assert order1 != order2
        finally:
            if saved is not None:
                setattr(Order, _ID_FIELD_NAME, saved)

    def test_hash_without_id_field(self, test_domain):
        """__hash__ returns id(self) when no id field."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        saved = getattr(Order, _ID_FIELD_NAME, None)
        try:
            delattr(Order, _ID_FIELD_NAME)
            assert hash(order) == id(order)
        finally:
            if saved is not None:
                setattr(Order, _ID_FIELD_NAME, saved)

    def test_str_without_id_field(self, test_domain):
        """__str__ fallback when no id field."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        saved = getattr(Order, _ID_FIELD_NAME, None)
        try:
            delattr(Order, _ID_FIELD_NAME)
            assert str(order) == "Order object"
        finally:
            if saved is not None:
                setattr(Order, _ID_FIELD_NAME, saved)


# ---------------------------------------------------------------------------
# Tests: raise_ from child entity with mismatched event
# ---------------------------------------------------------------------------
class TestEntityRaiseMismatchedEvent:
    def test_raise_mismatched_event_from_child_entity(self, test_domain):
        """ConfigurationError when child entity raises wrong event."""
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.register(Customer)
        test_domain.register(CustomerEvent, part_of=Customer)
        test_domain.init(traverse=False)

        order = Order(name="Test")
        item = OrderItem(product_name="Widget", quantity=1)
        order.add_items(item)

        # Try raising an event associated with Customer from OrderItem
        with pytest.raises(ConfigurationError, match="not associated"):
            item.raise_(CustomerEvent(name="Wrong"))


# ---------------------------------------------------------------------------
# Tests: Entity not part_of
# ---------------------------------------------------------------------------
class TestEntityPartOfRequired:
    def test_entity_without_part_of_raises(self, test_domain):
        """IncorrectUsageError when entity not part_of aggregate."""

        class StandaloneEntity(BaseEntity):
            name: String()

        with pytest.raises(IncorrectUsageError, match="needs to be associated"):
            test_domain.register(StandaloneEntity)
            test_domain.init(traverse=False)
