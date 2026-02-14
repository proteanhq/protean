"""Test cases for clone_class utility function."""

import pytest

from protean.utils import clone_class
from protean.utils.container import Element


class TestCloneClass:
    """Test cases for the clone_class utility function."""

    def test_clone_basic_class(self):
        """Test cloning a basic class."""

        class OriginalClass:
            class_attr = "test_value"

            def method(self):
                return "original_method"

        cloned_class = clone_class(OriginalClass, "ClonedClass")

        # Verify the new class has the correct name
        assert cloned_class.__name__ == "ClonedClass"
        assert cloned_class.__qualname__ == "ClonedClass"

        # Verify it's a different class object
        assert cloned_class is not OriginalClass

        # Verify attributes are preserved
        assert cloned_class.class_attr == "test_value"
        assert hasattr(cloned_class, "method")

        # Verify method behavior is preserved
        instance = cloned_class()
        assert instance.method() == "original_method"

    def test_clone_element_subclass(self):
        """Test cloning an Element subclass."""

        class TestElement(Element):
            element_type = "TEST"
            custom_attr = "element_value"

            @classmethod
            def class_method(cls):
                return f"Called on {cls.__name__}"

        cloned_element = clone_class(TestElement, "ClonedElement")

        assert cloned_element.__name__ == "ClonedElement"
        assert cloned_element.__qualname__ == "ClonedElement"
        assert cloned_element is not TestElement
        assert cloned_element.element_type == "TEST"
        assert cloned_element.custom_attr == "element_value"
        assert cloned_element.class_method() == "Called on ClonedElement"

    def test_clone_with_inheritance(self):
        """Test cloning a class with inheritance hierarchy."""

        class BaseClass:
            base_attr = "base"

        class DerivedClass(BaseClass):
            derived_attr = "derived"

        cloned_class = clone_class(DerivedClass, "ClonedDerived")

        assert cloned_class.__name__ == "ClonedDerived"
        assert cloned_class.__bases__ == (BaseClass,)
        assert cloned_class.base_attr == "base"
        assert cloned_class.derived_attr == "derived"

        # Verify inheritance works correctly
        instance = cloned_class()
        assert isinstance(instance, BaseClass)
        assert isinstance(instance, cloned_class)

    def test_clone_with_multiple_inheritance(self):
        """Test cloning a class with multiple inheritance."""

        class MixinA:
            mixin_a_attr = "a"

        class MixinB:
            mixin_b_attr = "b"

        class MultipleInheritance(MixinA, MixinB):
            own_attr = "own"

        cloned_class = clone_class(MultipleInheritance, "ClonedMultiple")

        assert cloned_class.__name__ == "ClonedMultiple"
        assert cloned_class.__bases__ == (MixinA, MixinB)
        assert cloned_class.mixin_a_attr == "a"
        assert cloned_class.mixin_b_attr == "b"
        assert cloned_class.own_attr == "own"

    def test_clone_with_static_and_class_methods(self):
        """Test cloning preserves static and class methods."""

        class WithMethods:
            @staticmethod
            def static_method():
                return "static_result"

            @classmethod
            def class_method(cls):
                return f"class_{cls.__name__}"

            def instance_method(self):
                return "instance_result"

        cloned_class = clone_class(WithMethods, "ClonedMethods")

        assert cloned_class.static_method() == "static_result"
        assert cloned_class.class_method() == "class_ClonedMethods"

        instance = cloned_class()
        assert instance.instance_method() == "instance_result"

    def test_clone_with_properties(self):
        """Test cloning preserves properties."""

        class WithProperties:
            def __init__(self):
                self._value = 10

            @property
            def value(self):
                return self._value

            @value.setter
            def value(self, new_value):
                self._value = new_value

        cloned_class = clone_class(WithProperties, "ClonedProperties")

        instance = cloned_class()
        assert instance.value == 10
        instance.value = 20
        assert instance.value == 20

    def test_clone_with_descriptors(self):
        """Test cloning preserves custom descriptors."""

        class CustomDescriptor:
            def __get__(self, obj, objtype=None):
                return "descriptor_value"

        class WithDescriptor:
            custom = CustomDescriptor()

        cloned_class = clone_class(WithDescriptor, "ClonedDescriptor")

        instance = cloned_class()
        assert instance.custom == "descriptor_value"

    def test_clone_preserves_metaclass(self):
        """Test cloning preserves metaclass behavior."""

        class CustomMeta(type):
            def custom_meta_method(cls):
                return f"meta_method_on_{cls.__name__}"

        class WithMetaclass(metaclass=CustomMeta):
            pass

        cloned_class = clone_class(WithMetaclass, "ClonedMeta")

        assert type(cloned_class) is CustomMeta
        assert cloned_class.custom_meta_method() == "meta_method_on_ClonedMeta"

    def test_clone_excludes_special_attributes(self):
        """Test that special attributes are properly excluded."""

        class OriginalClass:
            """Original docstring."""

            pass

        # Manually set some attributes that should be excluded
        OriginalClass.__module__ = "original_module"

        cloned_class = clone_class(OriginalClass, "ClonedClass")

        # These should not be copied from the original
        assert cloned_class.__name__ == "ClonedClass"
        assert cloned_class.__qualname__ == "ClonedClass"
        # __module__ should be set automatically by type()
        # Note: __dict__ and __weakref__ are automatically added by type() for regular classes

    def test_invalid_input_not_a_class(self):
        """Test error handling when input is not a class."""
        with pytest.raises(TypeError, match="Expected a class, got str"):
            clone_class("not_a_class", "NewName")

        with pytest.raises(TypeError, match="Expected a class, got int"):
            clone_class(123, "NewName")

        with pytest.raises(TypeError, match="Expected a class, got NoneType"):
            clone_class(None, "NewName")

    def test_invalid_name_not_string(self):
        """Test error handling when name is not a string."""

        class TestClass:
            pass

        with pytest.raises(TypeError, match="Class name must be a string, got int"):
            clone_class(TestClass, 123)

        with pytest.raises(
            TypeError, match="Class name must be a string, got NoneType"
        ):
            clone_class(TestClass, None)

    def test_invalid_name_not_identifier(self):
        """Test error handling for invalid Python identifiers."""

        class TestClass:
            pass

        invalid_names = [
            "123invalid",  # starts with number
            "invalid-name",  # contains hyphen
            "invalid name",  # contains space
            "invalid.name",  # contains dot
        ]

        for invalid_name in invalid_names:
            with pytest.raises(ValueError, match="is not a valid Python identifier"):
                clone_class(TestClass, invalid_name)

        # Test reserved keywords separately
        reserved_keywords = ["class", "def", "if", "for", "while"]
        for keyword in reserved_keywords:
            with pytest.raises(ValueError, match="is a reserved Python keyword"):
                clone_class(TestClass, keyword)

    def test_empty_name_error(self):
        """Test error handling for empty class name."""

        class TestClass:
            pass

        with pytest.raises(ValueError, match="Class name cannot be empty"):
            clone_class(TestClass, "")

    def test_valid_identifier_names(self):
        """Test that valid Python identifiers work correctly."""

        class TestClass:
            pass

        valid_names = [
            "ValidName",
            "valid_name",
            "_private_name",
            "__dunder_name__",
            "name123",
            "CamelCaseName",
            "UPPER_CASE_NAME",
        ]

        for valid_name in valid_names:
            cloned = clone_class(TestClass, valid_name)
            assert cloned.__name__ == valid_name
            assert cloned.__qualname__ == valid_name

    def test_clone_independence(self):
        """Test that cloned classes are independent of each other."""

        class OriginalClass:
            mutable_attr = []

        cloned1 = clone_class(OriginalClass, "Cloned1")
        cloned2 = clone_class(OriginalClass, "Cloned2")

        # Classes should be different objects
        assert cloned1 is not cloned2
        assert cloned1 is not OriginalClass
        assert cloned2 is not OriginalClass

        # But they share the same mutable attributes (shallow copy behavior)
        assert cloned1.mutable_attr is OriginalClass.mutable_attr
        assert cloned2.mutable_attr is OriginalClass.mutable_attr

    def test_clone_with_slots(self):
        """Test cloning classes with __slots__."""

        class WithSlots:
            __slots__ = ("x", "y")  # Use tuple instead of list to avoid conflicts

            def __init__(self, x=0, y=0):
                self.x = x
                self.y = y

        cloned_class = clone_class(WithSlots, "ClonedSlots")

        assert cloned_class.__name__ == "ClonedSlots"
        assert cloned_class.__slots__ == ("x", "y")

        instance = cloned_class(1, 2)
        assert instance.x == 1
        assert instance.y == 2

    def test_clone_abstract_base_classes(self):
        """Test cloning abstract base classes."""
        from abc import ABC, abstractmethod

        class AbstractClass(ABC):
            concrete_attr = "concrete"

            @abstractmethod
            def abstract_method(self):
                pass

            def concrete_method(self):
                return "concrete"

        cloned_class = clone_class(AbstractClass, "ClonedAbstract")

        assert cloned_class.__name__ == "ClonedAbstract"
        assert cloned_class.concrete_attr == "concrete"
        assert hasattr(cloned_class, "abstract_method")

        # Test concrete method on instance
        class ConcreteImplementation(cloned_class):
            def abstract_method(self):
                return "implemented"

        instance = ConcreteImplementation()
        assert instance.concrete_method() == "concrete"

        # Should still be abstract - cannot instantiate directly
        with pytest.raises(TypeError):
            cloned_class()

    def test_repr_and_str_consistency(self):
        """Test that cloned classes have consistent representation."""

        class OriginalClass:
            def __repr__(self):
                return f"<{self.__class__.__name__} instance>"

        cloned_class = clone_class(OriginalClass, "ClonedClass")

        instance = cloned_class()
        assert "ClonedClass" in repr(instance)
        assert cloned_class.__name__ in str(type(instance))

    def test_clone_preserves_annotations(self):
        """Test that type annotations are preserved."""

        class WithAnnotations:
            attr: str = "test"

            def method(self, x: int) -> str:
                return str(x)

        cloned_class = clone_class(WithAnnotations, "ClonedAnnotations")

        if hasattr(WithAnnotations, "__annotations__"):
            assert cloned_class.__annotations__ == WithAnnotations.__annotations__

        assert cloned_class.attr == "test"
        instance = cloned_class()
        assert instance.method(42) == "42"

    def test_clone_domain_aggregate(self):
        """Test cloning an actual Protean domain aggregate."""
        from protean.core.aggregate import BaseAggregate
        from protean.fields import String, Integer, DateTime
        from datetime import datetime

        class User(BaseAggregate):
            name = String(max_length=50, required=True)
            email = String(max_length=100, required=True, unique=True)
            age = Integer(default=18)
            created_at = DateTime(default=datetime.now)

            @classmethod
            def create_user(cls, name, email):
                """Factory method to create a user."""
                return cls(name=name, email=email)

            def get_display_name(self):
                """Instance method to get display name."""
                return f"{self.name} <{self.email}>"

            @property
            def is_adult(self):
                """Property to check if user is an adult."""
                return self.age >= 18

        # Clone the aggregate
        cloned_aggregate = clone_class(User, "UserClone")

        # Test basic class attributes
        assert cloned_aggregate.__name__ == "UserClone"
        assert cloned_aggregate.__qualname__ == "UserClone"
        assert cloned_aggregate is not User

        # Test that it's still a BaseAggregate
        assert issubclass(cloned_aggregate, BaseAggregate)

        # Test domain object element type is preserved
        assert cloned_aggregate.element_type == User.element_type

        # Test that fields are preserved
        from protean.utils.reflection import fields

        original_fields = fields(User)
        cloned_fields = fields(cloned_aggregate)

        # Should have the same field names
        assert set(original_fields.keys()) == set(cloned_fields.keys())

        # Test that class methods are preserved and work correctly
        assert hasattr(cloned_aggregate, "create_user")
        test_instance = cloned_aggregate.create_user("Alice", "alice@example.com")
        assert test_instance.name == "Alice"
        assert test_instance.email == "alice@example.com"
        assert isinstance(test_instance, cloned_aggregate)

        # Test that instance methods work
        assert test_instance.get_display_name() == "Alice <alice@example.com>"

        # Test that properties work
        assert test_instance.is_adult

        # Test that default values are preserved
        assert test_instance.age == 18

        # Test that the cloned class maintains aggregate-specific behavior
        # Aggregates should have versioning attributes
        assert hasattr(cloned_aggregate, "_version")
        assert hasattr(cloned_aggregate, "_next_version")

        # Test that aggregate methods from BaseAggregate are inherited
        assert hasattr(cloned_aggregate, "_default_options")
        assert callable(cloned_aggregate._default_options)

        # Test that metadata behavior is preserved
        default_options = cloned_aggregate._default_options()
        assert isinstance(default_options, list)
        assert len(default_options) > 0

        # Test instantiation with different parameters
        user2 = cloned_aggregate(name="Bob", email="bob@example.com", age=25)
        assert user2.name == "Bob"
        assert user2.age == 25
        assert user2.is_adult

        # Ensure instances of original and cloned classes are different types
        original_user = User(name="Charlie", email="charlie@example.com")
        assert type(test_instance) is not type(original_user)
        assert type(test_instance).__name__ == "UserClone"
        assert type(original_user).__name__ == "User"
