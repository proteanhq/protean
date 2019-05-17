"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""
# Standard Library Imports
import logging

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict

# Protean
from protean.core.provider import Providers
from protean.core.exceptions import ConfigurationError
from protean.utils import fully_qualified_name, singleton

logger = logging.getLogger('protean.repository')


class DomainObjects(Enum):
    AGGREGATE = auto()
    ENTITY = auto()
    REQUEST_OBJECT = auto()
    VALUE_OBJECT = auto()


@singleton
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
        element_name = fully_qualified_name(element_cls)

        try:
            element = self._get_element_by_class(element_type, element_cls)
            if element:
                raise ConfigurationError(f'Element {element_name} has already been registered')
        except AssertionError:
            element_record = _DomainRegistry.DomainRecord(
                name=element_cls.__name__,
                qualname=element_name,
                class_type=element_type.value,
                cls=element_cls
            )

            if element_type.name not in DomainObjects.__members__:
                return NotImplemented
            else:
                self._elements[element_type.value][element_cls.__name__] = element_record

            logger.debug(f'Registered Element {element_name} with Domain')

    def _find_element_in_records_by_class_name(self, element_type, element_name):
        records = {
            key: value for (key, value)
            in self._elements[element_type.value].items()
            if value.name == element_name
        }
        # If more than one record was found, we are dealing with the case of
        #   an element name present in multiple places (packages or plugins). Throw an error
        #   and ask for a fully qualified element name to be specified
        if len(records) > 1:
            raise ConfigurationError(
                f'Entity with name {element_name} has been registered twice. '
                f'Please use fully qualified element name to specify the exact element.')
        elif len(records) == 1:
            return next(iter(records.values()))
        else:
            raise AssertionError(f'No Element registered with name {element_name}')

    def _get_element_by_class(self, element_type, element_cls):
        element_qualname = fully_qualified_name(element_cls)
        if element_qualname in self._elements[element_type.value]:
            return self._elements[element_type.value][element_qualname]
        else:
            return self._find_element_in_records_by_class_name(element_type, element_cls.__name__).cls

    def get_element_by_name(self, element_type, element_name):
        if element_name in self._elements[element_type]:
            return self._elements[element_type][element_name].cls
        else:
            return self._find_element_in_records_by_class_name(element_name).cls


# Singleton Registry, populated with the help of @<DomainElement> decorators
domain_registry = _DomainRegistry()


def _register_element(element_type, element_cls, aggregate=None, bounded_context=None, **kwargs):
    """Register class into the domain"""
    new_dict = element_cls.__dict__.copy()
    new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion

    from protean.core.entity import BaseEntity
    from protean.core.transport.request import BaseRequestObject
    from protean.core.value_object import BaseValueObject

    base_class_mapping = {
        DomainObjects.AGGREGATE.value: BaseEntity,
        DomainObjects.ENTITY.value: BaseEntity,
        DomainObjects.REQUEST_OBJECT.value: BaseRequestObject,
        DomainObjects.VALUE_OBJECT.value: BaseValueObject
    }

    if element_type.value in base_class_mapping:
        new_cls = type(element_cls.__name__, (base_class_mapping[element_type.value], ), new_dict)
    else:
        raise NotImplementedError

    # Enrich element with domain information
    if hasattr(new_cls, 'meta_'):
        new_cls.meta_.aggregate = aggregate
        new_cls.meta_.bounded_context = bounded_context

    # Register element with domain
    domain_registry.register_element(element_type, new_cls)

    return new_cls


# _cls should never be specified by keyword, so start it with an
# underscore.  The presence of _cls is used to detect if this
# decorator is being called with parameters or not.
def DomainElement(element_type, _cls=None, *, aggregate=None, bounded_context=None):
    """Returns the registered class after decoarating it and recording its presence in the domain"""

    def wrap(cls):
        return _register_element(element_type, cls, aggregate, bounded_context)

    # See if we're being called as @Entity or @Entity().
    if _cls is None:
        # We're called with parens.
        return wrap

    # We're called as @dataclass without parens.
    return wrap(_cls)


def Entity(_cls=None, aggregate=None, bounded_context=None, **kwargs):
    return DomainElement(DomainObjects.ENTITY, _cls=_cls, **kwargs,
                         aggregate=aggregate, bounded_context=bounded_context)


def ValueObject(_cls=None, aggregate=None, bounded_context=None, **kwargs):
    return DomainElement(DomainObjects.VALUE_OBJECT, _cls=_cls, **kwargs,
                         aggregate=aggregate, bounded_context=bounded_context)


def RequestObject(_cls=None, aggregate=None, bounded_context=None, **kwargs):
    return DomainElement(DomainObjects.REQUEST_OBJECT, _cls=_cls, **kwargs,
                         aggregate=aggregate, bounded_context=bounded_context)


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

    def __init__(self, domain_name=__name__):
        self.domain_name = domain_name

        self.providers = Providers()

    @property
    def registry(self):
        return domain_registry

    def get_repository(self, entity_cls):
        from protean.core.repository.factory import repo_factory
        return repo_factory.get_repository(entity_cls)

    def get_model(self, entity_cls):
        from protean.core.repository.factory import repo_factory
        return repo_factory.get_model(entity_cls)

    def register_elements(self) -> None:
        from protean.core.repository.factory import repo_factory

        for aggregate_record in domain_registry._elements[DomainObjects.AGGREGATE.value]:
            repo_factory.register(aggregate_record.cls)
        for entity_name, entity_record in domain_registry._elements[DomainObjects.ENTITY.value].items():
            repo_factory.register(entity_record.cls)

    def register_element(self, element) -> None:
        from protean.core.entity import _EntityMetaclass
        if isinstance(element, _EntityMetaclass):
            from protean.core.repository.factory import repo_factory
            repo_factory.register(element)
        else:
            raise NotImplementedError

    def unregister_element(self, element) -> None:
        from protean.core.entity import _EntityMetaclass
        if isinstance(element, _EntityMetaclass):
            from protean.core.repository.factory import repo_factory
            repo_factory.unregister(element)
        else:
            raise NotImplementedError
