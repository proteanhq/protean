"""Module for defining embedded fields"""

from functools import lru_cache

from protean.exceptions import IncorrectUsageError
from protean.fields import Field
from protean.utils.reflection import declared_fields


class _ShadowField(Field):
    """Shadow Attribute Field to back Value Object Fields"""

    def __init__(self, owner, field_name, field_obj, **kwargs):
        """Preserve link to owner, and original field type for later reference"""
        super().__init__(**kwargs)

        self.owner = owner
        self.field_name = field_name
        self.field_obj = field_obj

    def __set__(self, instance, value):
        """Override `__set__` to update owner field and silently fail to update values.
        When the value object's value is set, the embedded fields will be automatically filled.
        """

    def __delete__(self, instance):
        """Nullify values and linkages"""
        self._reset_values(instance)

    def _cast_to_type(self, value):
        """Verify type of value assigned to the shadow field"""
        # FIXME Verify that the value being assigned is compatible with the remote field
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        raise NotImplementedError

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        instance.__dict__.pop(self.field_name, None)


class ValueObject(Field):
    """
    Represents a field that holds a value object.

    This field is used to embed a value object within an entity. It provides
    functionality to handle the value object's fields and their values.

    Args:
        value_object_cls (class): The class of the value object to be embedded.

    Attributes:
        embedded_fields (dict): A dictionary that holds the embedded fields of the value object.

    """

    def __init__(self, value_object_cls, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not isinstance(value_object_cls, str):
            # Validate the class being passed is a subclass of BaseValueObject
            self._validate_value_object_cls(value_object_cls)

        self._value_object_cls = value_object_cls

        self._embedded_fields = {}

    def _validate_value_object_cls(self, value_object_cls):
        """Validate that the value object class is a subclass of BaseValueObject"""
        from protean.core.value_object import BaseValueObject

        if not issubclass(value_object_cls, BaseValueObject):
            raise IncorrectUsageError(
                f"`{value_object_cls.__name__}` is not a valid Value Object "
                "and cannot be embedded in a Value Object field"
            )

    @property
    def value_object_cls(self):
        return self._value_object_cls

    def _resolve_to_cls(self, domain, value_object_cls, owner_cls):
        assert isinstance(self._value_object_cls, str)

        # Validate the class being passed is a subclass of BaseValueObject
        self._validate_value_object_cls(value_object_cls)

        self._value_object_cls = value_object_cls

        self._construct_embedded_fields()

        # Refresh attribute name, now that we know `value_object_cls` class
        self.attribute_name = self.get_attribute_name()

    @property
    @lru_cache()
    def embedded_fields(self):
        """Property to retrieve embedded fields"""
        if len(self._embedded_fields) == 0:
            self._construct_embedded_fields()

        return self._embedded_fields

    def _construct_embedded_fields(self):
        """Construct embedded fields"""
        for (
            field_name,
            field_obj,
        ) in declared_fields(self._value_object_cls).items():
            self._embedded_fields[field_name] = _ShadowField(
                self,
                field_name,
                field_obj,
                # FIXME Pass all other kwargs here
                #   Because we want the shadow field to mimic the behavior of the actual field
                #   Which means that ShadowField somehow has to become an Integer, Float, String, etc.
                referenced_as=field_obj.referenced_as,
            )

        for embedded_field in self.embedded_fields.values():
            if embedded_field.referenced_as:
                embedded_field.attribute_name = embedded_field.referenced_as
            else:
                # VO is associated with an aggregate/entity
                if self.field_name is not None:
                    # Refresh underlying embedded field names
                    embedded_field.attribute_name = (
                        self.field_name + "_" + embedded_field.field_name
                    )
                else:
                    # VO is being used standalone
                    embedded_field.attribute_name = embedded_field.field_name

    def __set_name__(self, entity_cls, name):
        super().__set_name__(entity_cls, name)

    def get_shadow_fields(self):
        """Return shadow field
        Primarily used during Entity initialization to register shadow field"""
        shadow_fields = []
        for field in self.embedded_fields.values():
            shadow_fields.append((field.attribute_name, field))
        return shadow_fields

    def _cast_to_type(self, value):
        # If the supplied value is a dict, reconstruct value object
        if isinstance(value, dict):
            value = self._value_object_cls(**value)

        if not isinstance(value, self._value_object_cls):
            self.fail("invalid", value=value)
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return (
            {
                field_name: shadow_field_obj.field_obj.as_dict(
                    getattr(value, field_name, None)
                )
                for field_name, shadow_field_obj in self.embedded_fields.items()
            }
            if value
            else None
        )

    def __set__(self, instance, value):
        """Override `__set__` to coordinate between value object and its embedded fields"""
        value = self._load(value)

        if value:
            # Check if the reference object has been saved. Otherwise, throw ValueError
            self._set_own_value(instance, value)
            self._set_embedded_values(instance, value)
        else:
            self._reset_values(instance)

    def _set_own_value(self, instance, value):
        if value is None:
            instance.__dict__.pop(self.field_name, None)
        else:
            instance.__dict__[self.field_name] = value

    def _set_embedded_values(self, instance, value):
        if value is None:
            for field_name in self.embedded_fields:
                attribute_name = self.embedded_fields[field_name].attribute_name
                instance.__dict__.pop(attribute_name, None)
                self.embedded_fields[field_name].value = None
        else:
            for field_name in declared_fields(value):
                self.embedded_fields[field_name].value = getattr(value, field_name)
                attribute_name = self.embedded_fields[field_name].attribute_name
                instance.__dict__[attribute_name] = getattr(value, field_name)

    def __delete__(self, instance):
        self._reset_values(instance)

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        self._set_own_value(instance, None)
        self._set_embedded_values(instance, None)
