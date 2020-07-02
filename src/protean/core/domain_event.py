# Protean
# Standard Library Imports
import logging

from protean.core.exceptions import IncorrectUsageError
from protean.domain import DomainObjects
from protean.utils.container import BaseContainer

logger = logging.getLogger("protean.event")


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


class DomainEventFactory:
    @classmethod
    def prep_class(cls, element_cls, **kwargs):
        if issubclass(element_cls, BaseDomainEvent):
            new_element_cls = element_cls
        else:
            try:
                new_dict = element_cls.__dict__.copy()
                new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

                new_element_cls = type(
                    element_cls.__name__, (BaseDomainEvent,), new_dict
                )
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

        if hasattr(new_element_cls, "meta_"):
            if not (
                hasattr(new_element_cls.meta_, "aggregate_cls")
                and new_element_cls.meta_.aggregate_cls
            ):
                new_element_cls.meta_.aggregate_cls = kwargs.pop("aggregate_cls", None)

            new_element_cls.meta_.bounded_context = kwargs.pop("bounded_context", None)

        if not new_element_cls.meta_.aggregate_cls:
            raise IncorrectUsageError(
                "Domain Events need to be associated with an Aggregate"
            )

        return new_element_cls
