from typing import Any

_FIELDS = "__container_fields__"
_ID_FIELD_NAME = "__container_id_field_name__"


def fields(class_or_instance):
    """Return a tuple describing the fields of this dataclass.

    Accepts a dataclass or an instance of one. Tuple elements are of
    type Field.
    """

    # Might it be worth caching this, per class?
    try:
        fields_dict = getattr(class_or_instance, _FIELDS)
    except AttributeError:
        raise TypeError("must be called with a dataclass type or instance")

    return fields_dict


def id_field(class_or_instance):
    try:
        field_name = getattr(class_or_instance, _ID_FIELD_NAME)
    except AttributeError:
        raise TypeError("must be called with a dataclass type or instance")

    return fields(class_or_instance)[field_name]


def has_id_field(class_or_instance: Any) -> bool:
    """Check if class/instance has an identity attribute.

    Args:
        class_or_instance (Any): Domain Element to check.

    Returns:
        bool: True if the element has an identity field.
    """
    return hasattr(class_or_instance, _ID_FIELD_NAME)


def has_fields(class_or_instance):
    """Check if Protean element encloses fields"""
    return hasattr(class_or_instance, _FIELDS)


def attributes(class_or_instance):
    attributes_dict = {}

    for _, field_obj in fields(class_or_instance).items():
        # FIXME Make these checks elegant
        # Because of circular import issues, `Reference` class cannot be imported
        #   in this file. So we are resorting to check for method presence in
        #   field objects. Not the most elegant way, but will have to suffice
        #   until class heirarchies are restructured.
        if hasattr(field_obj, "get_shadow_fields"):
            shadow_fields = field_obj.get_shadow_fields()
            for _, shadow_field in shadow_fields:
                attributes_dict[shadow_field.attribute_name] = shadow_field
        elif hasattr(field_obj, "relation"):
            attributes_dict[field_obj.get_attribute_name()] = field_obj.relation
        elif not hasattr(field_obj, "to_cls"):
            attributes_dict[field_obj.get_attribute_name()] = field_obj
        else:  # This field is an association. Ignore recording it as an attribute
            pass

    return attributes_dict


def unique_fields(class_or_instance):
    """Return the unique fields for this class or instance"""
    return {
        field_name: field_obj
        for field_name, field_obj in attributes(class_or_instance).items()
        if field_obj.unique
    }


def declared_fields(class_or_instance):
    """Return a tuple describing the declared fields of this dataclass.

    Accepts a dataclass or an instance of one. Tuple elements are of
    type Field.

    `_version` is a auto-controlled, internal field, so is not returned
    among declared fields.
    """

    # Might it be worth caching this, per class?
    try:
        fields_dict = dict(getattr(class_or_instance, _FIELDS))
        fields_dict.pop("_version", None)
    except AttributeError:
        raise TypeError("must be called with a dataclass type or instance")

    return fields_dict
