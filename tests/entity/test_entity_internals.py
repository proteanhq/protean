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


# ---------------------------------------------------------------------------
# Domain elements for shadow field / descriptor kwargs separation tests
# ---------------------------------------------------------------------------
class Region(BaseAggregate):
    name: String(required=True, max_length=100)


class Store(BaseAggregate):
    name: String(required=True, max_length=100)
    region = Reference(Region, required=True)


class Warehouse(BaseAggregate):
    name: String(required=True, max_length=100)
    region = Reference(Region, required=False)


class Country(BaseAggregate):
    name: String(required=True, max_length=50)


class City(BaseEntity):
    name: String(required=True, max_length=100)
    country = Reference(Country, required=True)


class Province(BaseEntity):
    name: String(required=True, max_length=100)
    country = Reference(Country, required=False)


class BillingAddress(BaseValueObject):
    street: String(max_length=200)
    city: String(max_length=100)


class BillingCustomer(BaseAggregate):
    name: String(required=True, max_length=100)
    billing = ValueObject(BillingAddress, required=True)


class Employee(BaseAggregate):
    name: String(required=True, max_length=100)
    home = ValueObject(BillingAddress, required=False)


# ---------------------------------------------------------------------------
# Tests: Shadow field / descriptor kwargs separation in __init__
# ---------------------------------------------------------------------------
class TestShadowFieldPriorityOnAggregates:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Region)
        test_domain.register(Store)
        test_domain.register(Warehouse)
        test_domain.register(Country)
        test_domain.register(City, part_of=Country)
        test_domain.register(Province, part_of=Country)
        test_domain.register(BillingAddress)
        test_domain.register(BillingCustomer)
        test_domain.register(Employee)
        test_domain.init(traverse=False)

    def test_construct_aggregate_with_shadow_field_kwarg(self, test_domain):
        """Passing region_id directly should not raise ValidationError."""
        store = Store(name="Main Store", region_id="region-1")
        assert store.name == "Main Store"
        assert store.region_id == "region-1"

    def test_construct_aggregate_with_descriptor_kwarg(self, test_domain):
        """Passing region as a Reference descriptor should work too."""
        region = Region(name="Northeast")
        store = Store(name="Main Store", region=region)
        assert store.name == "Main Store"
        assert store.region == region
        assert store.region_id == region.id

    def test_shadow_field_satisfies_required_reference(self, test_domain):
        """When region_id is provided, region Reference is satisfied (required)."""
        store = Store(name="Main Store", region_id="region-abc")
        assert store.region_id == "region-abc"

    def test_missing_required_reference_and_shadow_raises(self, test_domain):
        """Omitting both region and region_id should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            Store(name="Store without region")
        assert "region" in exc_info.value.messages

    def test_optional_reference_without_shadow_or_descriptor(self, test_domain):
        """Optional Reference — omitting both region and region_id is fine."""
        warehouse = Warehouse(name="Warehouse A")
        assert warehouse.region_id is None


class TestShadowFieldPriorityOnEntities:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Region)
        test_domain.register(Store)
        test_domain.register(Warehouse)
        test_domain.register(Country)
        test_domain.register(City, part_of=Country)
        test_domain.register(Province, part_of=Country)
        test_domain.register(BillingAddress)
        test_domain.register(BillingCustomer)
        test_domain.register(Employee)
        test_domain.init(traverse=False)

    def test_construct_entity_with_shadow_field_kwarg(self, test_domain):
        """Passing country_id directly to a child entity should work."""
        city = City(name="Boston", country_id="country-1")
        assert city.name == "Boston"
        assert city.country_id == "country-1"

    def test_construct_entity_with_descriptor_kwarg(self, test_domain):
        """Passing country as Reference descriptor should work."""
        country = Country(name="USA")
        city = City(name="Boston", country=country)
        assert city.country == country
        assert city.country_id == country.id

    def test_shadow_field_satisfies_required_reference_on_entity(self, test_domain):
        """country_id in kwargs should satisfy required Reference."""
        city = City(name="Boston", country_id="country-xyz")
        assert city.country_id == "country-xyz"

    def test_missing_required_reference_on_entity_raises(self, test_domain):
        """Omitting both country and country_id on required Reference raises."""
        with pytest.raises(ValidationError) as exc_info:
            City(name="Orphan City")
        assert "country" in exc_info.value.messages

    def test_optional_reference_on_entity_without_value(self, test_domain):
        """Optional Reference on entity — omitting is fine."""
        province = Province(name="Manitoba", country_id=None)
        assert province.country_id is None


class TestShadowFieldInTemplateDicts:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Region)
        test_domain.register(Store)
        test_domain.register(BillingAddress)
        test_domain.register(BillingCustomer)
        test_domain.init(traverse=False)

    def test_shadow_kwarg_via_template_dict(self, test_domain):
        """Shadow field passed via positional template dict should be popped."""
        store = Store({"name": "Branch", "region_id": "region-tmpl"})
        assert store.name == "Branch"
        assert store.region_id == "region-tmpl"

    def test_descriptor_kwarg_via_template_dict(self, test_domain):
        """Descriptor kwarg passed via template dict should be popped."""
        region = Region(name="South")
        store = Store({"name": "Branch", "region": region})
        assert store.region == region

    def test_regular_kwarg_overrides_template(self, test_domain):
        """For regular (non-shadow, non-descriptor) kwargs, keyword args
        take precedence over template dict via merged.update(kwargs)."""
        store = Store(
            {"name": "Template Name", "region_id": "r1"},
            name="Kwarg Name",
        )
        assert store.name == "Kwarg Name"


class TestValueObjectShadowFieldsSatisfyRequired:
    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(BillingAddress)
        test_domain.register(BillingCustomer)
        test_domain.register(Employee)
        test_domain.init(traverse=False)

    def test_vo_shadow_fields_satisfy_required_vo(self, test_domain):
        """Providing VO shadow fields should satisfy a required VO descriptor."""
        customer = BillingCustomer(
            name="Alice",
            billing_street="123 Main St",
            billing_city="Boston",
        )
        assert customer.name == "Alice"
        assert customer.billing.street == "123 Main St"
        assert customer.billing.city == "Boston"

    def test_vo_descriptor_directly(self, test_domain):
        """Passing VO descriptor directly should work."""
        addr = BillingAddress(street="456 Oak Ave", city="Cambridge")
        customer = BillingCustomer(name="Bob", billing=addr)
        assert customer.billing.street == "456 Oak Ave"

    def test_missing_required_vo_raises(self, test_domain):
        """Omitting both VO descriptor and its shadow fields raises."""
        with pytest.raises(ValidationError) as exc_info:
            BillingCustomer(name="Charlie")
        assert "billing" in exc_info.value.messages

    def test_optional_vo_without_value(self, test_domain):
        """Optional ValueObject — omitting is fine."""
        emp = Employee(name="Dave")
        assert emp.home is None


# ---------------------------------------------------------------------------
# Domain elements for mixed required VO + Reference tests
# ---------------------------------------------------------------------------
class ShippingAddress(BaseValueObject):
    line1: String(max_length=200)
    zip_code: String(max_length=10)


class Vendor(BaseAggregate):
    name: String(required=True, max_length=100)


class PurchaseOrder(BaseAggregate):
    description: String(max_length=200)
    vendor = Reference(Vendor, required=True)
    shipping = ValueObject(ShippingAddress, required=True)


# ---------------------------------------------------------------------------
# Tests: Mixed required VO + Reference satisfied by shadow kwargs
# ---------------------------------------------------------------------------
class TestMixedRequiredVoAndReference:
    """Both a required ValueObject and a required Reference on the same
    aggregate, both satisfied exclusively by shadow kwargs."""

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(ShippingAddress)
        test_domain.register(Vendor)
        test_domain.register(PurchaseOrder)
        test_domain.init(traverse=False)

    def test_both_satisfied_by_shadow_kwargs(self, test_domain):
        """Providing shadow kwargs for both VO and Reference should succeed."""
        po = PurchaseOrder(
            description="Office Supplies",
            vendor_id="vendor-1",
            shipping_line1="100 Warehouse Rd",
            shipping_zip_code="02139",
        )
        assert po.vendor_id == "vendor-1"
        assert po.shipping.line1 == "100 Warehouse Rd"

    def test_missing_reference_raises_even_when_vo_present(self, test_domain):
        """Missing required Reference should raise even if VO is satisfied."""
        with pytest.raises(ValidationError) as exc_info:
            PurchaseOrder(
                description="Partial",
                shipping_line1="100 Warehouse Rd",
                shipping_zip_code="02139",
            )
        assert "vendor" in exc_info.value.messages

    def test_missing_vo_raises_even_when_reference_present(self, test_domain):
        """Missing required VO should raise even if Reference is satisfied."""
        with pytest.raises(ValidationError) as exc_info:
            PurchaseOrder(
                description="Partial",
                vendor_id="vendor-1",
            )
        assert "shipping" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Tests: model_post_init internal kwargs (_owner, _root, _version)
# ---------------------------------------------------------------------------
class TestModelPostInitContextKwargs:
    """Tests that _owner, _root, and _version kwargs passed to __init__
    are correctly restored in model_post_init.  These are internal kwargs
    used during repository hydration and child entity construction."""

    @pytest.fixture(autouse=True)
    def register(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.init(traverse=False)

    def test_version_kwarg_restored_in_model_post_init(self, test_domain):
        """_version passed as kwarg should be set on the entity."""
        order = Order(name="Versioned Order", _version=5)
        assert order._version == 5

    def test_owner_kwarg_restored_in_model_post_init(self, test_domain):
        """_owner passed as kwarg should be set on the entity."""
        parent = Order(name="Parent Order")
        item = OrderItem(product_name="Widget", quantity=1, _owner=parent)
        assert item._owner is parent

    def test_root_kwarg_restored_in_model_post_init(self, test_domain):
        """_root passed as kwarg should be set on the entity."""
        root = Order(name="Root Order")
        item = OrderItem(product_name="Widget", quantity=1, _root=root)
        assert item._root is root

    def test_all_context_kwargs_together(self, test_domain):
        """All three internal kwargs together should be correctly restored."""
        root = Order(name="Root")
        parent = Order(name="Parent")
        item = OrderItem(
            product_name="Widget",
            quantity=1,
            _owner=parent,
            _root=root,
            _version=3,
        )
        assert item._owner is parent
        assert item._root is root
        assert item._version == 3
