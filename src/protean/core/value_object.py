"""Value Object Functionality and Classes"""
# Standard Library Imports
import logging

# Protean
from protean.core.exceptions import IncorrectUsageError
from protean.domain import DomainObjects
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

    def __new__(cls, *args, **kwargs):
        if cls is BaseValueObject:
            raise TypeError("BaseValueObject cannot be instantiated")
        return super().__new__(cls)


class ValueObjectFactory:
    @classmethod
    def prep_class(cls, element_cls, **kwargs):
        if issubclass(element_cls, BaseValueObject):
            new_element_cls = element_cls
        else:
            try:
                new_dict = element_cls.__dict__.copy()
                new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

                new_element_cls = type(
                    element_cls.__name__, (BaseValueObject,), new_dict
                )
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

        if hasattr(new_element_cls, "meta_"):
            if not (
                hasattr(new_element_cls.meta_, "aggregate_cls")
                and new_element_cls.meta_.aggregate_cls
            ):
                new_element_cls.meta_.aggregate_cls = kwargs.pop("aggregate_cls", None)

            new_element_cls.meta_.bounded_context = kwargs.pop("bounded_context", None)

        if not new_element_cls.meta_.aggregate_cls:
            raise IncorrectUsageError(
                "Value Objects need to be associated with an Aggregate"
            )

        return new_element_cls
