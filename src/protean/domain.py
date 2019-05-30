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
from protean.core.exceptions import ConfigurationError, IncorrectUsageError, NotSupportedError, ObjectNotFoundError
from protean.utils import fully_qualified_name

logger = logging.getLogger('protean.repository')


class DomainObjects(Enum):
    AGGREGATE = 'AGGREGATE'
    ENTITY = 'ENTITY'
    REPOSITORY = 'REPOSITORY'
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
        provider_name: str
        model_cls: Any

    def __post_init__(self):
        """Initialize placeholders for element types"""
        for element_type in DomainObjects:
            self._elements[element_type.value] = defaultdict(dict)

    def register_element(self, element_type, element_cls, provider_name=None, model_cls=None):
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
                cls=element_cls,
                provider_name=provider_name,
                model_cls=model_cls  # FIXME Remove `model_cls` from being stored here
            )

            self._elements[element_type.value][element_name] = element_record

            logger.debug(f'Registered Element {element_name} with Domain as a {element_type.value}')

    def unregister_element(self, element_type, element_cls):
        if element_type.name not in DomainObjects.__members__:
            raise NotImplementedError

        element_name = fully_qualified_name(element_cls)

        self._elements[element_type.value].pop(element_name, None)


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
    from protean.core.repository.base import BaseRepository
    from protean.core.transport.request import BaseRequestObject
    from protean.core.value_object import BaseValueObject

    base_class_mapping = {
            DomainObjects.AGGREGATE.value: BaseAggregate,
            DomainObjects.ENTITY.value: BaseEntity,
            DomainObjects.REPOSITORY.value: BaseRepository,
            DomainObjects.REQUEST_OBJECT.value: BaseRequestObject,
            DomainObjects.VALUE_OBJECT.value: BaseValueObject
        }

    def __init__(self, domain_name=__name__, config_file=None):
        self.domain_name = domain_name

        # Registry for all domain Objects
        self._domain_registry = _DomainRegistry()

        self.providers = Providers(self, config_file=config_file)

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

    @property
    def repositories(self):
        return self._domain_registry._elements[DomainObjects.REPOSITORY.value]

    def _register_element(self, element_type, element_cls, **kwargs):
        """Register class into the domain"""
        new_dict = element_cls.__dict__.copy()
        new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion

        try:
            if element_type.value not in self.base_class_mapping:
                raise

            new_cls = type(element_cls.__name__, (self.base_class_mapping[element_type.value], ), new_dict)
        except BaseException as exc:
            logger.debug("Error during Element registration:", repr(exc))
            raise IncorrectUsageError(
                "Invalid class {element_cls.__name__} for type {element_type.value}"
                " (Error: {exc})"
                )

        # Decorate Aggregate classes with Provider and Model info
        provider_name = None
        model_cls = None
        if element_type == DomainObjects.AGGREGATE and self._validate_aggregate_class(new_cls):
            provider_name = provider_name or new_cls.meta_.provider or 'default'
            model_cls = None  # FIXME Add ability to specify model_cls explicitly

        aggregate = None
        if element_type == DomainObjects.REPOSITORY and self._validate_repository_class(new_cls):
            aggregate = new_cls.meta_.aggregate or kwargs.pop('aggregate', None)
            if not aggregate:
                raise IncorrectUsageError("Repositories need to be associated with an Aggregate Class")

        # Enrich element with domain information
        if hasattr(new_cls, 'meta_'):
            new_cls.meta_.aggregate = aggregate or kwargs.pop('aggregate', None)
            new_cls.meta_.bounded_context = kwargs.pop('bounded_context', None)

        # Register element with domain
        self._domain_registry.register_element(
            element_type, new_cls, provider_name=provider_name, model_cls=model_cls)

        return new_cls

    def _validate_aggregate_class(self, element_cls):
        # Import here to avoid cyclic dependency
        from protean.core.aggregate import BaseAggregate

        if not issubclass(element_cls, BaseAggregate):
            raise AssertionError(
                f'Element {element_cls.__name__} must be subclass of `BaseAggregate`')

        if element_cls.meta_.abstract is True:
            raise NotSupportedError(
                f'{element_cls.__name__} class has been marked abstract'
                f' and cannot be instantiated')

        return True

    def _validate_repository_class(self, element_cls):
        # Import here to avoid cyclic dependency
        from protean.core.repository.base import BaseRepository

        if not issubclass(element_cls, BaseRepository):
            raise AssertionError(
                f'Element {element_cls.__name__} must be subclass of `BaseRepository`')

        return True

    # _cls should never be specified by keyword, so start it with an
    # underscore.  The presence of _cls is used to detect if this
    # decorator is being called with parameters or not.
    def _domain_element(self, element_type, _cls=None, *, aggregate=None, bounded_context=None):
        """Returns the registered class after decoarating it and recording its presence in the domain"""

        def wrap(cls):
            return self._register_element(
                element_type, cls,
                aggregate=aggregate, bounded_context=bounded_context)

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

    def register(self, element_cls, **kwargs):
        """Register an element already subclassed with the correct Hierarchy"""
        element_types = [
            element_type
            for element_type, element_class in self.base_class_mapping.items()
            if element_class in element_cls.__mro__
        ]

        if len(element_types) == 0:
            raise NotImplementedError

        if (hasattr(element_cls, 'meta_') and
                hasattr(element_cls.meta_, 'abstract') and
                element_cls.meta_.abstract is True):
            raise NotSupportedError(f'{element_cls.__name__} class has been marked abstract'
                                    ' and cannot be instantiated')

        return self._register_element(DomainObjects[element_types.pop()], element_cls, **kwargs)

    def unregister(self, element_cls):
        """Unregister a Domain Element.

        This method will result in a no-op if the entity class was not found
        in the registry for whatever reason.
        """
        element_types = [
            element_type
            for element_type, element_class in self.base_class_mapping.items()
            if element_class in element_cls.__bases__
        ]

        if len(element_types) == 0:
            raise NotImplementedError

        self._domain_registry.unregister_element(DomainObjects[element_types.pop()], element_cls)

    def _derive_element_type(self, element_cls):
        element_types = [
            element_type
            for element_type, element_class in self.base_class_mapping.items()
            if element_class in element_cls.__bases__
        ]

        if len(element_types) == 0:
            raise NotImplementedError

        return DomainObjects[element_types.pop()]

    def _get_element_by_class(self, element_type, element_cls):
        """Fetch Domain record with Element class details"""
        element_qualname = fully_qualified_name(element_cls)
        if element_qualname in self._domain_registry._elements[element_type.value]:
            return self._domain_registry._elements[element_type.value][element_qualname]
        else:
            raise ObjectNotFoundError("Element {element_qualname} not registered in domain {self.domain_name}")

    def get_model(self, aggregate_cls):
        """Retrieve Model class connected to Entity"""
        aggregate_record = self._get_element_by_class(DomainObjects.AGGREGATE, aggregate_cls)

        # We should ask the Provider to give a fully baked model
        #   that has been initialized properly for this aggregate
        provider = self.get_provider(aggregate_record.provider_name)
        baked_model_cls = provider.get_model(aggregate_record.cls)

        return baked_model_cls

    def get_provider(self, provider_name):
        """Retrieve the provider object with a given provider name"""
        # FIXME Should domain be derived from "context"?
        return self.providers.get_provider(provider_name)

    def repository_for(self, aggregate_cls, uow=None):
        """Retrieve a Repository registered for the Aggregate"""
        repository_record = next(
            repository for _, repository in self.repositories.items()
            if type(repository.cls.meta_.aggregate) == type(aggregate_cls))  # FIXME Avoid comparing classes
        return repository_record.cls(self, uow)

    def get_dao(self, aggregate_cls):
        """Retrieve a DAO registered for the Aggregate with a live connection"""
        aggregate_record = self._get_element_by_class(DomainObjects.AGGREGATE, aggregate_cls)
        provider = self.get_provider(aggregate_record.provider_name)

        return provider.get_dao(aggregate_record.cls)
