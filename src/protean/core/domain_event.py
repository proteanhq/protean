# Protean
from protean.core.value_object import BaseValueObject


class BaseDomainEvent(BaseValueObject):
    """Base DomainEvent class that all other Domain Events should inherit from.

    Core functionality associated with Domain Events, like timestamping, are specified
    as part of the base DomainEvent class.
    """
    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainEvent:
            raise TypeError("BaseDomainEvent cannot be instantiated")
        return super().__new__(cls)
