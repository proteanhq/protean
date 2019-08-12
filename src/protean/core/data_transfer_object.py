"""Data Transfer Object Functionality and Classes"""
from protean.utils.container import BaseContainer


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

    def __new__(cls, *args, **kwargs):
        if cls is BaseDataTransferObject:
            raise TypeError("BaseDataTransferObject cannot be instantiated")
        return super().__new__(cls)
