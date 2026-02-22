import logging
from datetime import datetime
from typing import Any, TypeVar, cast

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ObjectNotFoundError,
)
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

                # Remove internal attributes not needed for the Fact Event
                payload.pop("_version", None)

                # Construct and raise the Fact Event
                fact_event_obj = aggregate._fact_event_cls(**payload)
                aggregate.raise_(fact_event_obj)

            uow._add_to_identity_map(aggregate)

            # If we started a UnitOfWork, commit it now
            if own_current_uow:
                own_current_uow.commit()

    def get(
        self,
        identifier: str,
        *,
        at_version: int | None = None,
        as_of: datetime | None = None,
    ) -> Any:
        """Retrieve a fully-formed Aggregate from a stream of Events.

        By default, returns the aggregate at its latest version. Pass
        ``at_version`` or ``as_of`` to perform a *temporal query* and
        reconstitute the aggregate at a historical point.

        Temporal aggregates are **read-only** — calling ``raise_()`` on them
        will raise ``IncorrectUsageError``.

        If the aggregate was already loaded in the current UnitOfWork,
        ``get`` will return the cached aggregate object (identity-map
        optimisation).  Temporal queries always bypass the identity map.

        Args:
            identifier: Aggregate identifier.
            at_version: Reconstitute to this exact version (0-indexed).
                Version 0 is the state after the first event.
            as_of: Reconstitute the aggregate as of this timestamp.
                Only events written on or before ``as_of`` are applied.

        Raises:
            IncorrectUsageError: When both ``at_version`` and ``as_of`` are
                provided (they are mutually exclusive).
            ObjectNotFoundError: When no stream with *identifier* is found,
                or the requested version/time predates all events.

        Returns:
            The fully-loaded aggregate object.
        """
        if at_version is not None and as_of is not None:
            raise IncorrectUsageError(
                "Cannot specify both `at_version` and `as_of`; "
                "they are mutually exclusive."
            )

        is_temporal = at_version is not None or as_of is not None

        # Temporal queries always bypass the identity map.
        if not is_temporal:
            if current_uow and identifier in current_uow._identity_map:
                return cast(BaseAggregate, current_uow._identity_map[identifier])

        aggregate = self._domain.event_store.store.load_aggregate(
            self.meta_.part_of,
            identifier,
            at_version=at_version,
            as_of=as_of,
        )

        if not aggregate:
            raise ObjectNotFoundError(
                f"`{self.meta_.part_of.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        aggregate._event_position = aggregate._version

        if is_temporal:
            aggregate._is_temporal = True

        return aggregate


_T = TypeVar("_T")


def event_sourced_repository_factory(
    element_cls: type[_T], domain: Any, **opts: Any
) -> type[_T]:
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
