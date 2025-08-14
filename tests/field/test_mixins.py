"""Test cases for field mixins to cover missing lines"""

import pytest

from protean.fields.mixins import NOT_PROVIDED, FieldCacheMixin, FieldDescriptorMixin


class MockState:
    """Mock state object for testing cache operations"""

    def __init__(self, initial_cache=None):
        self.fields_cache = initial_cache or {}


class MockInstance:
    """Mock instance for testing field operations"""

    def __init__(self, initial_cache=None):
        self.state_ = MockState(initial_cache)


class TestMixin(FieldCacheMixin):
    """Test implementation of FieldCacheMixin"""

    def get_cache_name(self):
        return "test_cache"


class TestFieldCacheMixin:
    """Test cases to cover missing FieldCacheMixin methods"""

    def test_get_cache_name_raises_not_implemented_error(self):
        """Test FieldCacheMixin.get_cache_name raises NotImplementedError"""
        mixin = FieldCacheMixin()

        with pytest.raises(NotImplementedError):
            mixin.get_cache_name()

    def test_get_cached_value_with_default_when_key_not_found(self):
        """Test FieldCacheMixin.get_cached_value returns default when key not found"""
        mixin = TestMixin()
        instance = MockInstance()
        default_value = "default_test_value"

        result = mixin.get_cached_value(instance, default=default_value)
        assert result == default_value

    def test_get_cached_value_raises_key_error_when_no_default(self):
        """Test FieldCacheMixin.get_cached_value raises KeyError when no default and key not found"""
        mixin = TestMixin()
        instance = MockInstance()

        with pytest.raises(KeyError):
            mixin.get_cached_value(instance)

    def test_is_cached_returns_true_when_key_exists(self):
        """Test FieldCacheMixin.is_cached returns True when key exists"""
        mixin = TestMixin()
        instance = MockInstance({"test_cache": "cached_value"})

        assert mixin.is_cached(instance) is True

    def test_is_cached_returns_false_when_key_not_exists(self):
        """Test FieldCacheMixin.is_cached returns False when key doesn't exist"""
        mixin = TestMixin()
        instance = MockInstance()

        assert mixin.is_cached(instance) is False

    def test_set_cached_value_sets_value_in_cache(self):
        """Test FieldCacheMixin.set_cached_value sets value in cache"""
        mixin = TestMixin()
        instance = MockInstance()
        test_value = "test_cached_value"

        mixin.set_cached_value(instance, test_value)

        assert instance.state_.fields_cache["test_cache"] == test_value

    def test_delete_cached_value_removes_value_from_cache(self):
        """Test FieldCacheMixin.delete_cached_value removes value from cache"""
        mixin = TestMixin()
        instance = MockInstance({"test_cache": "cached_value"})

        mixin.delete_cached_value(instance)

        assert "test_cache" not in instance.state_.fields_cache

    def test_delete_cached_value_handles_missing_key(self):
        """Test FieldCacheMixin.delete_cached_value handles missing key gracefully"""
        mixin = TestMixin()
        instance = MockInstance()

        # Should not raise error when deleting non-existent key
        mixin.delete_cached_value(instance)

        assert len(instance.state_.fields_cache) == 0


class TestFieldDescriptorMixin:
    """Test cases to cover missing FieldDescriptorMixin methods"""

    def test_get_raises_not_implemented_error(self):
        """Test FieldDescriptorMixin.__get__ raises NotImplementedError"""
        mixin = FieldDescriptorMixin()

        with pytest.raises(NotImplementedError):
            mixin.__get__(None, None)

    def test_set_raises_not_implemented_error(self):
        """Test FieldDescriptorMixin.__set__ raises NotImplementedError"""
        mixin = FieldDescriptorMixin()

        with pytest.raises(NotImplementedError):
            mixin.__set__(None, None)

    def test_delete_raises_not_implemented_error(self):
        """Test FieldDescriptorMixin.__delete__ raises NotImplementedError"""
        mixin = FieldDescriptorMixin()

        with pytest.raises(NotImplementedError):
            mixin.__delete__(None)

    def test_field_descriptor_mixin_init(self):
        """Test FieldDescriptorMixin initialization"""
        mixin = FieldDescriptorMixin(description="Test field", referenced_as="test_ref")

        assert mixin.field_name is None
        assert mixin.attribute_name is None
        assert mixin.description == "Test field"
        assert mixin.referenced_as == "test_ref"

    def test_field_descriptor_mixin_set_name(self):
        """Test FieldDescriptorMixin.__set_name__ method"""
        mixin = FieldDescriptorMixin()

        class DummyEntity:
            pass

        mixin.__set_name__(DummyEntity, "test_field")

        assert mixin.field_name == "test_field"
        assert mixin.attribute_name == "test_field"
        assert mixin._entity_cls == DummyEntity

    def test_field_descriptor_mixin_get_attribute_name_with_referenced_as(self):
        """Test FieldDescriptorMixin.get_attribute_name with referenced_as"""
        mixin = FieldDescriptorMixin(referenced_as="custom_name")
        mixin.field_name = "original_name"

        assert mixin.get_attribute_name() == "custom_name"

    def test_field_descriptor_mixin_get_attribute_name_without_referenced_as(self):
        """Test FieldDescriptorMixin.get_attribute_name without referenced_as"""
        mixin = FieldDescriptorMixin()
        mixin.field_name = "original_name"

        assert mixin.get_attribute_name() == "original_name"


class TestNOT_PROVIDED:
    """Test the NOT_PROVIDED sentinel object"""

    def test_not_provided_is_unique_object(self):
        """Test that NOT_PROVIDED is a unique sentinel object"""
        assert NOT_PROVIDED is not None
        assert NOT_PROVIDED is not False
        assert NOT_PROVIDED != ""
        assert NOT_PROVIDED != 0
        assert NOT_PROVIDED != []
        assert NOT_PROVIDED != {}

        # Should be the same object when imported multiple times
        from protean.fields.mixins import NOT_PROVIDED as NOT_PROVIDED_2

        assert NOT_PROVIDED is NOT_PROVIDED_2
