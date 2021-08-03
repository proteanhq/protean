"""Aggregate Functionality and Classes"""
import logging

from protean.core.entity import BaseEntity
from protean.utils import DomainObjects, derive_element_class

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

    META_OPTIONS = [("provider", "default"), ("model", None)]

    def __new__(cls, *args, **kwargs):
        if cls is BaseAggregate:
            raise TypeError("BaseAggregate cannot be instantiated")
        return super().__new__(cls)


def aggregate_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseAggregate, **kwargs)
