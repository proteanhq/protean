"""Tests for ValueObject embedding in BaseEntity / BaseAggregate.

Validates:
- VO assignment and access
- Shadow fields in attributes()
- None handling
- to_dict() serialization
- State tracking on VO change
- Domain registration
"""

from uuid import uuid4

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import ValueObject
from protean.utils import _fully_qualified_name
from protean.utils.reflection import (
    _FIELDS,
    attributes,
    value_object_fields,
)


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class Address(BaseValueObject):
    street: str = ""
    city: str = ""
    zip_code: str = ""


class Customer(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: str = ""
    billing_address = ValueObject(Address)


class Location(BaseValueObject):
    latitude: float = 0.0
    longitude: float = 0.0


class ShippingAddress(BaseValueObject):
    street: str = ""
    city: str = ""
    location = ValueObject(Location)


class Store(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: str = ""
    shipping_address = ValueObject(ShippingAddress)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Address)
    test_domain.register(Customer)
    test_domain.register(Location)
    test_domain.register(ShippingAddress)
    test_domain.register(Store)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Tests: __container_fields__ bridge
# ---------------------------------------------------------------------------
class TestVOFieldsBridge:
    def test_vo_descriptor_in_container_fields(self):
        cf = getattr(Customer, _FIELDS, {})
        assert "billing_address" in cf
        assert isinstance(cf["billing_address"], ValueObject)

    def test_annotated_fields_coexist(self):
        cf = getattr(Customer, _FIELDS, {})
        assert "id" in cf
        assert "name" in cf

    def test_value_object_fields_utility(self):
        vof = value_object_fields(Customer)
        assert "billing_address" in vof

    def test_shadow_fields_in_attributes(self):
        attr = attributes(Customer)
        assert "billing_address_street" in attr
        assert "billing_address_city" in attr
        assert "billing_address_zip_code" in attr


# ---------------------------------------------------------------------------
# Tests: Flattened (shadow) attribute initialization
# ---------------------------------------------------------------------------
class TestVOFlattenedInit:
    """Flattened VO initialization via shadow attributes (e.g.
    ``billing_address_street="123 Main St"``) is supported at the
    Entity/Aggregate level.  It is NOT supported for direct VO-to-VO
    nesting because ValueObjects use ``extra="forbid"`` — flattened
    kwargs are an Entity-level concern for database persistence.
    """

    def test_entity_flattened_vo_init(self):
        """Entity can be initialized with flattened shadow attributes."""
        customer = Customer(
            name="Alice",
            billing_address_street="123 Main St",
            billing_address_city="Springfield",
            billing_address_zip_code="62704",
        )

        assert customer.billing_address is not None
        assert customer.billing_address.street == "123 Main St"
        assert customer.billing_address.city == "Springfield"
        assert customer.billing_address.zip_code == "62704"

    def test_entity_flattened_and_instance_are_equivalent(self):
        """Flattened shadow init produces the same result as instance init."""
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        via_instance = Customer(name="Alice", billing_address=addr)
        via_flat = Customer(
            name="Alice",
            billing_address_street="123 Main St",
            billing_address_city="Springfield",
            billing_address_zip_code="62704",
        )

        assert via_instance.billing_address == via_flat.billing_address

    def test_vo_to_vo_flattened_init_not_supported(self):
        """Direct VO-to-VO flattened init is not supported by design.

        Flattened (shadow) attributes are an Entity/Aggregate concern used
        for database column mapping.  ValueObjects use extra='forbid' and
        reject unknown kwargs.  Nested VOs must be passed as instances.
        """
        from protean.core.value_object import BaseValueObject
        from protean.exceptions import ValidationError

        class Inner(BaseValueObject):
            x: float = 0.0
            y: float = 0.0

        class Outer(BaseValueObject):
            label: str = ""
            point = ValueObject(Inner)

        with pytest.raises(ValidationError) as exc:
            Outer(label="origin", point_x=1.0, point_y=2.0)

        assert exc.value.messages["point_x"] == ["Extra inputs are not permitted"]
        assert exc.value.messages["point_y"] == ["Extra inputs are not permitted"]

    def test_vo_to_vo_instance_init_works(self):
        """Nested VOs must be passed as instances, not flattened kwargs."""
        from protean.core.value_object import BaseValueObject

        class Inner(BaseValueObject):
            x: float = 0.0
            y: float = 0.0

        class Outer(BaseValueObject):
            label: str = ""
            point = ValueObject(Inner)

        outer = Outer(label="origin", point=Inner(x=1.0, y=2.0))
        assert outer.point.x == 1.0
        assert outer.point.y == 2.0


class TestNestedVOFlattenedInit:
    """Flattened arguments stop at one level. A value object nested inside
    an embedded value object is passed as an object. A two-level flattened
    argument is rejected.
    """

    def test_one_level_flattened_argument_sets_the_field(self):
        store = Store(name="Corner", shipping_address_street="1 Main St")

        assert store.shipping_address.street == "1 Main St"
        assert store.shipping_address.city == ""
        assert store.shipping_address.location is None

    def test_one_level_flattened_argument_on_billing_address(self):
        customer = Customer(name="Alice", billing_address_street="123 Main St")

        assert customer.billing_address == Address(street="123 Main St")

    def test_nested_vo_passed_as_flattened_argument(self):
        store = Store(
            name="Corner",
            shipping_address_location=Location(latitude=12.5, longitude=77.6),
        )

        assert store.shipping_address.street == ""
        assert store.shipping_address.location == Location(
            latitude=12.5, longitude=77.6
        )

    def test_nested_vo_passed_as_dict_in_flattened_argument(self):
        store = Store(
            name="Corner",
            shipping_address_location={"latitude": 12.5, "longitude": 77.6},
        )

        assert store.shipping_address.location == Location(
            latitude=12.5, longitude=77.6
        )

    def test_nested_vo_passed_as_object(self):
        store = Store(
            name="Corner",
            shipping_address=ShippingAddress(
                street="1 Main St",
                location=Location(latitude=12.5, longitude=77.6),
            ),
        )

        assert store.shipping_address.street == "1 Main St"
        assert store.shipping_address.location == Location(
            latitude=12.5, longitude=77.6
        )

    def test_two_level_flattened_argument_is_rejected(self):
        with pytest.raises(ValidationError) as exc:
            Store(name="Corner", shipping_address_location_latitude=12.5)

        assert exc.value.messages["shipping_address_location_latitude"] == [
            "Extra inputs are not permitted"
        ]


# ---------------------------------------------------------------------------
# Tests: Assignment and access
# ---------------------------------------------------------------------------
class TestVOAssignment:
    def test_assign_vo_at_construction(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)

        assert customer.billing_address == addr
        assert customer.billing_address.street == "123 Main St"

    def test_shadow_fields_populated(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)

        assert customer.__dict__["billing_address_street"] == "123 Main St"
        assert customer.__dict__["billing_address_city"] == "Springfield"
        assert customer.__dict__["billing_address_zip_code"] == "62704"

    def test_none_vo_by_default(self):
        customer = Customer(name="Bob")
        assert customer.billing_address is None

    def test_replace_vo(self):
        addr1 = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr1)

        addr2 = Address(street="456 Elm Ave", city="Shelbyville", zip_code="62705")
        customer.billing_address = addr2

        assert customer.billing_address == addr2
        assert customer.__dict__["billing_address_street"] == "456 Elm Ave"

    def test_set_vo_to_none(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)

        customer.billing_address = None
        assert customer.billing_address is None


# ---------------------------------------------------------------------------
# Tests: State tracking
# ---------------------------------------------------------------------------
class TestVOStateTracking:
    def test_setting_vo_marks_changed(self):
        customer = Customer(name="Alice")
        customer._state.mark_saved()
        assert not customer._state.is_changed

        customer.billing_address = Address(street="789 Oak Ln")
        assert customer._state.is_changed


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestVOSerialization:
    def test_to_dict_includes_vo(self):
        addr = Address(street="123 Main St", city="Springfield", zip_code="62704")
        customer = Customer(name="Alice", billing_address=addr)
        d = customer.to_dict()

        assert "billing_address" in d
        assert d["billing_address"]["street"] == "123 Main St"
        assert d["billing_address"]["city"] == "Springfield"
        assert d["billing_address"]["zip_code"] == "62704"

    def test_to_dict_excludes_none_vo(self):
        customer = Customer(name="Bob")
        d = customer.to_dict()

        # ValueObject field should not appear when None
        assert "billing_address" not in d

    def test_to_dict_annotated_fields_included(self):
        customer = Customer(name="Alice")
        d = customer.to_dict()

        assert d["name"] == "Alice"
        assert "id" in d


# ---------------------------------------------------------------------------
# Tests: Domain registration
# ---------------------------------------------------------------------------
class TestVODomainRegistration:
    def test_aggregate_with_vo_registered(self, test_domain):
        assert _fully_qualified_name(Customer) in test_domain.registry.aggregates

    def test_vo_registered(self, test_domain):
        assert _fully_qualified_name(Address) in test_domain.registry.value_objects
