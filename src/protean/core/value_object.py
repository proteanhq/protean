"""Value Object Functionality and Classes"""
import logging

from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import BaseContainer

logger = logging.getLogger("protean.domain.value_object")


class BaseValueObject(BaseContainer):
    """The Base class for Protean-Compliant Domain Value Objects.

    Provides helper methods to custom define attributes, and find attribute names
    during runtime.

    Basic Usage::

        @ValueObject
        class Address:
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

    (or)

        class Address(BaseValueObject):
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

        domain.register_element(Address)

    If persistence is required, the model associated with this value object is retrieved dynamically.
    The value object may be persisted along with its related entity, or separately in which case its model is
    retrieved from the repository factory. Model is usually initialized with a live DB connection.
    """

    element_type = DomainObjects.VALUE_OBJECT

    class Meta:
        abstract = True


def value_object_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseValueObject, **kwargs)

    return element_cls
