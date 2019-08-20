# Protean
from protean.utils.container import BaseContainer


class BaseDomainEvent(BaseContainer):
    """Base DomainEvent class that all other Domain Events should inherit from.

    Core functionality associated with Domain Events, like timestamping, are specified
    as part of the base DomainEvent class.
    """
    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainEvent:
            raise TypeError("BaseDomainEvent cannot be instantiated")
        return super().__new__(cls)
