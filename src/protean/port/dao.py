import logging
from abc import ABCMeta, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.queryset import QuerySet, ResultSet
from protean.exceptions import (
    ObjectNotFoundError,
    TooManyObjectsError,
    ValidationError,
)
from protean.port.provider import BaseProvider
from protean.utils import DomainObjects
from protean.utils.globals import current_domain, current_uow
from protean.utils.query import Q
from protean.utils.reflection import declared_fields, id_field, unique_fields

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Max identifiers per ``IN (...)`` clause in the portable ``_delete_top``
# default. Kept under SQLite's default ``SQLITE_MAX_VARIABLE_NUMBER`` of 999 so
# the fallback path is safe on every backend regardless of batch size.
_DELETE_IN_CHUNK_SIZE = 900


class BaseDAO(metaclass=ABCMeta):
    """Base class for concrete DAO (Data Access Object) implementations.

    A DAO bridges the domain entity layer and the database. It has two parts:

    1. **Abstract methods** (``_filter``, ``_create``, ``_update``,
       ``_update_all``, ``_delete``, ``_delete_all``, ``_raw``, ``has_table``)
       — override these in your adapter to interact with the database.

    2. **Lifecycle methods** (``get``, ``save``, ``create``, ``update``,
       ``delete``) — fully implemented wrappers that handle entity ↔ model
       conversion, version checking, UoW tracking, and then delegate to
       the abstract internals above.

    See ``BaseProvider`` in ``protean.port.provider`` for the full adapter
    development guide, including the call-flow diagram showing how the
    framework invokes DAO methods.

    :param domain: the domain of the application this DAO is associated with.
    :param provider: the corresponding provider object of the database
        implementation, from whom the DAO can request sessions and connections.
    :param database_model_cls: the concrete model class associated with the
        DAO. The model class is a direct representation of an object in
        ORM/ODM terms or as represented by a python driver.
    :param entity_cls: the domain entity class associated with the DAO.
    """

    def __init__(
        self,
        domain: "Domain",
        provider: BaseProvider,
        entity_cls: type[BaseEntity],
        database_model_cls: type[BaseDatabaseModel],
    ):
        #: Holds a reference to the domain to which the DAO belongs to.
        self.domain = domain

        #: Holds a reference to the provider which supplies the DAO with live connections.
        self.provider = provider

        #: Holds a reference to the model class representation required by the ORM/ODM or the python database driver.
        self.database_model_cls = database_model_cls

        #: Holds a reference to the entity class associated with this DAO.
        self.entity_cls = entity_cls

        #: An empty query object that can be used to begin filtering/querying operations
        #: on the underlying data store.
        self.query = QuerySet(self, domain, self.entity_cls)

        #: The actual database document or table name associated with the DAO.
        #: This is used for deriving namespaces for storage containers, especially the default dict provider.
        self.schema_name = entity_cls.meta_.schema_name

        #: Tracks whether the DAO needs to operate outside any active Unit of Work transactions.
        self._outside_uow = False

    def _get_session(self) -> Any:
        """Returns an active connection to the persistence store.

        - If there is an active transaction, the connection associated with the transaction (in the UoW) is returned
        - If the DAO has been explicitly instructed to work outside a UoW (with the help of `_outside_uow`), or if
          there are no active transactions, a new connection is retrieved from the provider and returned.
        """
        if current_uow and not self._outside_uow:
            return current_uow.get_session(self.provider.name)
        else:
            return self.provider.get_connection()

    @property
    def _is_standalone(self) -> bool:
        """Check if this DAO is operating outside a Unit of Work.

        Returns True when the DAO must manage its own commit/rollback/close
        lifecycle — either because there is no active UoW, or because the DAO
        has been explicitly instructed to work outside it.
        """
        return not current_uow or self._outside_uow

    def _commit_if_standalone(self, conn: Any) -> None:
        """Commit the connection if we're not inside a Unit of Work.

        When operating within a UoW, the UoW handles commit/rollback/close.
        When standalone, we commit immediately and handle errors.
        """
        if self._is_standalone:
            try:
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _flush(self) -> None:
        """Flush pending writes to the data store within the active
        transaction, without committing.

        Default is a no-op. Adapters whose unit-of-work batches writes until
        commit (e.g. SQLAlchemy) override this so callers can force buffered
        INSERT/UPDATE statements to execute inside the current transaction —
        for example to materialize a parent row before dependent child rows
        referencing it are written, or to materialize a store-generated
        ``Auto(increment=True)`` primary key before it is reflected back onto
        the aggregate. Providers that persist eagerly and assign auto-increment
        values during ``_create`` (memory, Elasticsearch) need no flush and keep
        the default.
        """
        return None

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
        last_message = current_domain.event_store.store.read_last_message(
            f"{entity.meta_.stream_category}-{identifier}"
        )
        if last_message:
            assert last_message.metadata is not None
            assert last_message.metadata.event_store is not None
            entity._event_position = last_message.metadata.event_store.position

    def _track_in_uow(self, entity: BaseEntity) -> None:
        """Register the aggregate in the active Unit of Work's identity map.

        Tracking loaded aggregates lets the UoW collect domain events
        raised during the transaction and persist them on commit.

        This is a no-op for non-aggregate entities or when there is no
        active UoW.
        """
        if current_uow and entity.element_type == DomainObjects.AGGREGATE:
            current_uow._add_to_identity_map(entity)

    def outside_uow(self) -> "BaseDAO":
        """When called, the DAO is instructed to work outside active transactions."""
        self._outside_uow = True

        # Return the DAO object to support method chaining
        return self

    ###############################
    # Repository-specific methods #
    ###############################

    @abstractmethod
    def _filter(
        self,
        criteria: Q,
        offset: int = 0,
        limit: int = 10,
        order_by: Sequence[str] = (),
        with_total: bool = True,
        fields: list[str] | None = None,
    ) -> ResultSet:
        """
        Filter objects from the data store. Method must return a `ResultSet`
        object.

        When ``with_total`` is ``False`` the caller does not need the full
        match count, so adapters may skip any expensive total computation
        (e.g. SQL's separate ``COUNT`` query) and report only the size of the
        returned page in ``ResultSet.total``. Adapters that derive the total
        for free (memory, Elasticsearch) may continue to populate it.

        When ``fields`` is a list of attribute (column) names (set via
        ``QuerySet.only()``), adapters should fetch only those columns (the
        identifier is always among them) instead of full rows. The returned
        ``ResultSet.items`` are still raw storage records; the caller builds
        read-only ``Record`` objects from them via the model's ``to_records``.
        ``None`` means fetch full rows as usual.
        """

    @abstractmethod
    def _create(self, model_obj: Any) -> Any:
        """Persist a new entity into the persistent store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should persist a new record in the data store.

        This method is invoked by the `create` wrapper and should not be called directly.

        Returns the persisted model object.

        :param model_obj: The model object supplied in an ORM/ODM/Python driver friendly/format
        """

    @abstractmethod
    def _update(self, model_obj: Any, expected_version: int | None = None) -> Any:
        """Update entity data in the persistence store.

        Concrete implementations must perform the version check **atomically**
        with the write when ``expected_version`` is not ``None``.  For example,
        a SQL adapter should use ``UPDATE … WHERE _version = :expected`` and
        check the affected row count rather than doing a separate SELECT.

        Raises ``ExpectedVersionError`` when the stored version does not match
        ``expected_version``.

        :param model_obj: The model object in an ORM/ODM/driver-friendly format.
        :param expected_version: The version the record must currently have for
            the update to succeed.  ``None`` means no version check is required.
        """

    @abstractmethod
    def _update_all(self, criteria: Q, *args: Any, **kwargs: Any) -> int:
        """Perform a bulk update on the persistent store.

        Concrete implementation will be provided by the database DAO class.
        Updates all objects satisfying ``criteria`` with attributes specified
        in ``args`` (a dict) and/or ``kwargs``.

        .. warning::

            This is an **internal framework method** reserved for
            infrastructure needs (outbox, projection rebuilds).  It bypasses
            domain validation, invariants, and the Unit of Work.  Do not call
            it from domain-level code.

        Returns the count of rows matched for the provided criteria.

        :param criteria: A ``Q`` object wrapping one or more filter conditions.
        :param args: A dictionary of attribute data to be updated.
        :param kwargs: Keyword args specifying attribute data to be updated.
        """

    @abstractmethod
    def _delete(self, model_obj: Any) -> Any:
        """Delete this entity from the persistence store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should delete existing record in the persistent store, by its unique identifier.

        This method is invoked by DAO's `delete` wrapper method and should not be called directly.

        Returns the deleted model object.

        :param model_obj: The model object supplied in an ORM/ODM/Python driver friendly/format
        """

    @abstractmethod
    def _delete_all(self, criteria: Q | None = None) -> int:
        """Perform a bulk delete on the persistent store.

        Concrete implementation will be provided by the database DAO class.
        Deletes all objects satisfying ``criteria``.

        .. warning::

            This is an **internal framework method** reserved for
            infrastructure needs (outbox, projection rebuilds, table cleanup).
            It bypasses domain validation, invariants, and the Unit of Work.
            Do not call it from domain-level code.

        Returns the count of rows matched for the provided criteria.

        :param criteria: A ``Q`` object wrapping one or more filter conditions.
            If ``None``, all records of the table/document are removed.
        """

    @abstractmethod
    def _count(self, criteria: Q) -> int:
        """Count rows matching ``criteria`` without materializing them.

        Concrete implementations should issue a single ``SELECT COUNT(*)``
        (or equivalent) without projecting columns or fetching rows.

        :param criteria: A ``Q`` object wrapping the filter conditions.
        :return: The number of matching rows.
        """

    @abstractmethod
    def _raw(self, query: Any, data: Any = None) -> Any:
        """Run raw query on Data source. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should fetch all objects satisfying the raw query. Running a raw query on the data store
        should always returns entity instance objects. If the results were not synthesizable back into
        entity objects, an exception should be thrown.

        This method is invoked by Queryset's `raw()` method and should not be called directly.

        .. warning:: The `raw()` method bypasses ORM/ODM unit-of-work automation.

        Returns the result specified by the raw query.

        :param query: Raw query to be passed to the data store.
        :param data: Data to be passed to the data store as-is, along with the query
                     (in case of update statements, for example).
        """

    @abstractmethod
    def has_table(self) -> bool:
        """Check if the table/collection exists in the data store.

        Returns True if the table/collection exists, False otherwise.

        :return: Boolean indicating if the table/collection exists
        """

    def _claim(
        self,
        criteria: Q,
        claim_fields: dict[str, Any],
        limit: int,
        order_by: str | None = None,
    ) -> list[BaseEntity]:
        """Atomically select up to ``limit`` rows matching ``criteria``, apply
        ``claim_fields`` as an update, and return the claimed rows.

        .. important::
            Call this **outside** an active Unit of Work. The claim is committed
            via the DAO's standalone commit so the lock and state change are
            durable the moment the method returns; inside a UoW the write would
            not commit until the UoW does, so other workers would not see the
            claim and the "lock-then-return" guarantee would not hold.

        This is the **portable default**. It reads candidate rows and then
        re-asserts ``criteria`` inside a guarded update for each one
        (``UPDATE … WHERE id = :id AND <criteria>``), at the cost of ``1 + N``
        round trips. Its concurrency behaviour depends on the backend:

        - **Relational backends** (PostgreSQL, MySQL, SQL Server): the guarded
          ``UPDATE`` re-evaluates its predicate against committed state once it
          acquires the row lock, so a row another worker already claimed no
          longer matches — the update affects zero rows and the row is skipped.
          No double-claim.
        - **SQLite**: writers are serialized at the database level, so claims
          are effectively sequential (a contended write may raise
          ``SQLITE_BUSY`` rather than skip).
        - **The in-memory adapter** overrides this to hold its provider lock
          across the whole read-and-claim, serializing claimers in-process.
        - **Elasticsearch**: document versioning prevents a double write, so no
          two callers claim the same row — but a lost race surfaces as a
          version-conflict error rather than a graceful skip. Elasticsearch is
          not recommended as a concurrently-consumed claim store.

        Adapters with single-statement claim support (e.g. SQLAlchemy on
        PostgreSQL via ``UPDATE … FOR UPDATE SKIP LOCKED … RETURNING``) override
        this with a faster path. See
        ``docs/adr/0013-optimistic-concurrency-and-claim-contract.md``.

        The contract every implementation must uphold:

        - No two callers ever observe the same row as claimed (no
          double-claim). A caller that loses a race for a row simply does not
          get it.
        - Returned rows reflect post-claim state (the applied ``claim_fields``).

        Non-blocking is *not* part of the contract: the portable default may
        briefly block on a contended row's lock before its guard rejects the
        claim. Only the ``FOR UPDATE SKIP LOCKED`` fast path steps over locked
        rows without waiting.

        :param criteria: A ``Q`` object selecting eligible (claimable) rows.
        :param claim_fields: Attribute values to write on each claimed row.
        :param limit: Maximum number of rows to claim. ``<= 0`` claims none.
        :param order_by: Optional single ordering key (e.g. ``"-priority"``).
        :return: List of claimed entity instances reflecting ``claim_fields``.
        """
        if limit <= 0:
            return []

        entity_id_field = id_field(self.entity_cls)
        assert entity_id_field is not None, (
            f"`{self.entity_cls.__name__}` does not have an identity field"
        )
        assert entity_id_field.field_name is not None
        id_name = entity_id_field.field_name

        # Read candidate entities via the entity-level query API (``self.query``
        # returns entities; the low-level ``_filter`` returns raw model objects).
        candidate_qs = self.query.filter(criteria)
        if order_by:
            candidate_qs = candidate_qs.order_by(order_by)
        candidates = candidate_qs.limit(limit).all(with_total=False).items

        claimed = []
        for entity in candidates:
            identifier = getattr(entity, id_name)
            # Re-assert the eligibility criteria in the update so a row claimed
            # by another worker between the read and this write is skipped.
            guard = Q(**{id_name: identifier}) & criteria
            if self._update_all(guard, dict(claim_fields)) > 0:
                for attr, value in claim_fields.items():
                    setattr(entity, attr, value)
                claimed.append(entity)

        return claimed

    def _delete_top(
        self,
        criteria: Q,
        limit: int,
        order_by: str | None = None,
    ) -> int:
        """Delete up to ``limit`` rows matching ``criteria``. Returns the count
        of rows deleted.

        This is the bounded counterpart to :meth:`_delete_all`. It lets
        high-volume cleanups run in fixed-size batches instead of one
        unbounded ``DELETE``, so a backlog of millions of rows can be cleared
        without holding locks for the duration of a single statement or
        bloating the transaction log.

        .. warning::

            Like :meth:`_delete_all`, this is an **internal framework method**
            reserved for infrastructure needs (outbox cleanup, table pruning).
            It bypasses domain validation, invariants, and the Unit of Work.
            Do not call it from domain-level code.

        This is the **portable default**: it selects up to ``limit``
        identifiers (projecting only the id via :meth:`QuerySet.only`, so large
        columns such as JSON blobs are never materialized) and then deletes
        those rows by identifier. Two statements, correct on every backend.
        Adapters with a single-statement bounded delete (e.g. ``DELETE … WHERE
        id IN (SELECT … LIMIT n)``) override this with a faster path.

        :param criteria: A ``Q`` object selecting deletable rows.
        :param limit: Maximum number of rows to delete. ``<= 0`` deletes none.
        :param order_by: Optional single ordering key (e.g. ``"-priority"``)
            controlling which rows are removed first.
        :return: The number of rows deleted (``<= limit``).
        """
        if limit <= 0:
            return 0

        entity_id_field = id_field(self.entity_cls)
        assert entity_id_field is not None, (
            f"`{self.entity_cls.__name__}` does not have an identity field"
        )
        assert entity_id_field.field_name is not None
        id_name = entity_id_field.field_name

        # Read up to ``limit`` identifiers via the entity-level query API,
        # projecting only the id so blob columns are left unread.
        candidate_qs = self.query.filter(criteria)
        if order_by:
            candidate_qs = candidate_qs.order_by(order_by)
        records = candidate_qs.only(id_name).limit(limit).all(with_total=False).items

        if not records:
            return 0

        # Delete by identifier in sub-batches so the ``IN`` clause never
        # exceeds a backend's bind-parameter ceiling (e.g. SQLite's default
        # limit of 999). ``limit`` can be larger than that on this portable
        # path, so chunk rather than emit one oversized ``IN (...)``.
        ids = [getattr(record, id_name) for record in records]
        deleted = 0
        for start in range(0, len(ids), _DELETE_IN_CHUNK_SIZE):
            chunk = ids[start : start + _DELETE_IN_CHUNK_SIZE]
            chunk_filter: dict[str, Any] = {f"{id_name}__in": chunk}
            deleted += self._delete_all(Q(**chunk_filter))
        return deleted

    ######################
    # Life-cycle methods #
    ######################

    def get(self, identifier: Any) -> BaseEntity:
        """Retrieve a specific Record from the Repository by its `identifier`.

        This method internally uses the `filter` method to fetch records.

        Returns exactly one record that matches the identifier.

        Throws `ObjectNotFoundError` if no record was found for the identifier.

        Throws `TooManyObjectsError` if multiple records were found for the identifier.

        :param identifier: id of the record to be fetched from the data store.
        """
        logger.debug(
            f"Lookup `{self.entity_cls.__name__}` object with identifier {identifier}"
        )

        # Filter on the ID field of the entity
        entity_id_field = id_field(self.entity_cls)
        assert entity_id_field is not None, (
            f"`{self.entity_cls.__name__}` does not have an identity field"
        )
        assert entity_id_field.field_name is not None
        filters = {
            entity_id_field.field_name: identifier,
        }

        results = self.query.filter(**filters).all()
        if not results:
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        if len(results) > 1:
            raise TooManyObjectsError(
                f"More than one object of `{self.entity_cls.__name__}` exist with identifier {identifier}",
            )

        # Return the first result, because `filter` would have returned an array
        result: BaseEntity | None = results.first
        assert result is not None
        return result

    def find_by(self, **kwargs: Any) -> "BaseEntity":
        """Find a specific entity record that matches one or more criteria.

        This method internally uses the `filter` method to fetch records.

        Returns exactly one record that matches the identifier.

        Throws `ObjectNotFoundError` if no record was found for the identifier.
        Throws `TooManyObjectsError` if multiple records were found for the identifier.

        :param kwargs: named arguments of attribute names and values to filter on.
        """
        logger.debug(f"Lookup `{self.entity_cls.__name__}` object with values {kwargs}")

        # Filter for item in the data store
        results = self.query.filter(**kwargs).all()

        if not results:
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with values {[item for item in kwargs.items()]} "
                f"does not exist."
            )

        if len(results) > 1:
            raise TooManyObjectsError(
                f"More than one object of `{self.entity_cls.__name__}` exist "
                f"with values {[item for item in kwargs.items()]}",
            )

        # Return the first result, because `filter` would have returned an array
        result: BaseEntity | None = results.first
        assert result is not None
        return result

    def exists(self, excludes_: dict[str, Any], **filters: Any) -> bool:
        """Returns `True` if objects matching the provided filters were found. Else, returns False.

        This method internally uses the `filter` method to fetch records. But it can be overridden for better and
        quicker implementations supported by databases.

        :param filters: criteria to match records against
        :param excludes_: criteria that records should not satisfy
        """
        results = self.query.filter(**filters).exclude(**excludes_)

        # Invokes the __bool__ method on `ResultSet`.
        return bool(results)

    @staticmethod
    def _is_pending_auto_field(
        entity_obj: Any, field_name: str, field_obj: Any
    ) -> bool:
        """True if ``field_obj`` is an ``Auto(increment=True)`` field whose value
        on ``entity_obj`` has not been generated yet (still ``None``).

        A caller-supplied value is thus never treated as pending, so it is
        neither flushed-for nor overwritten during reflection.
        """
        return getattr(field_obj, "increment", False) and (
            getattr(entity_obj, field_name) is None
        )

    def _has_pending_auto_field(self, entity_obj: Any) -> bool:
        """Return True if the entity has any ``Auto(increment=True)`` field still
        awaiting a store-generated value.

        Used to decide whether a pre-reflection flush is worth its cost: a
        relational adapter assigns such a value only when the INSERT is flushed.
        Entities identified by a client-supplied value (e.g. the common
        UUID/string identifier) have no pending auto field and skip the flush.
        """
        return any(
            self._is_pending_auto_field(entity_obj, field_name, field_obj)
            for field_name, field_obj in declared_fields(entity_obj).items()
        )

    def _reflect_auto_fields(self, entity_obj: Any, model_obj: Any) -> None:
        """Copy store-generated auto-increment values back onto the entity.

        An ``Auto(increment=True)`` field's value is produced by the
        persistence store during the create, not by the entity. After the
        record is created, reflect that value back onto the in-memory instance
        so the caller holds the same identity that was persisted. Only fields
        still unset on the entity are updated, so a caller-supplied value is
        never overwritten.
        """
        for field_name, field_obj in declared_fields(entity_obj).items():
            if self._is_pending_auto_field(entity_obj, field_name, field_obj):
                if isinstance(model_obj, dict):
                    # The memory model dict is keyed by field name.
                    field_val = model_obj[field_name]
                else:
                    # An object model (SQLAlchemy) exposes the generated column
                    # under its attribute name, which differs from the field
                    # name when ``referenced_as`` is set.
                    attribute_name = field_obj.attribute_name
                    assert attribute_name is not None
                    field_val = getattr(model_obj, attribute_name)

                setattr(entity_obj, field_name, field_val)

    def create(self, *args: Any, **kwargs: Any) -> "BaseEntity":
        """Create a new record in the data store.

        Performs validations for unique attributes before creating the entity

        Returns the created entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param args: Dictionary object containing the object's data.
        :param kwargs: named attribute names and values
        """
        logger.debug(
            f"Creating new `{self.entity_cls.__name__}` object using data {kwargs}"
        )

        try:
            # Build the entity from input arguments
            # Raises validation errors, if any, at this point
            entity_obj = self.entity_cls(*args, **kwargs)

            # Perform unique checks. Raises validation errors if unique constraints are violated.
            self._validate_unique(entity_obj)

            # Build the model object and persist into data store
            model_obj = self._create(self.database_model_cls.from_entity(entity_obj))

            # Flush before reflecting so a DB-assigned Auto(increment=True) key
            # materializes under a UoW, mirroring save(). See the note there.
            if not self._is_standalone and self._has_pending_auto_field(entity_obj):
                self._flush()

            # Reflect store-generated auto-increment values back onto the entity
            self._reflect_auto_fields(entity_obj, model_obj)

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
                current_uow._add_to_identity_map(entity_obj)

            return entity_obj
        except ValidationError as exc:
            logger.error(f"Failed creating entity because of {exc}")
            raise

    def _validate_and_update_version(self, entity_obj: Any) -> int | None:
        """Compute the expected version and advance the entity's version.

        Returns the expected version that the persistence store must match
        atomically during the subsequent ``_update()`` call, or ``None``
        for new (unpersisted) entities.
        """
        expected_version: int | None = None

        if entity_obj.state_.is_persisted:
            expected_version = entity_obj._version

        # Advance to the next version — the model built from this entity
        # will carry the incremented version for the UPDATE.
        entity_obj._version = entity_obj._next_version

        return expected_version

    def save(self, entity_obj: Any) -> Any:
        """Create or update an entity in the data store, depending on its state. An identity for entity record is
        generated, if not already present.

        The primary difference between `save` and other lifecycle methods like `create` and `update` is that `save`
        accepts a fully formed entity object to persist, while the others accept attribute params to build the
        entity model from.

        Returns the created/updated entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param entity_obj: Entity object to be persisted
        """
        logger.debug(f"Saving `{self.entity_cls.__name__}` object")

        expected_version: int | None = None
        if entity_obj.element_type == DomainObjects.AGGREGATE:
            expected_version = self._validate_and_update_version(entity_obj)

        try:
            # Build the model object and create it
            if entity_obj.state_.is_persisted:
                self._update(
                    self.database_model_cls.from_entity(entity_obj),
                    expected_version=expected_version,
                )
            else:
                # Perform unique checks. Raises validation errors if unique constraints are violated.
                self._validate_unique(entity_obj)

                model_obj = self._create(
                    self.database_model_cls.from_entity(entity_obj)
                )

                # A relational adapter assigns an Auto(increment=True) key only
                # when the INSERT is flushed; under a UoW that flush is deferred
                # to commit, after add() has returned. Force it here so the value
                # materializes before we reflect it. Standalone _create has
                # already committed (and flushed), so this is UoW-only, and it is
                # skipped entirely when no auto field is pending (the common
                # client-supplied identifier).
                if not self._is_standalone and self._has_pending_auto_field(entity_obj):
                    self._flush()

                # Reflect store-generated auto-increment values back onto the
                # entity so an Auto(increment=True) field is populated after add().
                self._reflect_auto_fields(entity_obj, model_obj)

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
                # The element may have changed from the time it was loaded or may have been
                #   updated multiple times. We retain the last copy in seen.
                current_uow._add_to_identity_map(entity_obj)

            return entity_obj
        except Exception as exc:
            # Roll back the version advance so the entity stays consistent
            # with the persistence store after a failed save.
            if expected_version is not None:
                entity_obj._version = expected_version
            logger.error(f"Failed saving entity because {exc}")
            raise

    def update(self, entity_obj: Any, *data: Any, **kwargs: Any) -> "BaseEntity":
        """Update a record in the data store.

        Performs validations for unique attributes before creating the entity.

        Supports both dictionary and keyword argument updates to the entity::

            >>> user.update({'age': 10})
            >>> user.update(age=10)

        Returns the updated entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param entity_obj: The entity object to be updated
        :param data: Dictionary of values to be updated for the entity
        :param kwargs: keyword arguments of attribute pairs to be updated
        """
        logger.debug(
            f"Updating existing `{self.entity_cls.__name__}` object with id {entity_obj.id}"
        )

        try:
            # Update entity's data attributes
            entity_obj._update_data(*data, **kwargs)

            # Do unique checks
            self._validate_unique(entity_obj, create=False)

            self._update(self.database_model_cls.from_entity(entity_obj))

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
                current_uow._add_to_identity_map(entity_obj)

            updated: BaseEntity = entity_obj
            return updated
        except Exception as exc:
            logger.error(f"Failed updating entity because of {exc}")
            raise

    def _validate_unique(self, entity_obj: Any, create: bool = True) -> None:
        """Validate the unique constraints for the entity. Raise ValidationError, if constraints were violated.

        This method internally uses each field object's fail method to construct a valid error message.

        :param entity_obj: Entity object to be validated
        :param create: boolean value to indicate that the validation is part of a create operation
        """
        # Build the filters from the unique constraints
        filters, excludes = {}, {}

        # Construct filter criteria based on unique fields defined in Entity class
        for field_name, field_obj in unique_fields(self.entity_cls).items():
            lookup_value = getattr(entity_obj, field_name, None)

            # Ignore empty lookup values
            if lookup_value in (None, "", [], (), {}):
                continue

            # Ignore identifiers on updates
            if not create and field_obj.identifier:
                excludes[field_name] = lookup_value
                continue

            filters[field_name] = lookup_value

        # Lookup the objects by filters and raise error if objects exist
        for filter_key, lookup_value in filters.items():
            if self.exists(excludes, **{filter_key: lookup_value}):
                field_obj = declared_fields(self.entity_cls)[filter_key]
                field_obj.fail(
                    "unique",
                    entity_name=self.entity_cls.__name__,
                    field_name=filter_key,
                    value=lookup_value,
                )

    def delete(self, entity_obj: Any) -> Any:
        """Delete a record in the data store.

        Performs validations before data deletion.

        Returns the deleted entity object.

        Throws ObjectNotFoundError if the object was not found in the data store.

        :param entity_obj: Entity object to be deleted from data store
        """
        try:
            if not entity_obj.state_.is_destroyed:
                self._delete(self.database_model_cls.from_entity(entity_obj))

                # Set Entity status to destroyed to let everybody know the object is no longer referable
                entity_obj.state_.mark_destroyed()

            return entity_obj
        except Exception as exc:
            logger.error(f"Failed entity deletion because of {exc}")
            raise

    def delete_all(self) -> None:
        """Delete all records in this table/document in the persistent store.

        Does not perform validations before data deletion.
        Does not return confirmation of data deletion.
        """
        try:
            self._delete_all()
        except Exception as exc:
            logger.error(f"Failed deletion of all records because of {exc}")
            raise


class BaseLookup(metaclass=ABCMeta):
    """Base Lookup class to implement for each lookup

    Inspired by the lookup mechanism implemented in Django.

    Each lookup, which is simply a data comparison (like `name == 'John'`), is implemented as a subclass of this
    class, and has to implement the `as_expression()` method to provide the representation that the persistence
    store needs.

    Lookups are identified by their names, and the names are stored in the `lookup_name` class variable.
    """

    lookup_name: ClassVar[str | None] = None

    def __init__(
        self,
        source: Any,
        target: Any,
        *,
        database_model_cls: type[BaseDatabaseModel] | None = None,
    ) -> None:
        """Source is LHS and Target is RHS of a comparsion.

        For example, in the expression `name == 'John'`, `name` is source (LHS) and `'John'` is target (RHS).
        In other words, source is the key/column/attribute to be searched on, and target is the value present in the
        persistent store.

        :param source: The key/column/attribute (LHS of the comparison)
        :param target: The value to compare against (RHS of the comparison)
        :param database_model_cls: Optional database model class for adapter-specific lookups
        """
        self.source, self.target = source, target
        self.database_model_cls = database_model_cls

    def process_source(self) -> Any:
        """This is a blank implementation that simply returns the source.

        Returns `source` (LHS of the expression).

        You can override this method to manipulate the source when necessary. For example, if you are using a
        data store that cannot perform case-insensitive queries, it may be useful to always compare in lowercase.
        """
        return self.source

    def process_target(self) -> Any:
        """This is a blank implementation that simply returns the target.

        Returns `target` (RHS of the expression).

        You can override this method to manipulate the target when necessary. A good example of overriding this
        method is when you are using a data store that needs strings to be enclosed in single quotes.
        """
        return self.target

    @abstractmethod
    def as_expression(self) -> Any:
        """This methods should return the source and the target in the format required by the persistence store.

        Concrete implementation for this method varies from database to database.
        """
