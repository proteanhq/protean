"""Aggregate Functionality and Classes"""
import logging

from protean.container import EventedMixin
from protean.core.entity import BaseEntity
from protean.fields import Integer
from protean.utils import DomainObjects, derive_element_class, inflection

logger = logging.getLogger(__name__)


class BaseAggregate(EventedMixin, BaseEntity):
    """This is the base class for Domain Aggregates.

    Aggregates are fundamental, coarse-grained building blocks of a domain model. They are
    conceptual wholes - they enclose all behaviors and data of a distinct domain concept.
    Aggregates are often composed of one or more Aggregate Elements (Entities and Value Objests),
    that work together to codify a concept.

    This class provides helper methods to custom define aggregate attributes, and query attribute
    names during runtime.

    Basic Usage::

        @domain.aggregate
        class Dog:
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    During persistence, the model associated with this entity is retrieved dynamically from
        the repository factory. A model object is usually pre-initialized with a live DB connection.
    """

    element_type = DomainObjects.AGGREGATE

    def __new__(cls, *args, **kwargs):
        if cls is BaseAggregate:
            raise TypeError("BaseAggregate cannot be instantiated")
        return super().__new__(cls)

    # Track current version of Aggregate
    _version = Integer(default=-1)

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def _default_options(cls):
        return [
            ("provider", "default"),
            ("model", None),
            ("stream_name", inflection.underscore(cls.__name__)),
            ("schema_name", inflection.underscore(cls.__name__)),
        ]


def aggregate_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseAggregate, **kwargs)
