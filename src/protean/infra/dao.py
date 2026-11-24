"""The `DAO` service.

A database adapter implements `DAOPort`: it reads and writes one entity
class's rows in the session it is given. `DAO` wraps one adapter for one
entity class and builds the entity-level operations on top of it: getting,
finding, creating, saving, updating and deleting entities, checking unique
fields and versions, running pre-persist hooks, tracking aggregates in the
Unit of Work, claiming rows and deleting them in batches. The write path
lives in `protean.infra.dao_write` and the read path in
`protean.infra.dao_read`; the service's methods delegate to them.

`DAO.session_scope` picks the session for each operation. Inside a Unit of
Work it is the Unit of Work's session for the provider, and the Unit of Work
ends it. Outside one, or after `outside_uow()`, it is a new session from the
provider, which the service commits, rolls back on an error, and closes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from protean._deprecation import deprecated_from_registry
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.queryset import QuerySet, ResultSet
from protean.exceptions import ConfigurationError
from protean.infra import dao_read, dao_write
from protean.port.dao import (
    _FLAG_PORTS,
    BoundedDeletePort,
    ClaimCandidatesPort,
    DAOPort,
    HoldBack,
    NativeClaimPort,
)
from protean.port.database import DatabaseCapabilities, DatabaseModelPort
from protean.utils import DomainObjects
from protean.utils.globals import current_domain, current_uow
from protean.utils.query import Q
from protean.utils.reflection import id_field

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.database import SessionProtocol

# Max identifiers per ``IN (...)`` clause in :func:`portable_delete_top`. Kept under SQLite's default ``SQLITE_MAX_VARIABLE_NUMBER`` of 999 so
# the fallback path is safe on every backend regardless of batch size.
_DELETE_IN_CHUNK_SIZE = 900


def _uses_adapter_operation(dao: DAO, flag: DatabaseCapabilities) -> bool:
    """Whether ``dao``'s provider declares ``flag``, so the adapter's own
    operation runs instead of the portable one.

    Building the service already checked that the adapter subclasses the port
    that goes with each declared flag.
    """
    return flag in dao.provider.capabilities


def _check_flag_ports(provider: Any, adapter: DAOPort) -> None:
    """Check that ``adapter``'s class subclasses the port of each flag in
    ``_FLAG_PORTS`` that ``provider`` declares.

    The check runs one way: an adapter may implement a port whose flag its
    provider does not declare.

    Raises:
        ConfigurationError: The provider declares a flag and the DAO class
            does not subclass the port that goes with it.
    """
    capabilities = provider.capabilities
    for flag, port in _FLAG_PORTS.items():
        # The ports are not ``runtime_checkable``, so check the MRO.
        if flag in capabilities and port not in type(adapter).__mro__:
            raise ConfigurationError(
                f"Provider `{provider.name}` declares `{flag.name}`, but DAO "
                f"class `{type(adapter).__name__}` does not subclass "
                f"`{port.__name__}`"
            )


def _order_keys(order_by: str | Sequence[str] | None) -> tuple[str, ...]:
    """Normalize an ``order_by`` argument to a tuple of keys.

    A bare string is one key, not a sequence of one-character keys.
    """
    if not order_by:
        return ()
    if isinstance(order_by, str):
        return (order_by,)
    return tuple(order_by)


def _lookup(key: str, value: Any) -> Q:
    """``Q`` for one lookup whose key is only known at run time."""
    kwargs: dict[str, Any] = {key: value}
    return Q(**kwargs)


def _earlier_than(entity: Any, order: Sequence[str]) -> Q:
    """``Q`` matching rows that sort before ``entity`` on the ascending
    ``order`` keys, with NULL last.

    Built from ``entity``'s values so that every adapter can run it. A NULL
    never matches ``<``, so a row with NULL in a key is never "before" a row
    with a value there, which is what NULL-last means.
    """
    earlier = Q()
    equal_so_far = Q()
    for key in order:
        value = getattr(entity, key)
        if value is None:
            before = _lookup(f"{key}__isnull", False)
            same = _lookup(f"{key}__isnull", True)
        else:
            before = _lookup(f"{key}__lt", value)
            same = _lookup(key, value)
        earlier = earlier | (equal_so_far & before)
        equal_so_far = equal_so_far & same
    return earlier


def _try_claim(
    dao: DAO,
    id_name: str,
    criteria: Q,
    claim_fields: dict[str, Any],
    entity: Any,
) -> bool:
    """Claim one candidate row, and on success apply ``claim_fields`` to it.

    On an aggregate, the claim also advances the row's ``_version`` by one,
    and ``entity`` then carries the new version.
    """
    # Re-assert the eligibility criteria in the update so a row claimed
    # by another worker between the read and this write is skipped.
    guard = Q(**{id_name: getattr(entity, id_name)}) & criteria
    values = claim_fields
    versioned = dao.entity_cls.element_type == DomainObjects.AGGREGATE
    if versioned:
        guard &= Q(_version=entity._version)
        values = {**claim_fields, "_version": entity._version + 1}
    if dao.update_all(guard, values) > 0:
        for attr, value in claim_fields.items():
            setattr(entity, attr, value)
        if versioned:
            # The next save of ``entity`` expects the claimed version.
            entity._version += 1
            entity._next_version = entity._version + 1
        return True
    return False


def _claim_held_back(
    dao: DAO,
    criteria: Q,
    limit: int,
    order_by: Sequence[str],
    hold_back: HoldBack,
    try_claim: Callable[[Any], bool],
    read_page: Callable[[Q, int, int, Sequence[str]], list[Any]],
) -> list[BaseEntity]:
    """Claim up to ``limit`` rows page by page, keeping back each grouped row
    whose group has an earlier holding row this call did not claim."""
    claimed: list[BaseEntity] = []
    # A row is claimed only after every earlier holding row of its group
    # is, so the rows a group has claimed here all sort before any of its
    # rows still to be checked.
    claimed_in_group: Counter[tuple[Any, ...]] = Counter()
    lanes: tuple[Q, ...] = hold_back.lanes or (Q(),)
    rows_read = 0
    # Read a page of ``limit`` candidates at a time until ``limit`` rows are
    # claimed or none remain, so held rows never use up the batch. Claimed
    # rows stop matching ``criteria``, which shifts the next page's offset
    # back by the rows claimed. Pages are not capped: a cap would let a held
    # group fill every batch and starve the other groups. The portable
    # page read returns held rows too, so a large held backlog costs one page
    # read per ``limit`` held rows on every call.
    while len(claimed) < limit:
        page = read_page(criteria, limit, rows_read - len(claimed), order_by)
        if not page:
            break
        rows_read += len(page)

        for entity in page:
            if len(claimed) >= limit:
                break
            if _try_claim_in_group(
                dao, entity, hold_back, lanes, claimed_in_group, try_claim
            ):
                claimed.append(entity)

    return claimed


def _try_claim_in_group(
    dao: DAO,
    entity: Any,
    hold_back: HoldBack,
    lanes: tuple[Q, ...],
    claimed_in_group: Counter[tuple[Any, ...]],
    try_claim: Callable[[Any], bool],
) -> bool:
    """Claim ``entity`` unless an earlier holding row of its group is unclaimed.

    A successful claim of a grouped row adds one to its group's count in
    ``claimed_in_group``.
    """
    lane_index = hold_back.lane_of(entity)
    if lane_index is None:
        return try_claim(entity)

    same_group: dict[str, Any] = {
        column: getattr(entity, column) for column in hold_back.group_by
    }
    group = (*same_group.values(), lane_index)
    earlier = (
        Q(**same_group)
        & hold_back.applies
        & lanes[lane_index]
        & hold_back.holds
        & _earlier_than(entity, hold_back.order)
    )
    # The rows this call claimed in the group are all earlier than
    # this row and still hold, so a larger count means an earlier
    # row this call did not claim. One count per row binds the same
    # parameters however large the batch is.
    held = dao.count(earlier) > claimed_in_group[group]
    if held or not try_claim(entity):
        return False

    claimed_in_group[group] += 1
    return True


def _read_claim_candidates(
    dao: DAO, criteria: Q, limit: int, offset: int, order_by: Sequence[str]
) -> list[Any]:
    """Read one page of claim candidates: up to ``limit`` entities matching
    ``criteria`` in ``order_by`` order, skipping the first ``offset``."""
    candidate_qs = dao.query.filter(criteria)
    if order_by:
        candidate_qs = candidate_qs.order_by(list(order_by))
    return list(candidate_qs.offset(offset).limit(limit).all(with_total=False).items)


def _claim_page_reader(
    dao: DAO, hold_back: HoldBack
) -> Callable[[Q, int, int, Sequence[str]], list[Any]]:
    """The page read for a claim with ``hold_back``: the adapter's
    ``claim_candidates`` when the provider declares
    ``FILTERED_CLAIM_CANDIDATES``, else the portable read."""
    if _uses_adapter_operation(dao, DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES):
        return partial(_read_filtered_claim_candidates, dao, hold_back)
    return partial(_read_claim_candidates, dao)


def _read_filtered_claim_candidates(
    dao: DAO,
    hold_back: HoldBack,
    criteria: Q,
    limit: int,
    offset: int,
    order_by: Sequence[str],
) -> list[Any]:
    """Read one page of claim candidates through the adapter's
    ``claim_candidates``, which leaves out the rows ``hold_back`` holds."""
    adapter = cast(ClaimCandidatesPort, dao._adapter)
    with dao.session_scope() as session:
        return adapter.claim_candidates(
            session, criteria, limit, offset, order_by, hold_back
        )


def _entity_id_name(dao: DAO) -> str:
    """The attribute name of the identifier of ``dao``'s entity class."""
    entity_id_field = id_field(dao.entity_cls)
    assert entity_id_field is not None, (
        f"`{dao.entity_cls.__name__}` does not have an identity field"
    )
    assert entity_id_field.field_name is not None
    return entity_id_field.field_name


def portable_claim(
    dao: DAO,
    criteria: Q,
    claim_fields: Mapping[str, Any],
    limit: int,
    order_by: Sequence[str] = (),
    hold_back: HoldBack | None = None,
) -> list[BaseEntity]:
    """Claim rows on any adapter, with the promises :meth:`DAO.claim`
    states.

    It reads candidates, then claims each one with a guarded update that
    re-checks ``criteria``. An ungrouped claim costs ``1 + N`` round trips.
    A claim with ``hold_back`` also counts earlier rows for each grouped
    candidate and may read more than one page of candidates. It runs inside
    the adapter's ``claim_lock()``.
    """
    if limit <= 0:
        return []

    order_by = _order_keys(order_by)
    id_name = _entity_id_name(dao)
    try_claim = partial(_try_claim, dao, id_name, criteria, dict(claim_fields))

    with dao._adapter.claim_lock():
        if hold_back is None:
            candidates = _read_claim_candidates(dao, criteria, limit, 0, order_by)
            return [entity for entity in candidates if try_claim(entity)]

        read_page = _claim_page_reader(dao, hold_back)
        return _claim_held_back(
            dao, criteria, limit, order_by, hold_back, try_claim, read_page
        )


def portable_delete_top(
    dao: DAO, criteria: Q, limit: int, order_by: str | None = None
) -> int:
    """Delete rows on any adapter, with the promises
    :meth:`DAO.delete_top` states.

    It reads up to ``limit`` identifiers, then deletes by identifier. It runs
    inside the adapter's ``claim_lock()``.
    """
    if limit <= 0:
        return 0

    id_name = _entity_id_name(dao)

    with dao._adapter.claim_lock():
        # Read up to ``limit`` identifiers through the entity-level query
        # API, projecting only the id so blob columns are left unread.
        candidate_qs = dao.query.filter(criteria)
        if order_by:
            candidate_qs = candidate_qs.order_by(order_by)
        records = candidate_qs.only(id_name).limit(limit).all(with_total=False).items

        # Delete by identifier in sub-batches so the ``IN`` clause never
        # exceeds a backend's bind-parameter ceiling (e.g. SQLite's default
        # limit of 999). ``limit`` can be larger than that, so chunk rather
        # than emit one oversized ``IN (...)``.
        ids = [getattr(record, id_name) for record in records]
        deleted = 0
        for start in range(0, len(ids), _DELETE_IN_CHUNK_SIZE):
            chunk = ids[start : start + _DELETE_IN_CHUNK_SIZE]
            chunk_filter: dict[str, Any] = {f"{id_name}__in": chunk}
            deleted += dao.delete_all(Q(**chunk_filter))
        return deleted


class DAO:
    """The entity-level operations on one entity class's rows, built on the
    database adapter's `DAOPort`.

    The lifecycle methods (``get``, ``save``, ``create``, ``update``,
    ``delete``) work on entities: they convert between entities and models,
    check versions, track the Unit of Work, and call the adapter in the
    session :meth:`session_scope` picks. The write methods delegate to
    `protean.infra.dao_write`, and the read methods to
    `protean.infra.dao_read`.

    Args:
        domain: The domain this DAO belongs to.
        provider: The database provider the adapter belongs to. It supplies
            standalone sessions and ends them.
        adapter: The adapter's DAO for the entity class.

    Raises:
        ConfigurationError: ``provider`` declares a flag in
            ``DatabaseCapabilities`` whose port ``adapter``'s class does not
            subclass.
    """

    def __init__(self, domain: Domain, provider: Any, adapter: DAOPort) -> None:
        _check_flag_ports(provider, adapter)

        #: The domain the DAO belongs to.
        self.domain = domain

        #: The provider that supplies sessions to the adapter.
        self.provider = provider

        #: The adapter's DAO, which reads and writes the rows.
        self._adapter = adapter

        #: The entity class the DAO stores.
        self.entity_cls: type[BaseEntity] = adapter.entity_cls

        #: The adapter's database model class for ``entity_cls``.
        self.database_model_cls: type[DatabaseModelPort] = adapter.database_model_cls

        #: The table, index or store key the entity's rows live under.
        self.schema_name: str = adapter.schema_name

        #: An empty query object that can be used to begin filtering/querying operations
        #: on the underlying data store.
        self.query = QuerySet(self, domain, self.entity_cls)

        #: Tracks whether the DAO needs to operate outside any active Unit of Work transactions.
        self._outside_uow = False

    def __repr__(self) -> str:
        return f"DAO <{self.entity_cls.__name__}> over {self._adapter!r}"

    @property
    def _is_standalone(self) -> bool:
        """Check if this DAO is operating outside a Unit of Work.

        Returns True when the DAO must commit, roll back and close its own
        session: when no Unit of Work is active, or when the DAO was told to
        work outside it with ``outside_uow()``.
        """
        return not current_uow or self._outside_uow

    @contextmanager
    def session_scope(self) -> Iterator[SessionProtocol]:
        """Yield the session an operation runs in, and end it when standalone.

        Inside a Unit of Work, unless :meth:`outside_uow` was called, it yields
        the Unit of Work's session for the provider and ends nothing: the Unit
        of Work commits or rolls it back.

        Otherwise it yields ``provider.new_session()``. When the block exits
        normally, it commits the session through ``provider.commit``. When the
        block or the commit raises an ``Exception``, it rolls the session back
        through ``provider.rollback`` and re-raises. It always closes the
        session.
        """
        if not self._is_standalone:
            yield current_uow.get_session(self.provider.name)
            return

        session = self.provider.new_session()
        try:
            yield session
            self.provider.commit(session)
        except Exception:  # any failure rolls back, then re-raises
            self.provider.rollback(session)
            raise
        finally:
            session.close()

    def flush(self) -> None:
        """Run the session's pending writes inside its transaction, without
        committing.

        Callers flush to write a parent row before the child rows that
        reference it, or to have the database assign an
        ``Auto(increment=True)`` key before it is copied back onto the
        aggregate. It calls ``provider.flush``, which does nothing on a
        provider whose sessions write at commit.

        Raises:
            ExpectedVersionError: The flush hit an optimistic-concurrency
                conflict.
        """
        with self.session_scope() as session:
            self.provider.flush(session)

    def _sync_event_position(self, entity: BaseEntity) -> None:
        """Sync the aggregate's event position from the event store.

        When an aggregate is loaded from the persistence store, its
        ``_event_position`` must reflect the last written event so that
        optimistic concurrency control (expected-version checks) works
        correctly on subsequent ``raise_()`` calls.

        This is a no-op for non-aggregate entities.
        """
        if entity.element_type != DomainObjects.AGGREGATE:
            return

        id_f = id_field(entity)
        assert id_f is not None and id_f.field_name is not None
        identifier = getattr(entity, id_f.field_name)
        store = current_domain.event_store
        last_message = store.read_last_message(
            f"{entity.meta_.stream_category}-{identifier}"
        )
        if last_message:
            assert last_message.metadata is not None
            assert last_message.metadata.event_store is not None
            entity._event_position = last_message.metadata.event_store.position

    def _track_in_uow(self, entity: BaseEntity) -> BaseEntity:
        """Return the instance to hand back for an aggregate just loaded.

        Inside a Unit of Work, an aggregate already tracked there is returned
        in place of the loaded copy. Two copies of one aggregate in one
        transaction would each count versions and event positions from the
        store, which has not seen the other copy's pending changes.

        Otherwise the loaded aggregate's event position is synced from the
        event store and, inside a Unit of Work, the aggregate is registered so
        that later reads return this instance. The events it raises are
        persisted on commit only once ``add()`` saves it. Non-aggregate
        entities are returned unchanged.
        """
        if not isinstance(entity, BaseAggregate):
            return entity

        tracked = self._tracked_in_uow(entity)
        if tracked is not None:
            return tracked

        self._sync_event_position(entity)
        if not self._is_standalone:
            current_uow._add_to_identity_map(entity)
        return entity

    def _tracked_in_uow(self, entity: BaseEntity) -> BaseAggregate | None:
        """The instance of ``entity``'s aggregate that the active Unit of
        Work tracks, if this DAO works inside one and it tracks one."""
        if self._is_standalone or not isinstance(entity, BaseAggregate):
            return None
        id_f = id_field(entity)
        assert id_f is not None and id_f.field_name is not None
        return current_uow._tracked_instance(
            type(entity), getattr(entity, id_f.field_name)
        )

    def outside_uow(self) -> DAO:
        """When called, the DAO is instructed to work outside active transactions."""
        self._outside_uow = True

        # Return the DAO object to support method chaining
        return self

    ##############################
    # Operations on many records #
    ##############################

    def fetch(
        self,
        criteria: Q,
        *,
        offset: int = 0,
        limit: int = 10,
        order_by: Sequence[str] = (),
        with_total: bool = True,
        fields: list[str] | None = None,
    ) -> ResultSet:
        """Return one page of the entities that match ``criteria``, read in
        the session :meth:`session_scope` picks.

        Each entity is marked retrieved. Inside a Unit of Work, each aggregate
        is tracked in it, or swapped for the instance it already tracks.
        With ``fields`` set, ``items`` holds read-only ``Record`` objects with
        those fields, and nothing is tracked. An empty ``fields`` selects
        nothing and returns full entities. With ``with_total`` set to
        ``False``, the adapter may skip computing ``total``.
        """
        return dao_read.fetch(
            self,
            criteria,
            offset=offset,
            limit=limit,
            order_by=order_by,
            with_total=with_total,
            fields=fields,
        )

    def count(self, criteria: Q) -> int:
        """Return the number of rows that match ``criteria``."""
        return dao_read.count(self, criteria)

    def raw(self, query: Any, data: Any = None) -> ResultSet:
        """Run ``query`` through the adapter's ``raw`` and return the
        entities, tracked in the Unit of Work as :meth:`fetch` tracks them.

        Raises:
            NotSupportedError: The provider does not declare ``RAW_QUERIES``.
        """
        return dao_read.raw(self, query, data)

    def has_table(self) -> bool:
        """Whether the adapter's table, collection or index exists."""
        return self._adapter.has_table()

    def update_all(self, criteria: Q, values: Mapping[str, Any]) -> int:
        """Write ``values`` to every row that matches ``criteria``.

        .. warning::

            This is an **internal framework method** reserved for
            infrastructure needs (outbox, projection rebuilds). It bypasses
            domain validation, invariants, and the Unit of Work's tracking.
            Do not call it from domain-level code.

        Returns:
            The number of rows that matched ``criteria``. The Elasticsearch
            adapter returns ``0`` when ``values`` is empty.
        """
        with self.session_scope() as session:
            return self._adapter.update_all(session, criteria, values)

    def delete_all(self, criteria: Q | None = None) -> int:
        """Delete every row that matches ``criteria``, or every row when
        ``criteria`` is ``None``.

        .. warning::

            This is an **internal framework method** reserved for
            infrastructure needs (outbox, projection rebuilds, table cleanup).
            It bypasses domain validation, invariants, and the Unit of Work's
            tracking. Do not call it from domain-level code.

        Returns:
            The number of rows that matched ``criteria``.

        Raises:
            Exception: The adapter's error, logged and re-raised.
        """
        return dao_write.delete_all(self, criteria)

    def claim(
        self,
        criteria: Q,
        claim_fields: Mapping[str, Any],
        limit: int,
        order_by: str | Sequence[str] | None = None,
        hold_back: HoldBack | None = None,
    ) -> list[BaseEntity]:
        """Claim up to ``limit`` rows that match ``criteria`` and return them.

        Each claimed row gets ``claim_fields`` written to it, and the returned
        entities show that post-claim state. The claim is committed before the
        method returns, so call it **outside** an active Unit of Work. Inside
        one, the write waits for the Unit of Work to commit, and other workers
        do not see the claim until then.

        Every implementation keeps these promises:

        - No two callers claim the same row. A caller that loses a race for a
          row does not get it.
        - With ``hold_back``, a grouped row is claimed only when every earlier
          row of its group that matches ``hold_back.holds`` is claimed by the
          same call. A row locked by another caller holds the rows behind it.
        - On an aggregate, each claimed row's ``_version`` advances by one,
          and the returned entity carries the new version, so it can be saved
          as it is. A later claim of the row advances the version again, and
          the repository's version check then refuses a save of the entity
          the earlier claim returned.

        ``claim_fields`` must make a claimed row stop matching ``criteria``.
        The call may wait briefly on a row another caller has locked. How a
        lost race shows up depends on the backend; see ADR-0013.

        Args:
            criteria: Selects the rows that can be claimed.
            claim_fields: Values to write on each claimed row.
            limit: The most rows to claim. ``0`` or less claims none.
            order_by: A key, or a list of keys applied in turn, such as
                ``["-priority", "created_at"]``. A ``-`` prefix sorts that key
                descending.
            hold_back: Keeps a grouped row back until the earlier rows of its
                group are claimed with it. ``None`` claims the top rows with no
                grouping.

        Returns:
            The claimed entities, with ``claim_fields`` applied.

        """
        if limit <= 0:
            return []

        order = _order_keys(order_by)
        if _uses_adapter_operation(self, DatabaseCapabilities.NATIVE_CLAIM):
            adapter = cast(NativeClaimPort, self._adapter)
            with self.session_scope() as session:
                return adapter.claim(
                    session, criteria, claim_fields, limit, order, hold_back
                )
        return portable_claim(self, criteria, claim_fields, limit, order, hold_back)

    def delete_top(
        self,
        criteria: Q,
        limit: int,
        order_by: str | None = None,
    ) -> int:
        """Delete up to ``limit`` rows that match ``criteria``.

        Large cleanups use this to delete in fixed-size batches.

        .. warning::

            Like :meth:`delete_all`, this is an **internal framework method**
            reserved for infrastructure needs (outbox cleanup, table pruning).
            It bypasses domain validation, invariants, and the Unit of Work's
            tracking. Do not call it from domain-level code.

        Args:
            criteria: Selects the rows that can be deleted.
            limit: The most rows to delete. ``0`` or less deletes none.
            order_by: One sort key, such as ``"-priority"``, that decides which
                rows go first.

        Returns:
            The number of rows deleted, at most ``limit``.
        """
        if limit <= 0:
            return 0

        if _uses_adapter_operation(self, DatabaseCapabilities.BOUNDED_DELETE):
            adapter = cast(BoundedDeletePort, self._adapter)
            with self.session_scope() as session:
                return adapter.delete_top(session, criteria, limit, order_by)
        return portable_delete_top(self, criteria, limit, order_by)

    ######################
    # Life-cycle methods #
    ######################

    def get(self, identifier: Any) -> BaseEntity:
        """Return the one entity whose identity is ``identifier``.

        Raises:
            ObjectNotFoundError: No entity has the identifier.
            TooManyObjectsError: More than one entity has the identifier.
        """
        return dao_read.get(self, identifier)

    def find_by(self, **kwargs: Any) -> BaseEntity:
        """Return the one entity whose attributes equal ``kwargs``.

        Raises:
            ObjectNotFoundError: No entity matches.
            TooManyObjectsError: More than one entity matches.
        """
        return dao_read.find_by(self, **kwargs)

    def exists(self, excludes_: dict[str, Any], **filters: Any) -> bool:
        """Return whether any entity matches ``filters`` and none of
        ``excludes_``."""
        return dao_read.exists(self, excludes_, **filters)

    def create(self, *args: Any, **kwargs: Any) -> BaseEntity:
        """Build an entity from ``args`` and ``kwargs`` and write it as a new
        row.

        Inside a Unit of Work, an aggregate is tracked in it as saved.

        Returns:
            The created entity.

        Raises:
            ValidationError: A field value fails validation, or a unique
                field's value is taken.
        """
        return dao_write.create(self, *args, **kwargs)

    def apply_pre_persist_hooks(self, entity_obj: Any) -> None:
        """Stamp ``auto_now``/``auto_now_add`` fields, then run aggregate enrichers.

        Enrichers run only on aggregates the user registered. They never run on
        the framework's internal aggregates, such as outbox rows.

        The ``@invariant.pre`` checks do not run on these writes. On an
        aggregate, the post-invariants run once after the stamping and once
        after each enricher, unless the save runs inside an open
        ``atomic_change`` block. When a check fails, or a hook raises, that
        hook's writes are undone and the save aborts. A ``ValidationError``
        carries a ``location`` that names the hook; any other exception
        propagates as it was raised.

        ``save`` calls this unless ``apply_hooks=False``. A caller that must run
        the hooks earlier than the write (so a raising enricher fails before any
        other store is touched) calls it directly and then saves with
        ``apply_hooks=False``.
        """
        dao_write.apply_pre_persist_hooks(self, entity_obj)

    def save(self, entity_obj: Any, *, apply_hooks: bool = True) -> Any:
        """Persist a fully formed entity: create it if it was never saved, else
        update it.

        Args:
            entity_obj: The entity to persist.
            apply_hooks: When ``False``, skip the pre-persist hooks
                (``auto_now``/``auto_now_add`` stamping and aggregate
                enrichers) for a raw write, such as a bulk migration that must
                not touch audit fields. The optimistic-concurrency version
                check still applies.

        Returns:
            The saved entity.

        Raises:
            ValidationError: A field value or a uniqueness constraint fails
                validation.
        """
        return dao_write.save(self, entity_obj, apply_hooks=apply_hooks)

    def save_if_absent(self, entity_obj: Any, *, apply_hooks: bool = True) -> Any:
        """Save ``entity_obj`` unless another row already holds its unique key.

        The unique key is the values of the fields of each ``Index`` declared
        with ``unique=True`` and no ``where`` predicate. This method does not
        check an index with a ``None`` among those values, and leaves such a
        row to the database's own rule for NULLs. When the entity declares no
        such index, this is :meth:`save`.

        When the provider declares ``INSERT_IF_ABSENT``, the adapter checks the
        key and writes the row as one step, so a writer that loses a race also
        gets ``None``. The write runs inside the adapter's ``claim_lock()``.
        A ``ValidationError`` from the save also returns ``None`` when another
        row holds the key, because a key field that is also declared
        ``unique=True`` fails its check before the write. The pre-persist
        hooks run before the adapter checks the key, so on ``None`` the entity
        keeps its ``auto_now`` stamps and its enrichers' changes; only the
        aggregate's version is put back.

        Inside a Unit of Work the memory adapter only stages the row. When
        another session commits a row with the same key first, the Unit of
        Work's commit drops this row after this method has returned the
        entity, and records it in the session's ``dropped_rows``.

        Otherwise this method checks for the key, then saves. Two writers that
        check at the same moment can both pass the check. A store with a unique
        index on the key then rejects the second write with its own error. A
        store with no such index, such as Elasticsearch, keeps both rows.

        Args:
            entity_obj: The entity to persist.
            apply_hooks: Passed to :meth:`save`.

        Returns:
            The saved entity, or ``None`` when another row holds the unique key.
            Nothing is written in that case.

        Raises:
            ValidationError: ``save`` rejected the entity, and no other row
                holds the unique key.
        """
        return dao_write.save_if_absent(self, entity_obj, apply_hooks=apply_hooks)

    def _save_if_key_free(self, entity_obj: Any, *, apply_hooks: bool) -> Any:
        """Check for ``entity_obj``'s unique key, then save it when no other
        row holds the key. Returns ``None`` when one does."""
        return dao_write._save_if_key_free(self, entity_obj, apply_hooks=apply_hooks)

    @deprecated_from_registry("dao_update")
    def update(
        self,
        entity_obj: Any,
        *data: Any,
        apply_hooks: bool = True,
        **kwargs: Any,
    ) -> BaseEntity:
        """Apply a field patch to an existing entity and persist it.

        .. deprecated:: 0.18.0
            The patch-and-persist path is deprecated and is removed in v0.20.0.
            Load the aggregate, invoke a behaviour method that applies the
            change, and persist it with ``repository.add()`` instead.

        Applies the values, checks uniqueness, then persists the entity the
        way :meth:`save` does. An aggregate update advances its version, stamps
        ``auto_now`` fields, and runs pre-persist enrichers.

        Takes the values as a dictionary or as keyword arguments::

            >>> dao.update(user, {'age': 10})
            >>> dao.update(user, age=10)

        ``apply_hooks`` is a reserved keyword argument. To patch a field named
        ``apply_hooks``, use the dictionary form
        (``dao.update(user, {'apply_hooks': ...})``).

        Args:
            entity_obj: The persisted entity to update.
            *data: A dictionary of values to apply.
            apply_hooks: When ``False``, skip the pre-persist hooks
                (``auto_now`` stamping and enrichers). The optimistic-concurrency
                version check still applies. See :meth:`save`.
            **kwargs: Values to apply, as keyword arguments.

        Returns:
            The updated entity.

        Raises:
            ObjectNotFoundError: ``entity_obj`` was never persisted.
            ValidationError: A field value or a uniqueness constraint fails
                validation.
            ExpectedVersionError: The stored aggregate has a newer version.
        """
        return self._apply_update(entity_obj, *data, apply_hooks=apply_hooks, **kwargs)

    def _apply_update(
        self,
        entity_obj: Any,
        *data: Any,
        apply_hooks: bool = True,
        **kwargs: Any,
    ) -> BaseEntity:
        """Apply a field patch to an existing entity and persist it.

        The real work behind :meth:`update`, split out so ``QuerySet.update``
        can drive a bulk patch without re-emitting the per-call deprecation
        warning once for every matched row. Not a public API; the deprecation
        lives on the :meth:`update` wrapper.
        """
        return dao_write._apply_update(
            self, entity_obj, *data, apply_hooks=apply_hooks, **kwargs
        )

    def delete(self, entity_obj: Any) -> Any:
        """Delete ``entity_obj``'s row, unless it is already destroyed, and
        mark the entity destroyed.

        Returns:
            The entity.

        Raises:
            Exception: The adapter's error, logged and re-raised.
        """
        return dao_write.delete(self, entity_obj)
