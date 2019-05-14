"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""
# Standard Library Imports
import logging

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict

# Protean
from protean.core.entity import BaseEntity
from protean.core.exceptions import ConfigurationError
from protean.core.transport.request import BaseRequestObject
from protean.core.value_object import BaseValueObject
from protean.utils import fully_qualified_name, singleton

logger = logging.getLogger('protean.repository')


class DomainObjects(Enum):
    ENTITY = auto()
    VALUE_OBJECT = auto()
    REQUEST_OBJECT = auto()


@singleton
@dataclass
class _DomainRegistry:
    _entities: Dict[str, BaseEntity] = field(default_factory=dict)
    _value_objects: Dict[str, BaseValueObject] = field(default_factory=dict)
    _request_objects: Dict[str, BaseRequestObject] = field(default_factory=dict)

    @dataclass
    class DomainRecord:
        name: str
        qualname: str
        class_type: str
        cls: Any

    def register_entity(self, entity_cls):
        """Register an Entity"""
        entity_name = fully_qualified_name(entity_cls)

        try:
            entity = self._get_entity_by_class(entity_cls)

            if entity:
                # This probably is an accidental re-registration of the entity
                #   and we should warn the user of a possible repository confusion
                raise ConfigurationError(
                    f'Entity {entity_name} has already been registered')
        except AssertionError:
            self._entities[entity_cls.__name__] = _DomainRegistry.DomainRecord(
                name=entity_cls.__name__,
                qualname=entity_name,
                class_type=DomainObjects.ENTITY,
                cls=entity_cls
            )
            logger.debug(f'Registered Entity {entity_name} with Domain')

    def _find_entity_in_records_by_class_name(self, entity_name):
        """Fetch by Entity Name in values"""
        records = {
            key: value for (key, value)
            in self._entities.items()
            if value.name == entity_name
        }
        # If more than one record was found, we are dealing with the case of
        #   an Entity name present in multiple places (packages or plugins). Throw an error
        #   and ask for a fully qualified Entity name to be specified
        if len(records) > 1:
            raise ConfigurationError(
                f'Entity with name {entity_name} has been registered twice. '
                f'Please use fully qualified Entity name to specify the exact Entity.')
        elif len(records) == 1:
            return next(iter(records.values()))
        else:
            raise AssertionError(f'No Entity registered with name {entity_name}')

    def _get_entity_by_class(self, entity_cls):
        """Fetch Entity record with Entity class details"""
        entity_qualname = fully_qualified_name(entity_cls)
        if entity_qualname in self._entities:
            return self._entities[entity_qualname]
        else:
            return self._find_entity_in_records_by_class_name(entity_cls.__name__).cls

    def get_entity_by_name(self, entity_name):
        """Retrieve Entity class registered by `entity_name`"""
        if entity_name in self._entities:
            return self._entities[entity_name].cls
        else:
            return self._find_entity_in_records_by_class_name(entity_name).cls

    def register_value_object(self, value_object_cls):
        """Register a Value Object"""
        value_object_name = fully_qualified_name(value_object_cls)

        try:
            entity = self._get_value_object_by_class(value_object_cls)

            if entity:
                # This probably is an accidental re-registration of the entity
                #   and we should warn the user of a possible repository confusion
                raise ConfigurationError(
                    f'Entity {value_object_name} has already been registered')
        except AssertionError:
            self._value_objects[value_object_cls.__name__] = _DomainRegistry.DomainRecord(
                name=value_object_cls.__name__,
                qualname=value_object_name,
                class_type=DomainObjects.VALUE_OBJECT,
                cls=value_object_cls
            )
            logger.debug(f'Registered Value Object {value_object_name} with Domain')

    def _find_value_object_in_records_by_class_name(self, value_object_name):
        """Fetch by Entity Name in values"""
        records = {
            key: value for (key, value)
            in self._value_objects.items()
            if value.name == value_object_name
        }
        # If more than one record was found, we are dealing with the case of
        #   an Entity name present in multiple places (packages or plugins). Throw an error
        #   and ask for a fully qualified Entity name to be specified
        if len(records) > 1:
            raise ConfigurationError(
                f'Entity with name {value_object_name} has been registered twice. '
                f'Please use fully qualified Entity name to specify the exact Entity.')
        elif len(records) == 1:
            return next(iter(records.values()))
        else:
            raise AssertionError(f'No Entity registered with name {value_object_name}')

    def _get_value_object_by_class(self, value_object_cls):
        """Fetch Value Object record with Value Object class details"""
        value_object_qualname = fully_qualified_name(value_object_cls)
        if value_object_qualname in self._value_objects:
            return self._value_objects[value_object_qualname]
        else:
            return self._find_value_object_in_records_by_class_name(value_object_cls.__name__).cls

    def get_value_object_by_name(self, value_object_name):
        """Retrieve Value Object class registered by `value_object_name`"""
        if value_object_name in self._value_objects:
            return self._value_objects[value_object_name].cls
        else:
            return self._find_value_object_in_records_by_class_name(value_object_name).cls

    def register_request_object(self, request_object_cls):
        """Register a Request Object"""
        request_object_name = fully_qualified_name(request_object_cls)

        try:
            ro = self._get_request_object_by_class(request_object_cls)

            if ro:
                # We are going to ignore repetitive registrations of request objects
                #   as they are usually declared along with a service and used only for the
                #   lifetime of the service
                #
                # FIXME Ensure that ignoring repetitive RO registrations is fine
                pass
        except AssertionError:
            self._request_objects[request_object_cls.__name__] = _DomainRegistry.DomainRecord(
                name=request_object_cls.__name__,
                qualname=request_object_name,
                class_type=DomainObjects.REQUEST_OBJECT,
                cls=request_object_cls
            )
            logger.debug(f'Registered Request Object {request_object_name} with Domain')

    def _find_request_object_in_records_by_class_name(self, request_object_name):
        """Fetch by Request Object Name in values"""
        records = {
            key: value for (key, value)
            in self._request_objects.items()
            if value.name == request_object_name
        }
        # If more than one record was found, we are dealing with the case of
        #   an Request Object name present in multiple places (packages or plugins). Throw an error
        #   and ask for a fully qualified Entity name to be specified
        if len(records) > 1:
            raise ConfigurationError(
                f'Request Object with name {request_object_name} has been registered twice. '
                f'Please use fully qualified Request Object Class name to specify the exact class.')
        elif len(records) == 1:
            return next(iter(records.values()))
        else:
            raise AssertionError(f'No Request Object registered with name {request_object_name}')

    def _get_request_object_by_class(self, request_object_cls):
        """Fetch Request Object record with Request Object class details"""
        request_object_qualname = fully_qualified_name(request_object_cls)
        if request_object_qualname in self._request_objects:
            return self._request_objects[request_object_qualname]
        else:
            return self._find_request_object_in_records_by_class_name(request_object_cls.__name__).cls

    def get_request_object_by_name(self, request_object_name):
        """Retrieve Request Object class registered by `request_object_name`"""
        if request_object_name in self._request_objects:
            return self._request_objects[request_object_name].cls
        else:
            return self._find_request_object_in_records_by_class_name(request_object_name).cls


# Singleton Registry, populated with the help of @<DomainElement> decorators
domain_registry = _DomainRegistry()


def _process_entity(cls, aggregate, bounded_context, root):
    """Register class into the domain"""
    # Dynamically subclass from BaseEntity
    new_dict = cls.__dict__.copy()
    new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion
    new_cls = type(cls.__name__, (BaseEntity, ), new_dict)

    # Enrich element with domain information
    new_cls.meta_.aggregate = aggregate
    new_cls.meta_.bounded_context = bounded_context
    new_cls.meta_.root = root

    # Register element with domain
    domain_registry.register_entity(new_cls)

    return new_cls


# _cls should never be specified by keyword, so start it with an
# underscore.  The presence of _cls is used to detect if this
# decorator is being called with parameters or not.
def Entity(_cls=None, *, aggregate=None, bounded_context=None, root=False):
    """Returns the same class that was passed in,
    after recording its presence in the domain
    """

    def wrap(cls):
        return _process_entity(cls, aggregate, bounded_context, root)

    # See if we're being called as @Entity or @Entity().
    if _cls is None:
        # We're called with parens.
        return wrap

    # We're called as @dataclass without parens.
    return wrap(_cls)


def _process_value_object(cls, aggregate, bounded_context):
    """Register class into the domain"""
    # Dynamically subclass from BaseValueObject
    new_dict = cls.__dict__.copy()
    new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion
    new_cls = type(cls.__name__, (BaseValueObject, ), new_dict)

    # Enrich element with domain information
    new_cls.meta_.aggregate = aggregate
    new_cls.meta_.bounded_context = bounded_context

    # Register element with domain
    domain_registry.register_value_object(new_cls)

    return new_cls


def ValueObject(_cls=None, *, aggregate=None, bounded_context=None):
    """Returns the same class that was passed in,
    after recording its presence in the domain
    """

    def wrap(cls):
        return _process_value_object(cls, aggregate, bounded_context)

    # See if we're being called as @Entity or @Entity().
    if _cls is None:
        # We're called with parens.
        return wrap

    # We're called as @dataclass without parens.
    return wrap(_cls)


def _process_request_object(cls, aggregate, bounded_context):
    """Register class into the domain"""
    # Dynamically subclass from BaseRequestObject
    new_dict = cls.__dict__.copy()
    new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion
    new_cls = type(cls.__name__, (BaseRequestObject, ), new_dict)

    # Enrich element with domain information
    # FIXME Add `meta_` attributes to Request Object
    # new_cls.meta_.aggregate = aggregate
    # new_cls.meta_.bounded_context = bounded_context

    # Register element with domain
    domain_registry.register_request_object(new_cls)

    return new_cls


def RequestObject(_cls=None, *, aggregate=None, bounded_context=None):
    """Returns the same class that was passed in,
    after recording its presence in the domain
    """

    def wrap(cls):
        return _process_request_object(cls, aggregate, bounded_context)

    # See if we're being called as @Entity or @Entity().
    if _cls is None:
        # We're called with parens.
        return wrap

    # We're called as @dataclass without parens.
    return wrap(_cls)


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

    def __init__(self, domain_name):
        self.domain_name = domain_name

    @property
    def registry(self):
        return domain_registry

    def register_elements(self) -> None:
        from protean.core.repository import repo_factory
        for entity in domain_registry._entities:
            repo_factory.register(domain_registry._entities[entity].cls)

    def register_element(self, element) -> None:
        from protean.core.repository import repo_factory
        repo_factory.register(element)

    def unregister_element(self, element) -> None:
        from protean.core.repository import repo_factory
        repo_factory.unregister(element)
