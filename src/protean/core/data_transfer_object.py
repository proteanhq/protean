"""Data Transfer Object Functionality and Classes"""
# Standard Library Imports
import logging

# Protean
from protean.domain import DomainObjects
from protean.utils.container import BaseContainer

logger = logging.getLogger('protean.application')


class BaseDataTransferObject(BaseContainer):
    """The Base class for Protean-Compliant Domain Data Transfer Objects.

    Provides helper methods to custom define attributes, and find attribute names
    during runtime.

    Basic Usage::

        @DataTransferObject
        class Address:
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

    (or)

        class Address(BaseDataTransferObject):
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

        domain.register_element(Address)

    If persistence is required, the model associated with this data transfer object is retrieved dynamically.
    The data transfer object may be persisted along with its related entity, or separately in which case its model is
    retrieved from the repository factory. Model is usually initialized with a live DB connection.
    """

    element_type = DomainObjects.DATA_TRANSFER_OBJECT

    def __new__(cls, *args, **kwargs):
        if cls is BaseDataTransferObject:
            raise TypeError("BaseDataTransferObject cannot be instantiated")
        return super().__new__(cls)
