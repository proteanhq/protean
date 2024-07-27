import logging

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ObjectNotFoundError,
)
from protean.fields import Identifier
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.globals import current_uow

logger = logging.getLogger(__name__)


class BaseEventSourcedRepository(Element, OptionsMixin):
    element_type = DomainObjects.EVENT_SOURCED_REPOSITORY

    @classmethod
    def _default_options(cls):
        return [("part_of", None)]

    def __new__(cls, *args, **kwargs):
        # Prevent instantiation of `BaseEventSourcedRepository itself`
        if cls is BaseEventSourcedRepository:
            raise NotSupportedError("BaseEventSourcedRepository cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain) -> None:
        self._domain = domain

    def add(self, aggregate: BaseAggregate) -> None:
        if aggregate is None:
            raise IncorrectUsageError("Aggregate object to persist is invalid")

        # Proceed only if aggregate has events
        if len(aggregate._events) > 0:
            # `add` is typically invoked in handler methods in Command Handlers and Event Handlers, which are
            #   enclosed in a UoW automatically. Therefore, if there is a UoW in progress, we can assume
            #   that it is the active session. If not, we will start a new UoW and commit it after the operation
            #   is complete.
            own_current_uow = None
            if not (current_uow and current_uow.in_progress):
                own_current_uow = UnitOfWork()
                own_current_uow.start()

            uow = current_uow or own_current_uow

            # If Aggregate has signed up Fact Events, raise them now
            if aggregate.meta_.fact_events:
                payload = aggregate.to_dict()

                # Construct and raise the Fact Event
                fact_event_obj = aggregate._fact_event_cls(**payload)
                aggregate.raise_(fact_event_obj)

            uow._add_to_identity_map(aggregate)

            # If we started a UnitOfWork, commit it now
            if own_current_uow:
                own_current_uow.commit()

    def get(self, identifier: Identifier) -> BaseAggregate:
        """Retrieve a fully-formed Aggregate from a stream of Events.

        If the aggregate was already loaded in the current UnitOfWork,
        `get` will return the aggregate object instead of loading it again
        from events.

        Args:
            identifier (Identifier): Aggregate identifier

        Raises:
            ObjectNotFoundError: When no stream with identifier is found

        Returns:
            BaseEventSourcedAggregate: The fully-loaded aggregate object
        """
        # Return aggregate if it was already loaded and is present in current
        #   UnitOfWork's identity map.
        if current_uow and identifier in current_uow._identity_map:
            return current_uow._identity_map[identifier]

        aggregate = self._domain.event_store.store.load_aggregate(
            self.meta_.part_of, identifier
        )

        if not aggregate:
            raise ObjectNotFoundError(
                f"`{self.meta_.part_of.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        aggregate._event_position = aggregate._version

        return aggregate


def event_sourced_repository_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEventSourcedRepository, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` should be associated with an Aggregate"
        )

    if not element_cls.meta_.part_of.meta_.is_event_sourced:
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` can only be associated with an Event Sourced Aggregate"
        )

    return element_cls
