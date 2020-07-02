"""Aggregate Functionality and Classes"""
# Standard Library Imports
import logging

# Protean
from protean.core.entity import BaseEntity
from protean.core.exceptions import IncorrectUsageError, NotSupportedError
from protean.domain import DomainObjects

logger = logging.getLogger("protean.domain.aggregate")


class BaseAggregate(BaseEntity):
    """The Base class for Protean-Compliant Domain Aggregates.

    Provides helper methods to custom define aggregate attributes, and query attribute names
    during runtime.

    Basic Usage::

        @domain.aggregate
        class Dog:
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    (or)

        class Dog(BaseAggregate):
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

        domain.register_element(Dog)

    During persistence, the model associated with this entity is retrieved dynamically from
            the repository factory. Model is usually initialized with a live DB connection.
    """

    element_type = DomainObjects.AGGREGATE

    def __new__(cls, *args, **kwargs):
        if cls is BaseAggregate:
            raise TypeError("BaseAggregate cannot be instantiated")
        return super().__new__(cls)


class AggregateFactory:
    @classmethod
    def prep_class(cls, element_cls, **kwargs):
        if issubclass(element_cls, BaseAggregate):
            new_element_cls = element_cls
        else:
            try:
                new_dict = element_cls.__dict__.copy()
                new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

                new_element_cls = type(element_cls.__name__, (BaseAggregate,), new_dict)
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

        cls._validate_aggregate_class(new_element_cls)

        new_element_cls.meta_.provider = (
            kwargs.pop("provider", None)
            or (hasattr(new_element_cls, "meta_") and new_element_cls.meta_.provider)
            or "default"
        )
        new_element_cls.meta_.model = (
            kwargs.pop("model", None)
            or (hasattr(new_element_cls, "meta_") and new_element_cls.meta_.model)
            or None
        )
        new_element_cls.meta_.bounded_context = kwargs.pop("bounded_context", None) or (
            hasattr(new_element_cls, "meta_") and new_element_cls.meta_.bounded_context
        )

        return new_element_cls

    @classmethod
    def _validate_aggregate_class(cls, element_cls):
        if not issubclass(element_cls, BaseAggregate):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseAggregate`"
            )

        if element_cls.meta_.abstract is True:
            raise NotSupportedError(
                f"{element_cls.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        return True
