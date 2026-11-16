import logging
from collections.abc import Iterator, Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeVar, cast

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.domain.context import has_domain_context
from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ObjectNotFoundError,
)
from protean.fields import HasMany, HasOne
from protean.fields.tempdata import HasManyChanges, HasOneChanges
from protean.port.dao import BaseDAO
from protean.port.database import BaseDatabase, DatabaseModelPort
from protean.utils import (
    DomainObjects,
    _derive_element_class,
    _fully_qualified_name,
)
from protean.utils.container import Element, OptionsMixin
from protean.utils.globals import current_uow, g
from protean.utils.query import Q
from protean.utils.reflection import association_fields, has_association_fields
from protean.utils.telemetry import set_span_error

if TYPE_CHECKING:
    from protean.core.queryset import QuerySet, ResultSet
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class BaseRepository(Element, OptionsMixin):
    """Base class for repositories, which load and persist aggregates.

    ``add()``, ``get()`` and ``get_or_none()`` persist and load an aggregate
    together with its child entities, and take part in the active Unit of
    Work. A custom repository adds domain-named query methods built on
    ``query``, ``find()``, ``find_by()`` and ``exists()``. A method that
    overrides ``add()`` or ``get()`` should call the parent method first.

    A user-defined repository can only be ``part_of`` an aggregate.
    Repositories have no delete or remove method; see the Repositories concept
    page for the reason.
    """

    element_type = DomainObjects.REPOSITORY

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("database_type", "ALL"),
        ("part_of", None),
        ("suppress_checks", ()),
    ]

    _renamed_options: ClassVar[Mapping[str, str]] = {"database": "database_type"}

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        # Prevent instantiation of `BaseRepository itself`
        if cls is BaseRepository:
            raise NotSupportedError("BaseRepository cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain: "Domain", provider: BaseDatabase) -> None:
        self._domain = domain
        self._provider = provider

    @property
    @lru_cache
    def _database_model(self) -> type[DatabaseModelPort]:
        """Retrieve Database Model class connected to Entity"""
        # Look up custom models registered for this entity, keyed by database type.
        # Prefer a model targeting this provider's database type; fall back to a
        # generic model (database_type=None) if no type-specific one exists.
        entity_models = self._domain._database_models.get(
            _fully_qualified_name(self.meta_.part_of), {}
        )
        database_type = self._provider.database_type
        custom_model_cls = entity_models.get(database_type) or entity_models.get(None)

        # The provider decorates a custom model, or builds one when there is none.
        return self._provider.model_for(self.meta_.part_of, custom_model_cls)

    @property
    @lru_cache
    def _dao(self) -> BaseDAO:
        """Return the Data Access Object for this repository's aggregate.

        Internal. Application code should use ``query``, ``find_by()``,
        ``find()`` and ``exists()``. Direct use is for infrastructure work such
        as hard deletion and test teardown.
        """
        # Fixate on Model class at the domain level because an explicit model may have been registered
        dao: BaseDAO = self._provider.dao_for(self.meta_.part_of, self._database_model)
        return dao

    def _delete_in_batches(self, criteria: Q, batch_size: int) -> int:
        """Delete all rows matching ``criteria`` in bounded batches of ``batch_size``.

        Loops `BaseDAO._delete_top` until a batch deletes fewer than
        ``batch_size`` rows (the matched set is drained), returning the total
        deleted. When called outside a Unit of Work each batch commits before
        the next begins, so a large backlog is cleared without one long-held
        lock or an oversized transaction. Shared by the outbox and consume-side
        idempotency cleanup paths.
        """
        # Guard the loop invariant: ``_delete_top(limit<=0)`` returns 0, and
        # ``0 < batch_size`` is False for a non-positive batch_size, so the loop
        # would never terminate. A user-facing ``--batch-size`` reaches here.
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        total = 0
        while True:
            deleted = self._dao._delete_top(criteria, limit=batch_size)
            total += deleted
            if deleted < batch_size:
                break
        return total

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

        Returns a `ResultSet` containing
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
        criteria, ``False`` otherwise. It runs the same query as ``find``
        and checks how many rows came back, so it reads the matching
        aggregates rather than asking the database for existence alone::

            if repo.exists(Q(email="john@example.com")):
                raise ValueError("Email already taken")
        """
        return self.query.filter(criteria).all().total > 0

    def add(self, item: Any) -> Any:
        """Persist a new or changed aggregate or projection, with its child entities.

        Inside an active Unit of Work, the changes are written in its
        transaction and committed when it commits. Otherwise they are committed
        before ``add()`` returns.

        Returns:
            The item passed in.
        """
        # Increment access log repo save counter
        if has_domain_context():
            g._access_log_repo_saves = getattr(g, "_access_log_repo_saves", 0) + 1

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
            except Exception as exc:  # marks the span as failed, then re-raises
                set_span_error(span, exc)
                raise

    def _do_add(self, item: Any) -> Any:
        """Internal add logic wrapped by the ``protean.repository.add`` span."""
        # `add` is typically invoked in handler methods in Command Handlers and Event Handlers, which are
        #   enclosed in a UoW automatically. Therefore, if there is a UoW in progress, we can assume
        #   that it is the active session. If not, we will start a new UoW and commit it after the operation
        #   is complete.
        own_current_uow = None
        if not (current_uow and current_uow.in_progress):
            own_current_uow = UnitOfWork()
            own_current_uow.start()

        try:
            # Persist the aggregate/projection FIRST so that it exists in the data
            # store before any child entities that hold a foreign-key reference to
            # it.  This is required for databases that enforce FK constraints
            # immediately (MSSQL, MySQL/InnoDB, SQLite with PRAGMA foreign_keys).
            root_persisted = _save_root(self, item)

            # Now sync child entities (HasMany/HasOne) — the parent row exists, so
            # child inserts referencing it will satisfy FK constraints.
            if has_association_fields(item):
                # Under an active UoW the save above is only buffered (no flush),
                # so force the root row to materialize in the transaction before
                # child inserts. Without FK metadata on the generated models, the
                # ORM cannot order parent-before-child at commit-time flush itself.
                if root_persisted:
                    self._dao._flush()
                self._sync_children(item)

            # If we started a UnitOfWork, commit it now
            if own_current_uow:
                own_current_uow.commit()
        except Exception:
            # A save/flush here can raise (e.g. ``ExpectedVersionError`` on a
            # concurrent conflict, now reachable for child-only changes). If we
            # started the UnitOfWork, roll it back so a standalone ``add`` does
            # not leave a dangling in-progress UoW (and, on SQLAlchemy, a session
            # needing rollback) for the next operation. A caller-supplied UoW is
            # left for the caller's own ``with`` block to unwind.
            if own_current_uow and own_current_uow.in_progress:
                own_current_uow.rollback()
            raise

        return item

    def _persist_child(self, child_cls: type[Any], item: Any) -> None:
        """Persist a child entity through its repository's DAO.

        This is an internal helper used by ``_sync_children`` to keep the
        child-persistence plumbing in one place.  Application code should
        never need to call this directly.
        """
        self._domain.repository_for(child_cls)._dao.save(item)

    def _remove_child(self, child_cls: type[Any], item: Any) -> None:
        """Delete a child entity through its repository's DAO.

        Internal counterpart to ``_persist_child`` for removals.
        """
        self._domain.repository_for(child_cls)._dao.delete(item)

    def _has_changed_child(self, entity: Any) -> bool:
        """Return ``True`` if a descendant entity has been directly changed.

        The aggregate root is the optimistic-concurrency boundary, so a change
        confined to a child (at any depth) with no change to a root field must
        still re-save the root to advance its ``_version``. This mirrors the
        direct-update detection in `_sync_children`: a child whose own
        attribute was edited carries ``state_.is_changed``, and the recursion
        walks nested children the same way ``_sync_children`` does. Structural
        ``add_``/``remove_`` changes to a collection are excluded for two distinct
        reasons: a freshly *added* child is new, so ``mark_changed`` no-ops and its
        ``is_changed`` stays ``False``; a *removed* child is no longer in the
        collection this walks (it lives in the association's temp cache until the
        sync). Those are handled separately and do not race the way concurrent
        edits of the same existing data do.
        """
        return any(
            child.state_.is_changed or self._has_changed_child(child)
            for child in _direct_children(entity)
        )

    def _sync_children(self, entity: Any) -> None:
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
        cache_clears: list[tuple[Any, str]] = []

        for field_name, field in association_fields(entity).items():
            if isinstance(field, HasMany):
                _sync_has_many(self, entity, field_name, field)
                # Defer cache clearing until all DAO operations succeed
                cache_clears.append((entity, field_name))
                _sync_grandchildren(self, entity, field_name, field)
            elif isinstance(field, HasOne):
                if _sync_has_one(self, entity, field_name, field):
                    # Defer cache clearing until all DAO operations succeed
                    cache_clears.append((entity, field_name))
                _sync_grandchildren(self, entity, field_name, field)

        # Clear all caches atomically after all DAO operations completed successfully
        _clear_caches(cache_clears)

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

    def get(self, identifier: Any) -> Any:
        """This is a utility method to fetch data from the persistence store by its key identifier. All child objects,
        including enclosed entities, are returned as part of this call.

        Returns the fetched object.

        All other data filtering capabilities can be implemented by using the underlying DAO's
        ``BaseDAO.filter`` method.

        Filter methods are typically implemented as domain-contextual queries, like `find_adults()`,
        `find_residents_of_area(zipcode)`, etc. It is also possible to make use of more complicated,
        domain-friendly design patterns like the `Specification` pattern.
        """
        # Increment access log repo load counter
        if has_domain_context():
            g._access_log_repo_loads = getattr(g, "_access_log_repo_loads", 0) + 1

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
            except Exception as exc:  # marks the span as failed, then re-raises
                set_span_error(span, exc)
                raise

    def get_or_none(self, identifier: Any) -> Any | None:
        """Fetch data from the persistence store by its key identifier, same as `get()`,
        but return `None` instead of raising `ObjectNotFoundError` when nothing matches.

        On a hit, the returned object has all child objects, including enclosed entities,
        pre-warmed exactly as `get()` does. On a miss, this method returns `None` and never
        raises `ObjectNotFoundError`. Any other error (for example `TooManyObjectsError`, or
        a provider/connection error) still propagates.

        Use `get()` instead when a missing identifier should be treated as a hard failure.
        """
        # Increment access log repo load counter
        if has_domain_context():
            g._access_log_repo_loads = getattr(g, "_access_log_repo_loads", 0) + 1

        tracer = self._domain.tracer

        with tracer.start_as_current_span(
            "protean.repository.get_or_none",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            span.set_attribute("protean.aggregate.type", self.meta_.part_of.__name__)
            span.set_attribute("protean.provider", self._provider.name)

            try:
                item = self._dao.get(identifier)
                self._prewarm_associations(item)
                return item
            except ObjectNotFoundError:
                return None
            except Exception as exc:  # marks the span as failed, then re-raises
                set_span_error(span, exc)
                raise


def _save_root(repo: BaseRepository, item: Any) -> bool:
    """Save ``item`` itself when it needs a write, and return whether it was saved.

    A new item, or one whose own fields or child entities changed, is saved
    and raises its fact event. An aggregate with only pending events is saved
    too, without a fact event.
    """
    if (not item.state_.is_persisted) or (
        item.state_.is_persisted
        and (item.state_.is_changed or repo._has_changed_child(item))
    ):
        repo._dao.save(item)
        _raise_fact_event(item)
        return True

    if item.element_type == DomainObjects.AGGREGATE and item._events:
        # Aggregate has pending events but no own-field changes (e.g., events
        # raised by child entities).  We still need to persist the aggregate so
        # that _version is incremented, and track it in the identity map so that
        # _gather_events picks up these events on commit.
        repo._dao.save(item)
        return True

    return False


def _raise_fact_event(item: Any) -> None:
    """Raise the fact event of ``item`` when it is an aggregate that signed up for one."""
    if not (item.element_type == DomainObjects.AGGREGATE and item.meta_.fact_events):
        return

    payload = item.to_dict()

    # Remove internal attributes from the payload, as they are not needed for the Fact Event
    payload.pop("state_", None)
    payload.pop("_version", None)

    # Construct and raise the Fact Event
    fact_event = item._fact_event_cls(**payload)
    item.raise_(fact_event)


def _direct_children(entity: Any) -> Iterator[Any]:
    """Yield the child entities of ``entity`` one level down, field by field.

    An unset ``HasOne`` yields nothing.
    """
    for field_name, field in association_fields(entity).items():
        if isinstance(field, HasMany):
            yield from getattr(entity, field_name)
        elif isinstance(field, HasOne):
            child = getattr(entity, field_name)
            if child is not None:
                yield child


def _sync_has_many(
    repo: BaseRepository, entity: Any, field_name: str, field: HasMany
) -> None:
    """Write the direct updates, removals, updates and additions of one ``HasMany``."""
    # Associations resolve ``to_cls`` to a class when the domain initializes.
    child_cls = cast("type[Any]", field.to_cls)
    cache = entity._temp_cache.get(field_name)
    if cache is None:
        cache = HasManyChanges()

    # First, handle direct updates to underlying child objects
    #   These are ones whose attributes have been changed directly
    #   instead of being routed via `add`/`remove`
    for item in getattr(entity, field_name):
        # If the item was changed directly AND added via `add`, then
        #   we give preference to the object in the cache
        if item.state_.is_changed and item not in cache.updated:
            repo._persist_child(child_cls, item)

    for item in cache.removed.values():
        repo._remove_child(child_cls, item)

    for item in cache.updated.values():
        repo._persist_child(child_cls, item)

    for item in cache.added.values():
        item.state_.mark_new()
        repo._persist_child(child_cls, item)


def _sync_has_one(
    repo: BaseRepository, entity: Any, field_name: str, field: HasOne
) -> bool:
    """Write the change of one ``HasOne``, and return whether its cache needs clearing.

    The cache needs clearing only when it recorded an assignment.
    """
    # Associations resolve ``to_cls`` to a class when the domain initializes.
    child_cls = cast("type[Any]", field.to_cls)
    cache = entity._temp_cache.get(field_name)
    if cache is None:
        cache = HasOneChanges()

    # First, handle direct updates to underlying child objects
    #   These are ones whose attributes have been changed directly
    #   instead of being routed via `add`/`remove`
    item = getattr(entity, field_name)
    if item is not None and item.state_.is_changed:
        repo._persist_child(child_cls, item)
        return False

    # Or a new instance has been assigned
    if not cache.change:
        return False

    _sync_has_one_change(repo, child_cls, item, cache)
    return True


def _sync_has_one_change(
    repo: BaseRepository, child_cls: type[Any], item: Any, cache: HasOneChanges
) -> None:
    """Write the assignment a ``HasOne`` cache recorded: an add, an update or a delete."""
    if cache.change == "ADDED":
        repo._persist_child(child_cls, item)
    elif cache.change == "UPDATED":
        if cache.old_value is not None:
            # The object was replaced, so delete the old record
            repo._remove_child(child_cls, cache.old_value)
        else:
            # The same object was updated.
            # Explicitly mark changed: the entity's is_changed flag may
            # have been cleared (e.g. by a prior save) even though
            # HasOne.__set__ recorded the mutation in _temp_cache.
            item.state_.mark_changed()

        repo._persist_child(child_cls, item)
    elif cache.change == "DELETED":
        repo._remove_child(child_cls, cache.old_value)


def _sync_grandchildren(
    repo: BaseRepository, entity: Any, field_name: str, field: HasMany | HasOne
) -> None:
    """Flush, then sync the children of each child in one association field.

    Does nothing when the child class has no association fields.
    """
    # Recurse AFTER persisting children at this level so that the child
    # row exists before any grandchild insert that holds an FK to it.
    # This gives top-down insert ordering: parent → child → grandchild.
    if not has_association_fields(cast("type[Any]", field.to_cls)):
        return

    # Flush this level's child inserts so their rows exist in the
    # transaction before grandchild inserts reference them.
    repo._dao._flush()
    if isinstance(field, HasMany):
        for item in getattr(entity, field_name):
            repo._sync_children(item)
    elif getattr(entity, field_name):
        repo._sync_children(getattr(entity, field_name))


def _clear_caches(cache_clears: list[tuple[Any, str]]) -> None:
    """Clear the association temp cache of each ``(entity, field_name)`` pair."""
    for ent, fname in cache_clears:
        cache = ent._temp_cache.get(fname)
        if cache is not None:
            cache.clear()


_T = TypeVar("_T")


def repository_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    # Pop internal flag before passing opts to _derive_element_class,
    # which validates that all options are known element options.
    auto_constructed = opts.pop("_auto_constructed", False)

    element_cls = _derive_element_class(element_cls, BaseRepository, **opts)

    # The derived class is always a ``BaseRepository`` subclass at runtime;
    # narrow the unbound ``type[_T]`` typevar so the injected ``meta_``
    # class attribute is visible to both type checkers.
    repository_cls = cast("type[BaseRepository]", element_cls)

    if not repository_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Repository `{repository_cls.__name__}` should be associated with an Aggregate"
        )

    # Enforce that user-defined repositories can only be associated with Aggregates.
    # Auto-constructed repositories (for child entities, projections) are created
    # internally and bypass this check. When ``part_of`` is a string reference,
    # the check is deferred: the ElementResolver only resolves it against
    # registered aggregates, so a non-aggregate target surfaces as an
    # unresolved reference during validation.
    if (
        not auto_constructed
        and not isinstance(repository_cls.meta_.part_of, str)
        and not (
            isinstance(repository_cls.meta_.part_of, type)
            and issubclass(repository_cls.meta_.part_of, BaseAggregate)
        )
    ):
        raise IncorrectUsageError(
            f"Repository `{repository_cls.__name__}` can only be associated with an Aggregate"
        )

    return element_cls
