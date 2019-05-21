"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""
# Standard Library Imports
import logging

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

# Protean
from protean.core.provider import Providers
from protean.core.exceptions import ConfigurationError
from protean.utils import fully_qualified_name

logger = logging.getLogger('protean.repository')


class DomainObjects(Enum):
    AGGREGATE = 'AGGREGATE'
    ENTITY = 'ENTITY'
    REQUEST_OBJECT = 'REQUEST_OBJECT'
    VALUE_OBJECT = 'VALUE_OBJECT'


@dataclass
class _DomainRegistry:
    _elements: Dict[str, dict] = field(default_factory=dict)

    @dataclass
    class DomainRecord:
        name: str
        qualname: str
        class_type: str
        cls: Any

    def __post_init__(self):
        """Initialize placeholders for element types"""
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def register_element(self, element_type, element_cls):
        if element_type.name not in DomainObjects.__members__:
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        element = self._elements[element_type.value][element_name]
        if element:
            raise ConfigurationError(f'Element {element_name} has already been registered')
        else:
            element_record = _DomainRegistry.DomainRecord(
                name=element_cls.__name__,
                qualname=element_name,
                class_type=element_type.value,
                cls=element_cls
            )

            self._elements[element_type.value][element_name] = element_record

            logger.debug(f'Registered Element {element_name} with Domain as a {element_type.value}')


class Domain:
    """The domain object is a one-stop gateway to:
    * Registrating Domain Objects/Concepts
    * Querying/Retrieving Domain Artifacts like Entities, Services, etc.
    * Retrieve injected infrastructure adapters

    Usually you create a :class:`Domain` instance in your main module or
    in the :file:`__init__.py` file of your package like this::

        from protean import Domain
        domain = Domain(__name__)

    :param domain_name: the name of the domain
    """

    from protean.core.aggregate import BaseAggregate
    from protean.core.entity import BaseEntity
    from protean.core.transport.request import BaseRequestObject
    from protean.core.value_object import BaseValueObject

    base_class_mapping = {
            DomainObjects.AGGREGATE.value: BaseAggregate,
            DomainObjects.ENTITY.value: BaseEntity,
            DomainObjects.REQUEST_OBJECT.value: BaseRequestObject,
            DomainObjects.VALUE_OBJECT.value: BaseValueObject
        }

    def __init__(self, domain_name=__name__):
        self.domain_name = domain_name

        # Registry for all domain Objects
        self._domain_registry = _DomainRegistry()

        self.providers = Providers()

    @property
    def registry(self):
        return self._domain_registry

    @property
    def aggregates(self):
        return self._domain_registry._elements[DomainObjects.AGGREGATE.value]

    @property
    def entities(self):
        return self._domain_registry._elements[DomainObjects.ENTITY.value]

    @property
    def value_objects(self):
        return self._domain_registry._elements[DomainObjects.VALUE_OBJECT.value]

    @property
    def request_objects(self):
        return self._domain_registry._elements[DomainObjects.REQUEST_OBJECT.value]

    def _register_element(self, element_type, element_cls, aggregate=None, bounded_context=None, **kwargs):
        """Register class into the domain"""
        new_dict = element_cls.__dict__.copy()
        new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion

        if element_type.value in self.base_class_mapping:
            new_cls = type(element_cls.__name__, (self.base_class_mapping[element_type.value], ), new_dict)
        else:
            raise NotImplementedError

        # Enrich element with domain information
        if hasattr(new_cls, 'meta_'):
            new_cls.meta_.aggregate = aggregate
            new_cls.meta_.bounded_context = bounded_context

        # Register element with domain
        self._domain_registry.register_element(element_type, new_cls)

        return new_cls

    # _cls should never be specified by keyword, so start it with an
    # underscore.  The presence of _cls is used to detect if this
    # decorator is being called with parameters or not.
    def _domain_element(self, element_type, _cls=None, *, aggregate=None, bounded_context=None):
        """Returns the registered class after decoarating it and recording its presence in the domain"""

        def wrap(cls):
            return self._register_element(element_type, cls, aggregate, bounded_context)

        # See if we're being called as @Entity or @Entity().
        if _cls is None:
            # We're called with parens.
            return wrap

        # We're called as @dataclass without parens.
        return wrap(_cls)

    def aggregate(self, _cls=None, aggregate=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.AGGREGATE, _cls=_cls, **kwargs,
            aggregate=aggregate, bounded_context=bounded_context)

    def entity(self, _cls=None, aggregate=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.ENTITY, _cls=_cls, **kwargs,
            aggregate=aggregate, bounded_context=bounded_context)

    def value_object(self, _cls=None, aggregate=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.VALUE_OBJECT, _cls=_cls, **kwargs,
            aggregate=aggregate, bounded_context=bounded_context)

    def request_object(self, _cls=None, aggregate=None, bounded_context=None, **kwargs):
        return self._domain_element(
            DomainObjects.REQUEST_OBJECT, _cls=_cls, **kwargs,
            aggregate=aggregate, bounded_context=bounded_context)

    def register(self, element_cls, aggregate=None, bounded_context=None, **kwargs):
        """Register an element already subclassed with the correct Hierarchy"""
        element_types = [
            element_type
            for element_type, element_class in self.base_class_mapping.items()
            if element_class in element_cls.__bases__
        ]

        if len(element_types) == 0:
            raise NotImplementedError

        return self._register_element(
            DomainObjects[element_types.pop()], element_cls,
            aggregate, bounded_context, **kwargs)
