"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""
# Standard Library Imports
from dataclasses import dataclass, field
from typing import List

# Protean
from protean.core.entity import BaseEntity
from protean.utils.generic import singleton


@singleton
@dataclass
class _DomainRegistry:
    entities: List[BaseEntity] = field(default_factory=list)


# Singleton Registry, populated with the help of @<DomainElement> decorators
_domain_registry = _DomainRegistry()


def _process_entity(cls, aggregate, context):
    """Register class into the domain"""
    # Dynamically subclass from BaseEntity
    new_dict = cls.__dict__.copy()
    new_dict.pop('__dict__', None)  # Remove __dict__ to prevent recursion
    new_cls = type(cls.__name__, (BaseEntity, ), new_dict)

    # Enrich element with domain information
    new_cls.meta_.aggregate = aggregate
    new_cls.meta_.context = context

    # Register element with domain
    _domain_registry.entities.append(new_cls)

    return new_cls


# _cls should never be specified by keyword, so start it with an
# underscore.  The presence of _cls is used to detect if this
# decorator is being called with parameters or not.
def Entity(_cls=None, *, aggregate=None, context=None):
    """Returns the same class that was passed in,
    after recording its presence in the domain
    """

    def wrap(cls):
        return _process_entity(cls, aggregate, context)

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
        return _domain_registry

    def register_elements(self) -> None:
        from protean.core.repository import repo_factory
        for entity in _domain_registry.entities:
            repo_factory.register(entity)

    def register_element(self, element) -> None:
        from protean.core.repository import repo_factory
        repo_factory.register(element)

    def unregister_element(self, element) -> None:
        from protean.core.repository import repo_factory
        repo_factory.unregister(element)
