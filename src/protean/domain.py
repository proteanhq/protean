"""This module implements the central domain object, along with decorators
to register Domain Elements.
"""
from dataclasses import dataclass
from dataclasses import field
from typing import List

from protean.core.entity import Entity
from protean.utils.generic import singleton


@singleton
@dataclass
class _DomainRegistry:
    entities: List[Entity] = field(default_factory=list)


# Singleton Registry, populated with @DomainElement decorators
_domain_registry = _DomainRegistry()


def _process_class(cls, aggregate, context):
    """Register class into the domain"""
    # Enrich element with domain information
    cls.meta_.aggregate = aggregate
    cls.meta_.context = context

    # Register element with domain
    _domain_registry.entities.append(cls)

    return cls


# _cls should never be specified by keyword, so start it with an
# underscore.  The presence of _cls is used to detect if this
# decorator is being called with parameters or not.
def DomainElement(_cls=None, *, aggregate=None, context=None):
    """Returns the same class that was passed in,
    after recording its presence in the domain
    """

    def wrap(cls):
        return _process_class(cls, aggregate, context)

    # See if we're being called as @DomainElement or @DomainElement().
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
