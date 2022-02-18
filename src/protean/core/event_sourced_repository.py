import logging

from protean import BaseEventSourcedAggregate
from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from protean.fields import Identifier
from protean.globals import current_domain, current_uow
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


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

    def __init__(self, domain) -> None:
        self._domain = domain

    def add(self, aggregate: BaseEventSourcedAggregate) -> None:
        current_uow._seen.add(aggregate)

    def get(self, identifier: Identifier) -> BaseEventSourcedAggregate:
        """Retrieve a fully-formed Aggregate from a stream of Events.

        Args:
            identifier (Identifier): Aggregate identifier

        Raises:
            ObjectNotFoundError: When no stream with identifier is found

        Returns:
            BaseEventSourcedAggregate: The fully-loaded aggregate object
        """
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
