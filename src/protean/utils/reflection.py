from __future__ import annotations

from typing import TYPE_CHECKING, Type

from protean.exceptions import IncorrectUsageError

if TYPE_CHECKING:
    from protean.fields.base import Field
    from protean.utils.container import Element

_FIELDS = "__container_fields__"
_ID_FIELD_NAME = "__container_id_field_name__"


def fields(class_or_instance: Type[Element] | Element) -> dict[str, Field]:
    """Return a dictionary of fields in this element.

    Accepts an element or an instance of one.
    """

    # Might it be worth caching this, per class?
    try:
        fields_dict = getattr(class_or_instance, _FIELDS)
    except AttributeError:
        raise IncorrectUsageError(f"{class_or_instance} does not have fields")

    return fields_dict


def data_fields(class_or_instance: Type[Element] | Element) -> dict[str, Field]:
    """Return a dictionary of data fields in this element.

    Accepts an element or an instance of one.
    """
    try:
        fields_dict = dict(getattr(class_or_instance, _FIELDS))

        # Remove internal fields
        fields_dict.pop("_metadata", None)
    except AttributeError:
        raise IncorrectUsageError(f"{class_or_instance} does not have fields")

    return fields_dict


def id_field(class_or_instance: Type[Element] | Element) -> Field | None:
    """Return the identity field in this element."""
    try:
        field_name = getattr(class_or_instance, _ID_FIELD_NAME)
    except AttributeError:
        return None

    return fields(class_or_instance)[field_name]


def has_id_field(class_or_instance: Type[Element] | Element) -> bool:
    """Check if Element class/instance has an identity field.

    Args:
        class_or_instance (Any): Domain Element to check.

    Returns:
        bool: True if the element has an identity field.
    """
    return hasattr(class_or_instance, _ID_FIELD_NAME)


def has_fields(class_or_instance: Type[Element] | Element) -> bool:
    """Check if the element encloses fields"""
    return hasattr(class_or_instance, _FIELDS)


def attributes(class_or_instance: Type[Element] | Element) -> dict[str, Field]:
    """Return a dictionary of attributes of this element.

    Accepts a element or an instance of one.
    """
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


def unique_fields(class_or_instance: Type[Element] | Element) -> dict[str, Field]:
    """Return a dictionary of fields marked `unique` in this class or instance"""
    return {
        field_name: field_obj
        for field_name, field_obj in attributes(class_or_instance).items()
        if field_obj.unique
    }


def declared_fields(class_or_instance: Type[Element] | Element) -> dict[str, Field]:
    """Return a dictionary of declared fields in this element.

    Accepts a dataclass or an instance of one.

    `_version` is an auto-controlled, internal field, so is not returned
    among declared fields.
    """

    # Might it be worth caching this, per class?
    try:
        fields_dict = dict(getattr(class_or_instance, _FIELDS))

        # Remove internal fields
        fields_dict.pop("_version", None)
        fields_dict.pop("_metadata", None)
    except AttributeError:
        raise IncorrectUsageError(f"{class_or_instance} does not have fields")

    return fields_dict


def association_fields(class_or_instance: Type[Element] | Element) -> dict[str, Field]:
    """Return a dictionary of association fields in this elment.

    Accepts an Element or an instance of one.
    """
    from protean.fields.association import Association

    return {
        field_name: field_obj
        for field_name, field_obj in declared_fields(class_or_instance).items()
        if isinstance(field_obj, Association)
    }


def has_association_fields(class_or_instance: Type[Element] | Element) -> bool:
    """Check if Element has association fields."""
    return bool(association_fields(class_or_instance))
