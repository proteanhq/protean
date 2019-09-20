# Protean
# Standard Library Imports
import logging

from protean.domain import DomainObjects
from protean.utils.container import BaseContainer

logger = logging.getLogger('protean.event')


class BaseDomainEvent(BaseContainer):
    """Base DomainEvent class that all other Domain Events should inherit from.

    Core functionality associated with Domain Events, like timestamping, are specified
    as part of the base DomainEvent class.
    """

    element_type = DomainObjects.DOMAIN_EVENT

    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainEvent:
            raise TypeError("BaseDomainEvent cannot be instantiated")
        return super().__new__(cls)
