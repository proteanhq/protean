"""Aggregate Functionality and Classes"""

import inspect
import logging

from protean.container import EventedMixin
from protean.core.entity import BaseEntity
from protean.exceptions import NotSupportedError
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
            raise NotSupportedError("BaseAggregate cannot be instantiated")
        return super().__new__(cls)

    # Track current version of Aggregate
    _version = Integer(default=-1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set root in all child elements
        #   This is where we kick-off the process of setting the owner and root
        self._set_root_and_owner(self, self)

    @classmethod
    def _default_options(cls):
        return [
            ("auto_add_id_field", True),
            ("provider", "default"),
            ("model", None),
            ("stream_name", inflection.underscore(cls.__name__)),
            ("schema_name", inflection.underscore(cls.__name__)),
        ]


def aggregate_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseAggregate, **kwargs)

    # Iterate through methods marked as `@invariant` and record them for later use
    #   `_invariants` is a dictionary initialized in BaseEntity.__init_subclass__
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_invariant"):
            element_cls._invariants[method._invariant][method_name] = method

    return element_cls


# Context manager to temporarily disable invariant checks on aggregate
class atomic_change:
    def __init__(self, aggregate):
        self.aggregate = aggregate

    def __enter__(self):
        # Temporary disable invariant checks
        self.aggregate._precheck()
        self.aggregate._disable_invariant_checks = True

    def __exit__(self, *args):
        # Validate on exit to trigger invariant checks
        self.aggregate._disable_invariant_checks = False
        self.aggregate._postcheck()
