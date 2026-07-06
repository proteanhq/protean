from typing import Any

NOT_PROVIDED = object()


class FieldCacheMixin:
    """Provide an API for working with the entity's fields value cache."""

    def get_cache_name(self) -> "str | None":
        raise NotImplementedError

    def get_cached_value(self, instance: Any, default: Any = NOT_PROVIDED) -> Any:
        cache_name = self.get_cache_name()
        try:
            return instance.state_.fields_cache[cache_name]
        except KeyError:
            if default is NOT_PROVIDED:
                raise
            return default

    def is_cached(self, instance: Any) -> bool:
        return self.get_cache_name() in instance.state_.fields_cache

    def set_cached_value(self, instance: Any, value: Any) -> None:
        instance.state_.fields_cache[self.get_cache_name()] = value

    def delete_cached_value(self, instance: Any) -> None:
        if self.get_cache_name() in instance.state_.fields_cache:
            del instance.state_.fields_cache[self.get_cache_name()]


class FieldDescriptorMixin:
    """Provide basic implementation to treat the Field as a descriptor"""

    # ``None`` on an unbound Field; populated with the owning entity's field /
    # attribute names by ``__set_name__`` once the class assigns the descriptor.
    field_name: str | None
    attribute_name: str | None
    # Set by ``__set_name__`` to the owning entity class once bound.
    _entity_cls: type

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize common Field Attributes"""
        # These are set up when the owner (Entity class) adds the field to itself
        self.field_name = None
        self.attribute_name = None
        self.description = kwargs.pop("description", None)
        self.referenced_as = kwargs.pop("referenced_as", None)

    def __set_name__(self, entity_cls: type, name: str) -> None:
        self.field_name = name
        self.attribute_name = self.get_attribute_name()

        # Record Entity setting up the field
        self._entity_cls = entity_cls

    def get_attribute_name(self) -> "str | None":
        """Return Attribute name for the attribute.

        Defaults to the field name in this base class, but can be overridden.
        Handy when defining complex objects with shadow attributes, like Foreign keys.
        """
        return self.referenced_as if self.referenced_as else self.field_name

    def __get__(self, instance: Any, owner: Any) -> Any:
        """Placeholder for handling `getattr` operations on attributes"""
        raise NotImplementedError

    def __set__(self, instance: Any, value: Any) -> None:
        """Placeholder for handling `setattr` operations on attributes"""
        raise NotImplementedError

    def __delete__(self, instance: Any) -> None:
        """Placeholder for handling `del` operations on attributes"""
        raise NotImplementedError
