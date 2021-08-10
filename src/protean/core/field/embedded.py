"""Module for defining embedded fields"""

from protean.core.field.base import Field
from protean.utils import DomainObjects, fetch_element_cls_from_registry


class _ShadowField(Field):
    """Shadow Attribute Field to back Value Object Fields"""

    def __init__(self, owner, field_name, field_type, **kwargs):
        """Preserve link to owner, and original field type for later reference"""
        super().__init__(**kwargs)

        self.owner = owner
        self.field_name = field_name
        self.field_type = field_type

    def __set__(self, instance, value):
        """Override `__set__` to update owner field and silently fail to update values.
        When the value object's value is set, the embedded fields will be automatically filled.
        """
        pass

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
    """Field implementation for Value Objects"""

    def __init__(self, value_object_cls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value_object_cls = value_object_cls

        self.embedded_fields = {}
        for (
            field_name,
            field_obj,
        ) in self._value_object_cls.meta_.declared_fields.items():
            self.embedded_fields[field_name] = _ShadowField(
                self,
                field_name,
                field_obj.__class__,
                # FIXME Pass all other kwargs here
                #   Because we want the shadow field to mimic the behavior of the actual field
                #   Which means that ShadowField somehow has to become an Integer, Float, String, etc.
                referenced_as=field_obj.referenced_as,
            )

    @property
    def value_object_cls(self):
        """Property to retrieve value_object_cls as a Value Object when possible"""
        # Checks if ``value_object_cls`` is a string
        #   If it is, checks if the Value Object is imported and available
        #   If it is, register the class
        try:
            if isinstance(self._value_object_cls, str):
                self._value_object_cls = fetch_element_cls_from_registry(
                    self._value_object_cls, (DomainObjects.VALUE_OBJECT,)
                )
        except AssertionError:
            # Preserve ``value_object_cls`` as a string and we will hook up the entity later
            pass

        return self._value_object_cls

    def __set_name__(self, entity_cls, name):
        super().__set_name__(entity_cls, name)
        # Refresh underlying embedded field names
        for embedded_field in self.embedded_fields.values():
            if embedded_field.referenced_as:
                embedded_field.attribute_name = embedded_field.referenced_as
            else:
                embedded_field.attribute_name = (
                    self.field_name + "_" + embedded_field.field_name
                )

    def get_shadow_fields(self):
        """Return shadow field
        Primarily used during Entity initialization to register shadow field"""
        shadow_fields = []
        for field in self.embedded_fields.values():
            shadow_fields.append((field.attribute_name, field))
        return shadow_fields

    def _cast_to_type(self, value):
        if not isinstance(value, self._value_object_cls):
            self.fail("invalid", value=value)
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return {
            field_obj.attribute_name: getattr(value, field_name)
            for field_name, field_obj in self.embedded_fields.items()
        }

    def __set__(self, instance, value):
        """Override `__set__` to coordinate between value object and its embedded fields"""
        if isinstance(self.value_object_cls, str):
            self.value_object_cls = fetch_element_cls_from_registry(
                self.value_object_cls, (DomainObjects.VALUE_OBJECT,)
            )

            # Refresh attribute name, now that we know `value_object_cls` class
            self.attribute_name = self.get_attribute_name()

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
            for field_name in value.meta_.declared_fields:
                self.embedded_fields[field_name].value = getattr(value, field_name)
                attribute_name = self.embedded_fields[field_name].attribute_name
                instance.__dict__[attribute_name] = getattr(value, field_name)

    def __delete__(self, instance):
        self._reset_values(instance)

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        self._set_own_value(instance, None)
        self._set_embedded_values(instance, None)
