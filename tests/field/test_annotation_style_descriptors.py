"""Tests for annotation-style descriptor declarations on domain elements.

Verifies that descriptor fields (ValueObject, HasMany, HasOne, Reference)
work correctly when declared using annotation syntax:

    class Customer(BaseAggregate):
        email: ValueObject(EmailAddress, required=True)
        addresses: HasMany(Address)

Previously, these descriptors ended up only in ``__annotations__`` and were
never migrated to ``vars(cls)``, breaking descriptor protocols.

See also: Bug 1 (entity.py) and Bug 2 (value_object.py) in the bug tracker.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import BaseValueObject
from protean.fields import HasMany, HasOne, String, ValueObject
from protean.fields.association import Association
from protean.utils.reflection import (
    declared_fields,
)


# ---------------------------------------------------------------------------
# Shared domain element definitions
# ---------------------------------------------------------------------------
class EmailAddress(BaseValueObject):
    address = String(max_length=254, required=True)


class Profile(BaseValueObject):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)


class GeoCoordinates(BaseValueObject):
    latitude: float
    longitude: float


class Address(BaseEntity):
    street = String(max_length=100, required=True)
    city = String(max_length=50)


class ShippingInfo(BaseEntity):
    method = String(max_length=30, required=True)


# =========================================================================
# Bug 1: Annotation-style descriptors on Aggregates/Entities
# =========================================================================
class TestAnnotationStyleValueObjectOnAggregate:
    """ValueObject() descriptor declared with annotation syntax on an aggregate."""

    def test_annotation_style_vo_descriptor_instantiation(self, test_domain):
        class Customer(BaseAggregate):
            name = String(max_length=50, required=True)
            email: ValueObject(EmailAddress, required=True)

        test_domain.register(Customer)
        test_domain.register(EmailAddress)
        test_domain.init(traverse=False)

        email = EmailAddress(address="alice@example.com")
        customer = Customer(name="Alice", email=email)

        assert customer.email is not None
        assert isinstance(customer.email, EmailAddress)
        assert customer.email.address == "alice@example.com"

    def test_annotation_style_vo_optional(self, test_domain):
        class Customer(BaseAggregate):
            name = String(max_length=50, required=True)
            profile: ValueObject(Profile)

        test_domain.register(Customer)
        test_domain.register(Profile)
        test_domain.init(traverse=False)

        # Without providing profile
        customer = Customer(name="Bob")
        assert customer.profile is None

        # With profile
        profile = Profile(first_name="Bob")
        customer2 = Customer(name="Bob", profile=profile)
        assert customer2.profile.first_name == "Bob"

    def test_annotation_style_vo_in_declared_fields(self, test_domain):
        class Customer(BaseAggregate):
            name = String(max_length=50, required=True)
            email: ValueObject(EmailAddress)

        test_domain.register(Customer)
        test_domain.register(EmailAddress)
        test_domain.init(traverse=False)

        df = declared_fields(Customer)
        assert "email" in df

    def test_annotation_style_vo_shadow_fields(self, test_domain):
        class Customer(BaseAggregate):
            name = String(max_length=50, required=True)
            email: ValueObject(EmailAddress)

        test_domain.register(Customer)
        test_domain.register(EmailAddress)
        test_domain.init(traverse=False)

        email = EmailAddress(address="test@example.com")
        customer = Customer(name="Test", email=email)

        # Shadow fields should be populated
        assert customer.__dict__.get("email_address") == "test@example.com"

    def test_annotation_style_vo_to_dict(self, test_domain):
        class Customer(BaseAggregate):
            name = String(max_length=50, required=True)
            email: ValueObject(EmailAddress)

        test_domain.register(Customer)
        test_domain.register(EmailAddress)
        test_domain.init(traverse=False)

        email = EmailAddress(address="test@example.com")
        customer = Customer(name="Test", email=email)

        d = customer.to_dict()
        assert "email" in d
        assert d["email"]["address"] == "test@example.com"

    def test_annotation_style_vo_equivalence_with_assignment(self, test_domain):
        """Annotation and assignment styles produce equivalent behavior."""

        class CustAssign(BaseAggregate):
            name = String(max_length=50, required=True)
            email = ValueObject(EmailAddress)

        class CustAnnot(BaseAggregate):
            name = String(max_length=50, required=True)
            email: ValueObject(EmailAddress)

        test_domain.register(CustAssign)
        test_domain.register(CustAnnot)
        test_domain.register(EmailAddress)
        test_domain.init(traverse=False)

        email = EmailAddress(address="test@example.com")

        c1 = CustAssign(name="Test", email=email)
        c2 = CustAnnot(name="Test", email=email)

        assert c1.email.address == c2.email.address
        assert "email" in declared_fields(CustAssign)
        assert "email" in declared_fields(CustAnnot)


class TestAnnotationStyleHasManyOnAggregate:
    """HasMany() descriptor declared with annotation syntax on an aggregate."""

    def test_annotation_style_has_many_instantiation(self, test_domain):
        class Order(BaseAggregate):
            name = String(max_length=50, required=True)
            items: HasMany(Address)

        test_domain.register(Order)
        test_domain.register(Address, part_of=Order)
        test_domain.init(traverse=False)

        addr = Address(street="123 Main St", city="NY")
        order = Order(name="Order1", items=[addr])

        assert len(order.items) == 1
        assert order.items[0].street == "123 Main St"

    def test_annotation_style_has_many_add_method(self, test_domain):
        class Order(BaseAggregate):
            name = String(max_length=50, required=True)
            items: HasMany(Address)

        test_domain.register(Order)
        test_domain.register(Address, part_of=Order)
        test_domain.init(traverse=False)

        order = Order(name="Order1")
        assert hasattr(order, "add_items")
        assert hasattr(order, "remove_items")

    def test_annotation_style_has_many_in_declared_fields(self, test_domain):
        class Order(BaseAggregate):
            name = String(max_length=50, required=True)
            items: HasMany(Address)

        test_domain.register(Order)
        test_domain.register(Address, part_of=Order)
        test_domain.init(traverse=False)

        df = declared_fields(Order)
        assert "items" in df
        assert isinstance(df["items"], Association)

    def test_annotation_style_has_many_equivalence_with_assignment(self, test_domain):
        """Annotation and assignment styles produce equivalent HasMany behavior."""

        class OrderAssign(BaseAggregate):
            name = String(max_length=50, required=True)
            items = HasMany(Address)

        class OrderAnnot(BaseAggregate):
            name = String(max_length=50, required=True)
            items: HasMany(Address)

        test_domain.register(OrderAssign)
        test_domain.register(OrderAnnot)
        test_domain.register(Address, part_of=OrderAssign)
        test_domain.init(traverse=False)

        assert "items" in declared_fields(OrderAssign)
        assert "items" in declared_fields(OrderAnnot)


class TestAnnotationStyleHasOneOnAggregate:
    """HasOne() descriptor declared with annotation syntax on an aggregate."""

    def test_annotation_style_has_one_instantiation(self, test_domain):
        class Order(BaseAggregate):
            name = String(max_length=50, required=True)
            shipping: HasOne(ShippingInfo)

        test_domain.register(Order)
        test_domain.register(ShippingInfo, part_of=Order)
        test_domain.init(traverse=False)

        shipping = ShippingInfo(method="Express")
        order = Order(name="Order1", shipping=shipping)

        assert order.shipping is not None
        assert order.shipping.method == "Express"

    def test_annotation_style_has_one_in_declared_fields(self, test_domain):
        class Order(BaseAggregate):
            name = String(max_length=50, required=True)
            shipping: HasOne(ShippingInfo)

        test_domain.register(Order)
        test_domain.register(ShippingInfo, part_of=Order)
        test_domain.init(traverse=False)

        df = declared_fields(Order)
        assert "shipping" in df
        assert isinstance(df["shipping"], Association)


class TestAnnotationStyleMixedDescriptors:
    """Mixed annotation-style and assignment-style descriptors."""

    def test_mixed_styles_on_aggregate(self, test_domain):
        class Customer(BaseAggregate):
            name = String(max_length=50, required=True)
            email: ValueObject(EmailAddress)
            profile = ValueObject(Profile)

        test_domain.register(Customer)
        test_domain.register(EmailAddress)
        test_domain.register(Profile)
        test_domain.init(traverse=False)

        email = EmailAddress(address="test@example.com")
        profile = Profile(first_name="Test")
        customer = Customer(name="Test", email=email, profile=profile)

        assert customer.email.address == "test@example.com"
        assert customer.profile.first_name == "Test"

        df = declared_fields(Customer)
        assert "email" in df
        assert "profile" in df


# =========================================================================
# Bug 2: Annotation-style ValueObject in ValueObject._resolve_fieldspecs
# =========================================================================
class TestAnnotationStyleNestedValueObject:
    """ValueObject() descriptor declared with annotation syntax inside another VO."""

    def test_annotation_style_nested_vo_instantiation(self):
        class Location(BaseValueObject):
            city = String(max_length=50, required=True)
            coordinates: ValueObject(GeoCoordinates)

        loc = Location(
            city="NYC",
            coordinates=GeoCoordinates(latitude=40.7, longitude=-74.0),
        )

        assert loc.city == "NYC"
        assert loc.coordinates.latitude == 40.7
        assert loc.coordinates.longitude == -74.0

    def test_annotation_style_nested_vo_optional(self):
        class Location(BaseValueObject):
            city = String(max_length=50, required=True)
            coordinates: ValueObject(GeoCoordinates)

        loc = Location(city="NYC")
        assert loc.coordinates is None

    def test_annotation_style_nested_vo_equivalence(self):
        """Assignment and annotation styles produce equivalent nested VOs."""

        class LocAssign(BaseValueObject):
            city = String(max_length=50, required=True)
            coordinates = ValueObject(GeoCoordinates)

        class LocAnnot(BaseValueObject):
            city = String(max_length=50, required=True)
            coordinates: ValueObject(GeoCoordinates)

        coords = GeoCoordinates(latitude=40.7, longitude=-74.0)

        l1 = LocAssign(city="NYC", coordinates=coords)
        l2 = LocAnnot(city="NYC", coordinates=coords)

        assert l1.coordinates.latitude == l2.coordinates.latitude
        assert l1.coordinates.longitude == l2.coordinates.longitude

    def test_annotation_style_nested_vo_in_declared_fields(self):
        class Location(BaseValueObject):
            city = String(max_length=50, required=True)
            coordinates: ValueObject(GeoCoordinates)

        df = declared_fields(Location)
        assert "city" in df
        assert "coordinates" in df

    def test_annotation_style_nested_vo_to_dict(self):
        class Location(BaseValueObject):
            city = String(max_length=50, required=True)
            coordinates: ValueObject(GeoCoordinates)

        loc = Location(
            city="NYC",
            coordinates=GeoCoordinates(latitude=40.7, longitude=-74.0),
        )
        d = loc.to_dict()
        assert d["city"] == "NYC"
        assert d["coordinates"]["latitude"] == 40.7
