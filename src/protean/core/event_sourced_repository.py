import logging

from protean import BaseEventSourcedAggregate
from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from protean.fields import Identifier
from protean.globals import current_domain, current_uow
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.event_sourced_repository")


class BaseEventSourcedRepository(Element, OptionsMixin):
    element_type = DomainObjects.EVENT_SOURCED_REPOSITORY

    @classmethod
    def _default_options(cls):
        return [("aggregate_cls", None)]

    def __new__(cls, *args, **kwargs):
        # Prevent instantiation of `BaseEventSourcedRepository itself`
        if cls is BaseEventSourcedRepository:
            raise TypeError("BaseEventSourcedRepository cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain: "Domain") -> None:
        self._domain = domain

    def add(self, aggregate: BaseEventSourcedAggregate):
        current_uow._seen.add(aggregate)

    def get(self, identifier: Identifier):
        aggregate = current_domain.event_store.store.load_aggregate(
            self.meta_.aggregate_cls, identifier
        )

        if not aggregate:
            raise ObjectNotFoundError(
                {
                    "_entity": f"`{self.meta_.aggregate_cls.__name__}` object with identifier {identifier} "
                    f"does not exist."
                }
            )

        return aggregate


def event_sourced_repository_factory(element_cls, **opts):
    element_cls = derive_element_class(element_cls, BaseEventSourcedRepository, **opts)

    if not element_cls.meta_.aggregate_cls:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Repository `{element_cls.__name__}` should be associated with an Aggregate"
                ]
            }
        )

    if not issubclass(element_cls.meta_.aggregate_cls, BaseEventSourcedAggregate):
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Repository `{element_cls.__name__}` can only be associated with an Aggregate"
                ]
            }
        )

    return element_cls
