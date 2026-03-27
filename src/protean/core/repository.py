import logging
from functools import lru_cache
from typing import Any, TYPE_CHECKING, TypeVar

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import HasMany, HasOne
from protean.fields.tempdata import HasManyChanges, HasOneChanges
from protean.port.dao import BaseDAO
from protean.port.provider import BaseProvider
from protean.utils import (
    Database,
    DomainObjects,
    derive_element_class,
    fully_qualified_name,
)
from protean.utils.container import Element, OptionsMixin
from protean.utils.globals import current_uow
from protean.utils.query import Q
from protean.utils.reflection import association_fields, has_association_fields
from protean.utils.telemetry import set_span_error

if TYPE_CHECKING:
    from protean.core.queryset import QuerySet, ResultSet
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class BaseRepository(Element, OptionsMixin):
    """This is the baseclass for concrete Repository implementations.

    The three methods in this baseclass to `add`, `get` or `all` entities are sufficient in most cases
    to handle application requirements. They have built-in support for handling child relationships and
    honor Unit of Work constructs. While they can be overridden, it is generally suggested to call the
    parent method first before writing custom code.

    Repositories are strictly meant to be used in conjunction with Aggregate elements. It is always prudent to deal
    with persistence at the transaction boundary, which is at an Aggregate's level.

    **Design note: no delete/remove method.**
    Repositories intentionally do not support hard deletion. Domain state changes — cancellation,
    deactivation, archival — should be modeled as explicit state transitions via commands and events,
    not as record erasure. Hard deletion is available at the infrastructure level (``_dao.delete()``)
    for projection rebuilds, test teardown, and compliance requirements (e.g. GDPR right to erasure).
    """

    element_type = DomainObjects.REPOSITORY

    @classmethod
    def _default_options(cls):
        return [("database", "ALL"), ("part_of", None)]

    def __new__(cls, *args, **kwargs):
        # Prevent instantiation of `BaseRepository itself`
        if cls is BaseRepository:
            raise NotSupportedError("BaseRepository cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain: "Domain", provider: BaseProvider) -> None:
        self._domain = domain
        self._provider = provider

    @property
    @lru_cache()
    def _database_model(self):
        """Retrieve Database Model class connected to Entity"""
        # If a model was associated with the aggregate record, give it a higher priority
        #   and do not bake a new model class from aggregate/entity attributes
        custom_database_database_model_cls = None
        if fully_qualified_name(self.meta_.part_of) in self._domain._database_models:
            custom_database_database_model_cls = self._domain._database_models[
                fully_qualified_name(self.meta_.part_of)
            ]

        # FIXME This is the provide support for activating database specific models
        #   This needs to be enhanced to allow Protean to hold multiple database models per Aggregate/Entity
        #   per database.
        #
        #   If no database is specified, model can be used for all databases
        if custom_database_database_model_cls and (
            custom_database_database_model_cls.meta_.database is None
            or custom_database_database_model_cls.meta_.database
            == self._provider.__class__.__database__
        ):
            # Get the decorated model class.
            #   This is a no-op if the provider decides that the model is fully-baked
            database_model_cls = self._provider.decorate_database_model_class(
                self.meta_.part_of, custom_database_database_model_cls
            )
        else:
            # No model was associated with the aggregate/entity explicitly.
            #   So ask the Provider to bake a new model, initialized properly for this aggregate
            #   and return it
            database_model_cls = self._provider.construct_database_model_class(
                self.meta_.part_of
            )

        return database_model_cls

    @property
    @lru_cache()
    def _dao(self) -> BaseDAO:
        """Return the Data Access Object for this repository's aggregate.

        .. warning:: Internal / escape-hatch API

            ``_dao`` is used by the framework for child-entity synchronization,
            outbox persistence, projection rebuilds, and association resolution.

            Application code should use the public query helpers instead:

            - ``self.query`` – a :class:`QuerySet` for filtered, sorted,
              paginated queries.
            - ``self.find_by(**kwargs)`` – find a single aggregate by field
              values.
            - ``self.find(criteria)`` – find aggregates matching a ``Q``
              expression.
            - ``self.exists(criteria)`` – check if any aggregate matches.

            Direct ``_dao`` access is intentionally available as an escape
            hatch for infrastructure-level operations (hard deletion, test
            teardown, GDPR compliance) but should not be used for routine
            domain queries.
        """
        # Fixate on Model class at the domain level because an explicit model may have been registered
        return self._provider.get_dao(self.meta_.part_of, self._database_model)  # type: ignore[return-value]

    @property
    def query(self) -> "QuerySet":
        """Return a QuerySet for fluent filtering on the aggregate's data store.

        Use this inside custom repository methods instead of ``self._dao.query``::

            @domain.repository(part_of=Person)
            class PersonRepository:
                def adults(self):
                    return self.query.filter(age__gte=18).all().items
        """
        return self._dao.query

    def find_by(self, **kwargs: Any) -> Any:
        """Find a single aggregate matching the given criteria.

        Raises ``ObjectNotFoundError`` if no match is found.
        Raises ``TooManyObjectsError`` if multiple matches are found.

        Example::

            @domain.repository(part_of=Person)
            class PersonRepository:
                def find_by_email(self, email: str) -> Person:
                    return self.find_by(email=email)
        """
        item = self._dao.find_by(**kwargs)
        self._prewarm_associations(item)
        return item

    def find(self, criteria: Q) -> "ResultSet":
        """Find all aggregates matching a Q criteria expression.

        Returns a :class:`~protean.core.queryset.ResultSet` containing
        the matching aggregates. Accepts composable ``Q`` objects, making
        it easy to build reusable, domain-named query functions::

            from protean.utils.query import Q

            def overdue_orders() -> Q:
                return Q(status="pending", due_date__lt=datetime.now())

            results = repo.find(overdue_orders())
            results = repo.find(overdue_orders() & Q(total__gte=5000))
        """
        return self.query.filter(criteria).all()

    def exists(self, criteria: Q) -> bool:
        """Check if any aggregate matches the given Q criteria.

        Returns ``True`` when at least one aggregate satisfies the
        criteria, ``False`` otherwise.  Unlike ``find``, this method
        does not load aggregate objects -- it only checks for existence::

            if repo.exists(Q(email="john@example.com")):
                raise ValueError("Email already taken")
        """
        return self.query.filter(criteria).all().total > 0

    def add(self, item: Any) -> Any:  # noqa: C901
        """This method helps persist or update aggregates or projections into the persistence store.

        Returns the persisted item.

        Protean adopts a collection-oriented design pattern to handle persistence. What this means is that
        the Repository interface does not hint in any way that there is an underlying persistence mechanism,
        avoiding any notion of saving or persisting data in the design layer. The task of syncing the data
        back into the persistence store is handled automatically.

        To be specific, a Repository mimics a `set` collection. Whatever the implementation, the repository
        will not allow instances of the same object to be added twice. Also, when retrieving objects from
        a Repository and modifying them, you don't need to "re-save" them to the Repository.

        If there is a Unit of Work in progress, then the changes are performed on the
        UoW's active session. They are committed whenever the entire UoW is committed. If there is no
        transaction in progress, changes are committed immediately to the persistence store. This mechanism
        is part of the DAO's design, and is automatically used wherever one tries to persist data.
        """
        tracer = self._domain.tracer

        with tracer.start_as_current_span(
            "protean.repository.add",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("protean.aggregate.type", item.__class__.__name__)
            span.set_attribute("protean.provider", self._provider.name)

            try:
                return self._do_add(item)
            except Exception as exc:
                set_span_error(span, exc)
                raise

    def _do_add(self, item: Any) -> Any:  # noqa: C901
        """Internal add logic wrapped by the ``protean.repository.add`` span."""
        # `add` is typically invoked in handler methods in Command Handlers and Event Handlers, which are
        #   enclosed in a UoW automatically. Therefore, if there is a UoW in progress, we can assume
        #   that it is the active session. If not, we will start a new UoW and commit it after the operation
        #   is complete.
        own_current_uow = None
        if not (current_uow and current_uow.in_progress):
            own_current_uow = UnitOfWork()
            own_current_uow.start()

        # Persist the aggregate/projection FIRST so that it exists in the data
        # store before any child entities that hold a foreign-key reference to
        # it.  This is required for databases that enforce FK constraints
        # immediately (MSSQL, MySQL/InnoDB, SQLite with PRAGMA foreign_keys).
        if (not item.state_.is_persisted) or (
            item.state_.is_persisted and item.state_.is_changed
        ):
            self._dao.save(item)

            # If Aggregate has signed up Fact Events, raise them now
            if item.element_type == DomainObjects.AGGREGATE and item.meta_.fact_events:
                payload = item.to_dict()

                # Remove internal attributes from the payload, as they are not needed for the Fact Event
                payload.pop("state_", None)
                payload.pop("_version", None)

                # Construct and raise the Fact Event
                fact_event = item._fact_event_cls(**payload)
                item.raise_(fact_event)
        elif item.element_type == DomainObjects.AGGREGATE and item._events:
            # Aggregate has pending events but no own-field changes (e.g., events
            # raised by child entities).  We still need to persist the aggregate so
            # that _version is incremented, and track it in the identity map so that
            # _gather_events picks up these events on commit.
            self._dao.save(item)

        # Now sync child entities (HasMany/HasOne) — the parent row exists, so
        # child inserts referencing it will satisfy FK constraints.
        if has_association_fields(item):
            self._sync_children(item)

        # If we started a UnitOfWork, commit it now
        if own_current_uow:
            own_current_uow.commit()

        return item

    def _persist_child(self, child_cls: type, item: Any) -> None:
        """Persist a child entity through its repository's DAO.

        This is an internal helper used by ``_sync_children`` to keep the
        child-persistence plumbing in one place.  Application code should
        never need to call this directly.
        """
        self._domain.repository_for(child_cls)._dao.save(item)

    def _remove_child(self, child_cls: type, item: Any) -> None:
        """Delete a child entity through its repository's DAO.

        Internal counterpart to ``_persist_child`` for removals.
        """
        self._domain.repository_for(child_cls)._dao.delete(item)

    def _sync_children(self, entity):
        """Recursively sync child entities to the persistence store.

        Cache clearing is deferred until all DAO operations complete successfully.
        This ensures that if a mid-sync failure triggers a DB rollback, the in-memory
        temp_cache remains consistent and a retry of ``repo.add()`` will re-attempt
        all child operations.
        """
        # If there are HasMany fields in the aggregate, sync child objects added/removed,
        #   but not yet persisted to the database.
        #
        # The details of in-transit child objects are maintained as part of the `has_many_field` itself
        #   in a variable called `_temp_cache`

        # Collect cache clear operations to execute after all DAO operations succeed
        cache_clears: list[tuple] = []

        for field_name, field in association_fields(entity).items():
            if isinstance(field, HasMany):
                cache = entity._temp_cache.get(field_name)
                if cache is None:
                    cache = HasManyChanges()

                # First, handle direct updates to underlying child objects
                #   These are ones whose attributes have been changed directly
                #   instead of being routed via `add`/`remove`
                for item in getattr(entity, field_name):
                    if item.state_.is_changed:
                        # If the item was changed directly AND added via `add`, then
                        #   we give preference to the object in the cache
                        if item not in cache.updated:
                            self._persist_child(field.to_cls, item)

                for _, item in cache.removed.items():
                    self._remove_child(field.to_cls, item)

                for _, item in cache.updated.items():
                    self._persist_child(field.to_cls, item)

                for _, item in cache.added.items():
                    item.state_.mark_new()
                    self._persist_child(field.to_cls, item)

                # Defer cache clearing until all DAO operations succeed
                cache_clears.append((entity, field_name))

            if isinstance(field, HasOne):
                cache = entity._temp_cache.get(field_name)
                if cache is None:
                    cache = HasOneChanges()

                # First, handle direct updates to underlying child objects
                #   These are ones whose attributes have been changed directly
                #   instead of being routed via `add`/`remove`
                item = getattr(entity, field_name)
                if item is not None and item.state_.is_changed:
                    self._persist_child(field.to_cls, item)
                # Or a new instance has been assigned
                elif cache.change:
                    if cache.change == "ADDED":
                        self._persist_child(field.to_cls, item)
                    elif cache.change == "UPDATED":
                        if cache.old_value is not None:
                            # The object was replaced, so delete the old record
                            self._remove_child(field.to_cls, cache.old_value)
                        else:
                            # The same object was updated.
                            # Explicitly mark changed: the entity's is_changed flag may
                            # have been cleared (e.g. by a prior save) even though
                            # HasOne.__set__ recorded the mutation in _temp_cache.
                            item.state_.mark_changed()

                        self._persist_child(field.to_cls, item)
                    elif cache.change == "DELETED":
                        self._remove_child(field.to_cls, cache.old_value)

                    # Defer cache clearing until all DAO operations succeed
                    cache_clears.append((entity, field_name))

            ### RECURSIVE SYNC ###
            # Recurse AFTER persisting children at this level so that the child
            # row exists before any grandchild insert that holds an FK to it.
            # This gives top-down insert ordering: parent → child → grandchild.
            if has_association_fields(field.to_cls):
                if isinstance(field, HasMany):
                    for item in getattr(entity, field_name):
                        self._sync_children(item)
                elif isinstance(field, HasOne):
                    if getattr(entity, field_name):
                        self._sync_children(getattr(entity, field_name))

        # Clear all caches atomically after all DAO operations completed successfully
        for ent, fname in cache_clears:
            cache = ent._temp_cache.get(fname)
            if cache is not None:
                cache.clear()

    def _prewarm_associations(self, aggregate: Any) -> None:
        """Eagerly load all association fields into the field cache.

        In DDD, loading an aggregate should return the complete aggregate
        boundary.  This method triggers the descriptor ``__get__`` on each
        HasMany / HasOne field, which fetches child entities from the data
        store and caches them so that subsequent access does not incur an
        additional database round-trip.
        """
        if not has_association_fields(aggregate):
            return
        for field_name in association_fields(aggregate):
            getattr(aggregate, field_name)

    def get(self, identifier) -> Any:
        """This is a utility method to fetch data from the persistence store by its key identifier. All child objects,
        including enclosed entities, are returned as part of this call.

        Returns the fetched object.

        All other data filtering capabilities can be implemented by using the underlying DAO's
        ``BaseDAO.filter`` method.

        Filter methods are typically implemented as domain-contextual queries, like `find_adults()`,
        `find_residents_of_area(zipcode)`, etc. It is also possible to make use of more complicated,
        domain-friendly design patterns like the `Specification` pattern.
        """
        tracer = self._domain.tracer

        with tracer.start_as_current_span(
            "protean.repository.get",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("protean.aggregate.type", self.meta_.part_of.__name__)
            span.set_attribute("protean.provider", self._provider.name)

            try:
                item = self._dao.get(identifier)
                self._prewarm_associations(item)
                return item
            except Exception as exc:
                set_span_error(span, exc)
                raise


_T = TypeVar("_T")


def repository_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    from protean.core.aggregate import BaseAggregate

    # Pop internal flag before passing opts to derive_element_class,
    # which validates that all options are known element options.
    auto_constructed = opts.pop("_auto_constructed", False)

    element_cls = derive_element_class(element_cls, BaseRepository, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` should be associated with an Aggregate"
        )

    # Enforce that user-defined repositories can only be associated with Aggregates.
    # Auto-constructed repositories (for child entities, projections) are created
    # internally and bypass this check.
    if not auto_constructed and not issubclass(
        element_cls.meta_.part_of, BaseAggregate
    ):
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` can only be associated with an Aggregate"
        )

    # Ensure the value of `database` is among known databases
    if element_cls.meta_.database != "ALL" and element_cls.meta_.database not in [
        database.value for database in Database
    ]:
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` should be associated with a valid Database"
        )

    return element_cls
