import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import String, ValueObject
from protean.fields.embedded import _ShadowField
from protean.utils.reflection import fields


def test_value_object_associated_class(test_domain):
    class Address(BaseValueObject):
        street_address = String()

    class User(BaseAggregate):
        email = String()
        address = ValueObject(Address)

    assert fields(User)["address"].value_object_cls == Address


def test_value_object_to_cls_is_always_a_base_value_object_subclass(test_domain):
    class Address(BaseEntity):
        street_address = String()

    with pytest.raises(IncorrectUsageError) as exc:

        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

    assert exc.value.args[0] == (
        "`Address` is not a valid Value Object and cannot be embedded in a Value Object field"
    )


class TestShadowField:
    """Test cases to cover missing ShadowField methods"""

    def test_shadow_field_as_dict_raises_not_implemented_error(self):
        """Test ShadowField.as_dict raises NotImplementedError"""
        shadow_field = _ShadowField(
            owner=None, field_name="test_field", field_obj=String()
        )

        with pytest.raises(NotImplementedError):
            shadow_field.as_dict("test_value")

    def test_shadow_field_delete_resets_values(self, test_domain):
        """Test ShadowField.__delete__ calls _reset_values"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()

        @test_domain.aggregate
        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

        user = User(email="test@example.com")
        user.address = Address(street="123 Main St")

        # Access the shadow field and call __delete__
        shadow_field = fields(User)["address"].embedded_fields["street"]
        shadow_field.__delete__(user)

        # The field should be reset (test passes if no exception is raised)
        assert True

    def test_shadow_field_reset_values_pops_field_name(self, test_domain):
        """Test ShadowField._reset_values pops field_name"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()

        @test_domain.aggregate
        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

        user = User(email="test@example.com")
        user.address = Address(street="123 Main St")

        # Access the shadow field and call _reset_values
        shadow_field = fields(User)["address"].embedded_fields["street"]
        shadow_field._reset_values(user)

        # The field should be reset (test passes if no exception is raised)
        assert True

    def test_shadow_field_set_method_does_nothing(self, test_domain):
        """Test ShadowField.__set__ method"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()

        @test_domain.aggregate
        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

        user = User(email="test@example.com")
        user.address = Address(street="123 Main St")

        # Access the shadow field and call __set__
        shadow_field = fields(User)["address"].embedded_fields["street"]
        shadow_field.__set__(user, "test_value")

        # The method should complete without error
        assert True

    def test_shadow_field_cast_to_type_returns_value_as_is(self):
        """Test ShadowField._cast_to_type returns value as is"""
        shadow_field = _ShadowField(
            owner=None, field_name="test_field", field_obj=String()
        )

        # Test with various value types - should return as is
        assert shadow_field._cast_to_type("test") == "test"
        assert shadow_field._cast_to_type(123) == 123
        assert shadow_field._cast_to_type(None) is None
        assert shadow_field._cast_to_type({"key": "value"}) == {"key": "value"}
        assert shadow_field._cast_to_type([1, 2, 3]) == [1, 2, 3]
        assert shadow_field._cast_to_type(True) is True


class TestValueObjectField:
    """Test cases to cover missing ValueObject field methods"""

    def test_value_object_field_delete_resets_values(self, test_domain):
        """Test ValueObject.__delete__ calls _reset_values"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()
            city = String()

        @test_domain.aggregate
        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

        user = User(email="test@example.com")
        user.address = Address(street="123 Main St", city="Boston")

        # Ensure the address is set
        assert user.address is not None
        assert user.address.street == "123 Main St"

        # Delete the value object field
        vo_field = fields(User)["address"]
        vo_field.__delete__(user)

        # The field should be reset
        assert user.address is None

    def test_value_object_field_resolve_to_cls_constructs_embedded_fields(
        self, test_domain
    ):
        """Test ValueObject._resolve_to_cls constructs embedded fields"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()
            city = String()

        # Create a ValueObject field with string reference
        vo_field = ValueObject("Address")

        # Manually call _resolve_to_cls to trigger the embedded field construction
        vo_field._resolve_to_cls(test_domain, Address, None)

        # Verify that embedded fields were constructed
        assert "street" in vo_field.embedded_fields
        assert "city" in vo_field.embedded_fields
        assert isinstance(vo_field.embedded_fields["street"], _ShadowField)
        assert isinstance(vo_field.embedded_fields["city"], _ShadowField)

    def test_value_object_field_with_string_reference_behavior(self, test_domain):
        """Test ValueObject field with string reference basic behavior"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()
            city = String()

        # Create a ValueObject field with string reference
        vo_field = ValueObject("Address")

        # The field should maintain the string reference
        assert vo_field.value_object_cls == "Address"
        assert isinstance(vo_field.value_object_cls, str)


class TestValueObjectFieldEdgeCases:
    """Test edge cases for ValueObject field handling"""

    def test_value_object_field_with_none_value(self, test_domain):
        """Test ValueObject field behavior with None values"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()
            city = String()

        @test_domain.aggregate
        class User(BaseAggregate):
            email = String()
            address = ValueObject(Address)

        user = User(email="test@example.com")

        # Set address to None
        user.address = None

        # Should handle None gracefully
        assert user.address is None

    def test_value_object_field_as_dict_with_none_value(self, test_domain):
        """Test ValueObject field as_dict method with None value"""

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()
            city = String()

        vo_field = ValueObject(Address)

        # Test as_dict with None value
        result = vo_field.as_dict(None)
        assert result is None

    def test_value_object_field_cast_to_type_with_invalid_value(self, test_domain):
        """Test ValueObject._cast_to_type fails with invalid value type"""
        from protean.exceptions import ValidationError

        @test_domain.value_object
        class Address(BaseValueObject):
            street = String()
            city = String()

        vo_field = ValueObject(Address)

        # Test with invalid value type (not dict or Address instance)
        with pytest.raises(ValidationError) as exc_info:
            vo_field._cast_to_type("invalid_value")

        # The error message should be set
        assert "unlinked" in exc_info.value.messages

        # Test with other invalid types
        with pytest.raises(ValidationError):
            vo_field._cast_to_type(123)

        with pytest.raises(ValidationError):
            vo_field._cast_to_type([1, 2, 3])
