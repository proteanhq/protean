"""Implementation of a dictionary based repository"""

import copy
import json
import typing
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from itertools import count
from threading import RLock
from typing import cast
from uuid import UUID

from protean.core.database_model import BaseDatabaseModel
from protean.core.index import Index
from protean.core.queryset import ResultSet
from protean.exceptions import (
    ExpectedVersionError,
    ObjectNotFoundError,
    ValidationError,
)
from protean.port.dao import BaseDAO, BaseLookup
from protean.port.provider import BaseProvider, DatabaseCapabilities, registry
from protean.utils import _fully_qualified_name, occ_trace
from protean.utils.container import Options
from protean.utils.globals import current_uow
from protean.utils.query import F, Q
from protean.utils.reflection import fields, id_field


class _ReverseCompare:
    """Helper class to reverse comparison order for descending sorts"""

    def __init__(self, value: typing.Any) -> None:
        self.value = value

    def __lt__(self, other: typing.Any) -> bool:
        if isinstance(other, _ReverseCompare):
            # Both are reverse, so flip the comparison
            return bool(self.value > other.value)
        # Comparing with non-reverse value should not happen in our context
        return bool(self.value > other)

    def __le__(self, other: typing.Any) -> bool:
        if isinstance(other, _ReverseCompare):
            return bool(self.value >= other.value)
        return bool(self.value >= other)

    def __eq__(self, other: typing.Any) -> bool:
        if isinstance(other, _ReverseCompare):
            return bool(self.value == other.value)
        return bool(self.value == other)

    def __ne__(self, other: typing.Any) -> bool:
        return not self.__eq__(other)

    def __gt__(self, other: typing.Any) -> bool:
        if isinstance(other, _ReverseCompare):
            return bool(self.value < other.value)
        return bool(self.value < other)

    def __ge__(self, other: typing.Any) -> bool:
        if isinstance(other, _ReverseCompare):
            return bool(self.value <= other.value)
        return bool(self.value <= other)

    def __repr__(self) -> str:
        return f"_ReverseCompare({self.value!r})"


class MemoryModel(BaseDatabaseModel):
    """A model for the dictionary repository"""

    @classmethod
    def _get_value(cls, item: dict[str, typing.Any], key: str) -> typing.Any:
        return item[key]

    @classmethod
    def from_entity(cls, entity: typing.Any) -> dict[str, typing.Any]:
        """Convert the entity to a dictionary record"""
        return cls._entity_to_dict(entity)


class MemorySession:
    """A copy-on-write view over the provider's in-memory store.

    On construction the session takes a private deep copy of the whole store
    (``data``); all reads and writes made through it operate on that copy, so a
    concurrent session never sees this one's uncommitted changes. The changes
    are published to the shared store only on :meth:`commit`.

    Committing is a **compare-and-set against the live store**, not a wholesale
    replacement. All writes go through :meth:`write` / :meth:`delete`, which
    mutate the session copy *and* record the change in one step, so a mutation
    can never be silently dropped by forgetting to track it. ``commit``
    re-validates the recorded optimistic-concurrency versions against the *live*
    store under the provider lock and then merges only the changed records,
    key-by-key. This is what makes the in-memory provider a faithful stand-in
    for optimistic locking: two overlapping writers of the same aggregate no
    longer both "win" (the stale one raises
    :class:`~protean.exceptions.ExpectedVersionError`), and writers touching
    *different* records no longer clobber each other on commit.
    """

    # Heterogeneous session store:
    #   ``data``           the deep-copied databases this session reads/writes
    #   ``lock``           a reentrant lock shared per provider
    #   ``counters``       auto-increment counters
    #   ``ops``            pending changeset ``(schema, identifier)`` -> "write"
    #                      | "delete"; last op per record wins
    #   ``version_checks`` ``(schema, identifier)`` -> expected ``_version`` the
    #                      live store must still hold for the commit to apply
    _db: dict[str, typing.Any]

    def __init__(
        self, provider: "MemoryProvider", new_connection: bool = False
    ) -> None:
        self._provider = provider
        self.is_active = True

        if (
            current_uow and self._provider.name in current_uow._sessions
        ) and not new_connection:
            self._db = cast(
                MemorySession, current_uow._sessions[self._provider.name]
            )._db
        else:
            lock = self._provider._locks.setdefault(self._provider.name, RLock())
            # Snapshot under the lock: ``commit`` now mutates the live store in
            # place (a per-record merge, not a wholesale replacement), so an
            # unlocked deepcopy could iterate a dict another thread's commit is
            # resizing and raise "dictionary changed size during iteration". The
            # lock is reentrant, so taking it here is safe even when the caller
            # (e.g. ``_claim``) already holds it on this thread.
            with lock:
                data = copy.deepcopy(self._provider._databases)
            self._db = {
                "data": data,
                "lock": lock,
                "counters": self._provider._counters,
                "ops": {},
                "version_checks": {},
                "created": set(),
            }

    def write(
        self,
        schema: str,
        identifier: typing.Any,
        record: typing.Any,
        is_new: bool = False,
    ) -> None:
        """Store ``record`` in the session copy and mark it for the commit merge.

        The single entry point for creating/updating a record, so a mutation of
        the session copy is always paired with the tracking ``commit`` needs.
        ``is_new=True`` marks a record this session *created* (an insert), which
        exempts it from the commit-time version check: it has no prior version in
        the live store to match, so ``None`` there is expected, not a conflict.
        """
        self._db["data"][schema][identifier] = record
        self._db["ops"][(schema, identifier)] = "write"
        if is_new:
            self._db["created"].add((schema, identifier))

    def delete(self, schema: str, identifier: typing.Any) -> None:
        """Drop ``identifier`` from the session copy and mark it for the merge."""
        self._db["data"][schema].pop(identifier, None)
        self._db["ops"][(schema, identifier)] = "delete"

    def record_version_check(
        self, schema: str, identifier: typing.Any, expected_version: int
    ) -> None:
        """Record the version the live store must still hold for a safe commit.

        Keeps the *first* expected version seen for a record (via
        ``setdefault``): if the same aggregate is updated twice in one session,
        the version the live store must match is the one it had when the session
        started, not the intermediate version produced by the first update.

        A record this session created (then updated in the same session) is
        skipped: it is not yet in the live store, so there is no prior version
        to compare against — checking would spuriously conflict on the ``None``.
        """
        if (schema, identifier) in self._db["created"]:
            return
        self._db["version_checks"].setdefault((schema, identifier), expected_version)

    def _clear_changeset(self) -> None:
        self._db["ops"].clear()
        self._db["version_checks"].clear()
        self._db["created"].clear()

    def commit(self) -> None:
        """Validate optimistic-concurrency versions and merge changes to the store.

        Runs the version checks and the merge together under the provider lock,
        so the whole compare-and-set is atomic with respect to other sessions'
        commits. A version mismatch raises :class:`ExpectedVersionError` and
        leaves the live store untouched.
        """
        with self._db["lock"]:
            live = self._provider._databases
            data = self._db["data"]
            checks = self._db["version_checks"]

            # Compare: every recorded version must still match the live store.
            for (schema, identifier), expected in checks.items():
                stored = live.get(schema, {}).get(identifier)
                stored_version = stored.get("_version") if stored is not None else None
                if stored_version != expected:
                    if occ_trace.is_active():
                        # Raw conflict observation, taken under the provider lock
                        # (the same lock the compare-and-set holds): the version
                        # this writer read as its base, and the live version that
                        # no longer matches it.
                        occ_trace.record(
                            stream=f"{schema}:{identifier}",
                            base=expected,
                            outcome="conflicted",
                            version_after=stored_version,
                        )
                    raise ExpectedVersionError(
                        f"Wrong expected version: {expected} "
                        f"(Schema: {schema}, Identifier: {identifier}, "
                        f"Version: {stored_version})"
                    )

            # Set: merge this session's changes into the live store record by
            # record, so concurrent writes to other records are preserved.
            for (schema, identifier), op in self._db["ops"].items():
                if op == "write":
                    live[schema][identifier] = data[schema][identifier]
                elif schema in live:  # op == "delete"
                    live[schema].pop(identifier, None)

            if occ_trace.is_active():
                # Every checked record merged cleanly, so this writer committed.
                # Read the stored version back from the live store after the merge
                # (raw, still under the lock), rather than assuming ``base + 1``.
                for (schema, identifier), expected in checks.items():
                    merged = live.get(schema, {}).get(identifier)
                    merged_version = (
                        merged.get("_version") if merged is not None else None
                    )
                    occ_trace.record(
                        stream=f"{schema}:{identifier}",
                        base=expected,
                        outcome="committed",
                        version_after=merged_version,
                    )

            # Clear the changeset so a repeated commit is a no-op.
            self._clear_changeset()

    def rollback(self) -> None:
        # Changes live only in this session's ``data`` copy and its pending
        # changeset until ``commit`` publishes them, so discarding the changeset
        # (never applying it) is the rollback.
        self._clear_changeset()

    def close(self) -> None:
        pass


class MemoryProvider(BaseProvider):
    """Provider class for Dict Repositories"""

    __database__ = "memory"

    @property
    def capabilities(self) -> DatabaseCapabilities:
        """Basic storage, simulated transactions, and real optimistic locking.

        ``OPTIMISTIC_LOCKING`` is a genuine guarantee here, not just for the
        sequential case: on the version-guarded write path (``repository.add``
        and the DAO's ``update()``, both through ``save()``),
        :meth:`MemorySession.commit` validates the aggregate version against the
        live store under the provider lock, so two overlapping writers of the
        same aggregate cannot both succeed — the stale one raises
        :class:`~protean.exceptions.ExpectedVersionError`. The aggregate root is
        the concurrency boundary, so independent child changes are guarded only
        through the root's version; see ``docs/reference/guarantees.md``.
        """
        return DatabaseCapabilities.IN_MEMORY

    def __init__(
        self, name: str, domain: typing.Any, conn_info: dict[str, typing.Any]
    ) -> None:
        """Initialize Provider with Connection/Adapter details"""

        # In case of `MemoryProvider`, the `database` value will always be `memory`.
        super().__init__(name, domain, conn_info)

        # Global in-memory store of dict data.
        self._databases: dict[str, dict[typing.Any, typing.Any]] = defaultdict(dict)
        # Reentrant so a method that already holds the lock (e.g. ``_claim``) can
        # call through to a standalone ``commit`` — which re-acquires it — in the
        # same thread without deadlocking.
        self._locks: dict[str, RLock] = defaultdict(RLock)
        self._counters: dict[str, count[int]] = defaultdict(count)

        # A temporary cache of already constructed model classes
        self._database_model_classes: dict[str, type[typing.Any]] = {}

    def get_session(self) -> MemorySession:
        """Return a session object

        For Dictionary Repo, a session translates to a copy of the
        `database`. All transactions on the Provider's repositories
        are committed on this copy of the database.
        """
        return MemorySession(self)

    def get_connection(self, session_cls: typing.Any = None) -> MemorySession:
        """Return the dictionary database object"""
        return MemorySession(self, new_connection=True)

    def is_alive(self) -> bool:
        """Check if the connection is alive"""
        return True

    def _data_reset(self) -> None:
        """Reset data"""
        self._databases = defaultdict(dict)
        self._locks = defaultdict(RLock)
        self._counters = defaultdict(count)

        # Discard any active Unit of Work
        if current_uow and current_uow.in_progress:
            current_uow.rollback()

    def close(self) -> None:
        """Close the provider and clean up resources.

        For MemoryProvider, this is a no-op since there are no persistent
        connections or external resources to clean up.
        """

    def decorate_database_model_class(
        self, entity_cls: type[typing.Any], database_model_cls: type[typing.Any]
    ) -> type[typing.Any]:
        cache_key = _fully_qualified_name(entity_cls)

        # Return the model class if it was already seen/decorated
        if cache_key in self._database_model_classes:
            return self._database_model_classes[cache_key]

        # If `database_model_cls` is already subclassed from MemoryModel,
        #   this method call is a no-op
        if issubclass(database_model_cls, MemoryModel):
            return database_model_cls
        else:
            custom_attrs = {
                key: value
                for (key, value) in vars(database_model_cls).items()
                if key not in ["Meta", "__module__", "__doc__", "__weakref__"]
            }

            meta_ = Options()
            meta_.part_of = entity_cls

            custom_attrs.update({"meta_": meta_})
            # User class is in the MRO; custom methods/properties resolve via standard Python MRO
            decorated_database_database_model_cls = type(
                database_model_cls.__name__,
                (MemoryModel, database_model_cls),
                custom_attrs,
            )

            # Memoize the constructed model class
            self._database_model_classes[cache_key] = (
                decorated_database_database_model_cls
            )

            return decorated_database_database_model_cls

    def construct_database_model_class(
        self, entity_cls: type[typing.Any]
    ) -> type[typing.Any]:
        """Return associated, fully-baked Model class"""
        database_model_cls = None
        cache_key = _fully_qualified_name(entity_cls)

        # Return the model class if it was already seen/decorated
        if cache_key in self._database_model_classes:
            database_model_cls = self._database_model_classes[cache_key]
        else:
            meta_ = Options()
            meta_.part_of = entity_cls

            attrs = {
                "meta_": meta_,
            }
            # Auto-generated model; no user-defined attributes to carry over
            database_model_cls = type(
                entity_cls.__name__ + "Model", (MemoryModel,), attrs
            )

            # Memoize the constructed model class
            self._database_model_classes[cache_key] = database_model_cls

        # Set Entity Class as a class level attribute for the Model, to be able to reference later.
        return database_model_cls

    def get_dao(
        self, entity_cls: type[typing.Any], database_model_cls: type[typing.Any]
    ) -> "DictDAO":
        """Return a DAO object configured with a live connection"""
        return DictDAO(self.domain, self, entity_cls, database_model_cls)

    def _evaluate_lookup(
        self,
        key: str,
        value: typing.Any,
        negated: bool,
        db: dict[typing.Any, typing.Any],
    ) -> dict[typing.Any, typing.Any]:
        """Extract values from DB that match the given criteria.

        When ``value`` is an :class:`~protean.utils.query.F`, the right-hand
        side is resolved per record to the referenced column, enabling
        column-to-column comparisons (e.g. ``retry_count < max_retries``).
        """
        results = {}
        stripped_key, base_lookup_class = self._extract_lookup(key)
        # Every lookup registered on ``MemoryProvider`` is a ``MemoryLookup``
        # (they implement ``evaluate()``); the ABC return type is the wider
        # ``type[BaseLookup]``, so narrow to the concrete memory lookup here.
        lookup_class = cast("type[MemoryLookup]", base_lookup_class)
        null_safe = getattr(lookup_class, "null_safe", False)
        target_is_column = isinstance(value, F)
        target_name = value.name if target_is_column else None
        for record_key, record_value in db.items():
            source_value = record_value[stripped_key]
            target_value = record_value[target_name] if target_is_column else value

            # A comparison against NULL on either side is UNKNOWN in SQL and
            # never matches, even when negated. ``isnull`` is the null_safe
            # exception that intentionally tests for NULL.
            if (source_value is None and not null_safe) or (
                target_is_column and target_value is None
            ):
                match = False
            else:
                result = lookup_class(source_value, target_value).evaluate()
                match = not result if negated else result

            if match:
                results[record_key] = record_value

        return results

    def _raw(self, query: typing.Any, data: typing.Any = None) -> list[typing.Any]:
        """Run raw queries on the memory database.

        As an example of running ``raw`` queries on a Dict repository, we will run the query
        on all possible schemas, and return all results.

        For this stand-in repository, the query string is a json string that contains kwargs
        criteria with straight-forward equality checks. Individual criteria are always AND-ed
        and the result is always a subset of the full repository.

        We will ignore the `data` parameter for this kind of repository.
        """
        assert isinstance(query, str)

        conn = self.get_connection()
        items = []

        for schema_name in conn._db["data"]:
            input_db = conn._db["data"][schema_name]
            try:
                # Ensures that the string contains double quotes around keys and values
                query = query.replace("'", '"')
                criteria = json.loads(query)

                for key, value in criteria.items():
                    input_db = self._evaluate_lookup(key, value, False, input_db)

                items.extend(list(input_db.values()))

            except json.JSONDecodeError as exc:
                raise Exception("Query Malformed") from exc
            except KeyError:
                # We encountered a repository where the key was not found
                pass

        return items

    def _create_database_artifacts(self) -> None:
        """Dummy placeholder. Nothing to do."""

    def _drop_database_artifacts(self) -> None:
        """Dummy placeholder. Nothing to do."""


class DictDAO(BaseDAO):
    """A repository for storing data in a dictionary"""

    def __repr__(self) -> str:
        return f"DictDAO <{self.entity_cls.__name__}>"

    def _set_auto_fields(
        self, model_obj: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Set the values of the auto field using counter"""
        conn = self._get_session()
        assert conn is not None

        for field_name, field_obj in fields(self.entity_cls).items():
            is_auto_increment = getattr(field_obj, "increment", False)
            if is_auto_increment:
                counter_key = f"{self.schema_name}_{field_name}"
                if not (field_name in model_obj and model_obj[field_name] is not None):
                    # Increment the counter and it should start from 1
                    counter = next(conn._db["counters"][counter_key])
                    if not counter:
                        counter = next(conn._db["counters"][counter_key])

                    model_obj[field_name] = counter

        return model_obj

    def _storage_key(self, field_name: str) -> str:
        """Map an index field name to the key it is stored under.

        Records are keyed by attribute name (``attribute_name`` already folds
        in ``referenced_as``), while an :class:`~protean.core.index.Index`
        declares field names. For scalar fields the two coincide; this resolves
        the difference for value-object and association attributes.
        """
        field_obj = fields(self.entity_cls).get(field_name)
        # A field bound to an entity class always has ``attribute_name``
        # populated (via ``__set_name__``); guard for the unbound ``None`` case
        # by falling back to the passed-in name.
        if field_obj is not None and field_obj.attribute_name is not None:
            return field_obj.attribute_name
        # Already an attribute name (e.g. a value-object shadow attribute).
        return field_name

    def _check_unique_indexes(
        self,
        model_obj: dict[str, typing.Any],
        records: dict[typing.Any, typing.Any],
        identifier: typing.Any,
    ) -> None:
        """Enforce declared ``Index(unique=True)`` constraints in memory.

        Relational adapters get this for free from the DDL they render; the
        in-memory store renders no DDL, so the check is replicated here to keep
        memory mode a faithful stand-in for uniqueness invariants.
        It guards the row-at-a-time write paths (``_create`` and ``_update``,
        which back ``repository.add``/``save``); the bulk paths (``_update_all``
        and ``_claim``/``update_all``, which delegate to it) are not covered,
        matching their role as low-level escape hatches.

        Partial unique indexes (``Index(..., unique=True, where=...)``) are
        advisory here and left unenforced, mirroring how the memory provider
        treats ``where`` elsewhere. NULLs are treated as distinct, matching
        PostgreSQL/SQLite semantics: a unique index over an indexed value that
        is ``None`` never collides. The
        record being written (``identifier``) is excluded so re-saving an
        unchanged row does not conflict with itself.
        """
        for index in getattr(self.entity_cls.meta_, "indexes", ()) or ():
            if not isinstance(index, Index) or not index.unique:
                continue

            # Partial (predicate) indexes are advisory in memory. Enforcing a
            # partial unique index globally would reject rows that are valid on
            # PostgreSQL/SQLite, where the `where` predicate excludes them from
            # the constraint. `where` is documented as advisory for the memory
            # provider, so skip enforcement rather than over-enforce.
            if index.where is not None:
                continue

            keys = [self._storage_key(f) for f in index.fields]
            values = [model_obj.get(k) for k in keys]

            # NULLs are distinct: skip enforcement when any indexed value is NULL.
            if any(v is None for v in values):
                continue

            for record_id, record in records.items():
                if record_id == identifier:
                    continue
                if all(record.get(k) == v for k, v in zip(keys, values, strict=False)):
                    fields_desc = ", ".join(index.fields)
                    values_desc = ", ".join(repr(v) for v in values)
                    raise ValidationError(
                        {
                            "_".join(index.fields): [
                                f"{self.entity_cls.__name__} with "
                                f"({fields_desc}) ({values_desc}) is already present."
                            ]
                        }
                    )

    def _create(self, model_obj: typing.Any) -> typing.Any:
        """Write a record to the dict repository"""
        conn = self._get_session()
        assert conn is not None

        # Update the value of the counters
        model_obj = self._set_auto_fields(model_obj)

        # Add the entity to the repository
        id_fld = id_field(self.entity_cls)
        assert id_fld is not None
        identifier = model_obj[id_fld.field_name]
        with conn._db["lock"]:
            self._check_unique_indexes(
                model_obj, conn._db["data"][self.schema_name], identifier
            )
            conn.write(self.schema_name, identifier, model_obj, is_new=True)

        self._commit_if_standalone(conn)

        return model_obj

    def _filter_items(
        self, criteria: Q, db: dict[typing.Any, typing.Any]
    ) -> dict[typing.Any, typing.Any]:
        """Recursive function to filter items from dictionary"""
        # Filter the dictionary objects based on the filters
        # ``_evaluate_lookup`` is defined on ``MemoryProvider``; ``self.provider``
        # is typed as the wider ``BaseProvider`` on the DAO, and a ``DictDAO`` is
        # only ever wired to a ``MemoryProvider``, so narrow here.
        provider = cast(MemoryProvider, self.provider)
        negated = criteria.negated
        input_db = None

        if criteria.connector == criteria.AND:
            # Trim database records over successive iterations
            #   Whatever is left at the end satisfy all criteria (AND)
            input_db = db
            for child in criteria.children:
                if isinstance(child, Q):
                    input_db = self._filter_items(child, input_db)
                else:
                    input_db = provider._evaluate_lookup(
                        child[0], child[1], negated, input_db
                    )
        else:
            # Grow database records over successive iterations
            #   Whatever is left at the end satisfy any criteria (OR)
            input_db = {}
            for child in criteria.children:
                if isinstance(child, Q):
                    results = self._filter_items(child, db)
                else:
                    results = provider._evaluate_lookup(child[0], child[1], negated, db)

                input_db = {**input_db, **results}

        return input_db

    def _filter(
        self,
        criteria: Q,
        offset: int = 0,
        limit: int = 10,
        order_by: Sequence[str] = (),
        with_total: bool = True,
        fields: list[str] | None = None,
    ) -> ResultSet:
        """Read the repository and return results as per the filter.

        ``fields`` is accepted for interface parity. The in-memory store holds
        whole records in process, so there is no per-column fetch cost to save;
        the requested subset is selected when the caller builds ``Record``
        objects via ``to_records``. Records are returned whole here.
        """
        conn = self._get_session()
        assert conn is not None

        if criteria.children:
            items = list(
                self._filter_items(
                    criteria, conn._db["data"][self.schema_name]
                ).values()
            )
        else:
            items = list(conn._db["data"][self.schema_name].values())

        # Sort the filtered results based on the order_by clause
        # Use compound sorting to match database behavior
        if order_by:

            def compound_sort_key(
                item: dict[str, typing.Any],
            ) -> tuple[typing.Any, ...]:
                """Create a compound sort key that matches database ORDER BY behavior"""
                key_parts: list[tuple[typing.Any, ...]] = []

                for o_key in order_by:
                    is_desc = o_key.startswith("-")
                    field_name = o_key[1:] if is_desc else o_key
                    value = item.get(field_name)

                    # Handle nulls consistently:
                    # - In ASC order: nulls come last
                    # - In DESC order: nulls come first
                    # We use tuples where the first element determines null vs non-null precedence
                    if value is None:
                        if is_desc:
                            # DESC: nulls should come first (smallest sort key)
                            key_parts.append((0,))
                        else:
                            # ASC: nulls should come last (largest sort key)
                            key_parts.append((2,))
                    else:
                        # Non-null values get precedence 1
                        if is_desc:
                            # For DESC order, negate numeric values or reverse string comparison
                            if isinstance(value, (int, float)):
                                key_parts.append((1, -value))
                            else:
                                # For non-numeric values (strings, dates, etc.), use reverse comparison
                                # We'll wrap in a special class that reverses all comparisons
                                key_parts.append((1, _ReverseCompare(value)))
                        else:
                            # For ASC order, use value directly
                            key_parts.append((1, value))

                return tuple(key_parts)

            items = sorted(items, key=compound_sort_key)

        # Apply offset always; when no limit is set, return the rest of the page
        returned = items[offset : offset + limit] if limit else items[offset:]
        result = ResultSet(
            offset=offset,
            limit=limit,
            total=len(items) if with_total else len(returned),
            items=returned,
        )

        return result

    def _update(
        self, model_obj: typing.Any, expected_version: int | None = None
    ) -> typing.Any:
        """Update the entity record in the dictionary.

        When ``expected_version`` is set, the version check and write happen
        atomically under the database lock.
        """
        conn = self._get_session()
        assert conn is not None

        id_fld = id_field(self.entity_cls)
        assert id_fld is not None
        identifier = model_obj[id_fld.field_name]
        with conn._db["lock"]:
            # Check if object is present
            if identifier not in conn._db["data"][self.schema_name]:
                raise ObjectNotFoundError(
                    f"`{self.__class__.__name__}` object with identifier {identifier} "
                    f"does not exist."
                )

            # Version check against this session's snapshot. This catches a
            # stale write early (the common sequential case, where the snapshot
            # already reflects a newer committed version). The authoritative
            # check for the *concurrent* case runs again against the live store
            # in ``MemorySession.commit`` — two writers that both pass here
            # against their own snapshots are reconciled there, so the stale one
            # still raises rather than silently losing its update.
            if expected_version is not None:
                stored = conn._db["data"][self.schema_name][identifier]
                stored_version = stored.get("_version")
                if stored_version != expected_version:
                    raise ExpectedVersionError(
                        f"Wrong expected version: {expected_version} "
                        f"(Aggregate: {self.entity_cls.__name__}({identifier}), "
                        f"Version: {stored_version})"
                    )
                conn.record_version_check(
                    self.schema_name, identifier, expected_version
                )

            # Reject updates that would collide with another row on a declared
            # unique index, mirroring the relational adapters' DDL enforcement.
            self._check_unique_indexes(
                model_obj, conn._db["data"][self.schema_name], identifier
            )

            conn.write(self.schema_name, identifier, model_obj)

        self._commit_if_standalone(conn)

        return model_obj

    def _update_all(self, criteria: Q, *args: typing.Any, **kwargs: typing.Any) -> int:
        """Update all objects satisfying the criteria"""
        conn = self._get_session()
        assert conn is not None

        items = self._filter_items(criteria, conn._db["data"][self.schema_name])

        update_count = 0
        for key in items:
            item = items[key]
            item.update(*args)
            item.update(kwargs)
            conn.write(self.schema_name, key, item)

            update_count += 1

        self._commit_if_standalone(conn)

        return update_count

    def _claim(
        self,
        criteria: Q,
        claim_fields: dict[str, typing.Any],
        limit: int,
        order_by: str | None = None,
    ) -> list[typing.Any]:
        """Atomic find-and-claim for the in-memory adapter.

        The memory adapter has no row-level locking, and its ``_update_all`` is
        not atomic across threads (it reads-then-writes). Holding the provider's
        lock across the whole read-and-claim section serializes concurrent
        claimers in-process, which is the strongest guarantee the single-process
        memory store can offer. With the lock held, the portable
        :meth:`BaseDAO._claim` default is race-free.

        The lock is a reentrant ``RLock``: ``_update_all`` commits standalone,
        and :meth:`MemorySession.commit` re-acquires the same lock on this
        thread to run its compare-and-set, so it must nest without deadlocking.
        """
        conn = self._get_session()
        assert conn is not None
        with conn._db["lock"]:
            return super()._claim(criteria, claim_fields, limit, order_by)

    def _delete(self, model_obj: typing.Any) -> typing.Any:
        """Delete the entity record in the dictionary"""
        conn = self._get_session()
        assert conn is not None

        id_fld = id_field(self.entity_cls)
        assert id_fld is not None
        identifier = model_obj[id_fld.field_name]
        with conn._db["lock"]:
            # Check if object is present
            if identifier not in conn._db["data"][self.schema_name]:
                raise ObjectNotFoundError(
                    f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                    f"does not exist."
                )

            conn.delete(self.schema_name, identifier)

        self._commit_if_standalone(conn)

        return model_obj

    def _count(self, criteria: Q) -> int:
        """Count items matching ``criteria`` without materializing entities."""
        conn = self._get_session()
        assert conn is not None

        records = conn._db["data"].get(self.schema_name, {})
        if criteria.children:
            return len(self._filter_items(criteria, records))
        return len(records)

    def _delete_top(
        self,
        criteria: Q,
        limit: int,
        order_by: str | None = None,
    ) -> int:
        """Bounded delete for the in-memory adapter.

        Holds the provider lock across the match-and-delete so a concurrent
        writer cannot remove or insert rows between selecting the batch and
        deleting it, mirroring :meth:`_claim`'s serialization guarantee.
        """
        if limit <= 0:
            return 0

        conn = self._get_session()
        assert conn is not None

        with conn._db["lock"]:
            records = conn._db["data"].get(self.schema_name, {})
            # No copy when there is no criteria: we only read keys/values here
            # and delete from the live store below, all under the lock.
            matched = (
                self._filter_items(criteria, records) if criteria.children else records
            )

            keys = list(matched.keys())
            if order_by:
                field_name = order_by.lstrip("-")
                keys.sort(
                    key=lambda k: matched[k].get(field_name),
                    reverse=order_by.startswith("-"),
                )

            to_delete = keys[:limit]
            for identifier in to_delete:
                conn.delete(self.schema_name, identifier)

        self._commit_if_standalone(conn)

        return len(to_delete)

    def _delete_all(self, criteria: Q | None = None) -> int:
        """Delete the dictionary object by its criteria"""
        conn = self._get_session()
        assert conn is not None
        items: dict[typing.Any, typing.Any] | list[typing.Any] = []

        if criteria:
            # Delete the object from the dictionary and return the deletion count
            items = self._filter_items(criteria, conn._db["data"][self.schema_name])

            # Delete all the matching identifiers
            with conn._db["lock"]:
                for identifier in items:
                    conn.delete(self.schema_name, identifier)
        else:
            # Delete every record one at a time (rather than dropping the whole
            # schema) so the commit merge removes exactly what this session saw
            # and does not clobber records another session inserted concurrently.
            with conn._db["lock"]:
                items = list(conn._db["data"].get(self.schema_name, {}))
                for identifier in items:
                    conn.delete(self.schema_name, identifier)

        self._commit_if_standalone(conn)

        return len(items)

    def _raw(self, query: typing.Any, data: typing.Any = None) -> ResultSet:
        """Run raw query on Repository.

        For this stand-in repository, the query string is a json string that contains kwargs
        criteria with straight-forward equality checks. Individual criteria are always AND-ed
        and the result is always a subset of the full repository.

        We will ignore the `data` parameter for this kind of repository.
        """
        items = self.provider._raw(query, data)
        return ResultSet(offset=1, limit=len(items), total=len(items), items=items)

    def has_table(self) -> bool:
        """Always returns True for MemoryProvider as it is always available"""
        return True


class MemoryLookup(BaseLookup):
    """Base class for Memory provider lookups.

    Subclasses implement ``evaluate()`` which returns a boolean result
    by comparing ``self.source`` (stored value) against ``self.target``
    (filter value) directly — no string construction or eval().
    """

    def _coerce(self, value: typing.Any) -> typing.Any:
        """Coerce UUID/datetime/date to str for comparison."""
        if isinstance(value, (UUID, datetime, date)):
            return str(value)
        return value

    def as_expression(self) -> str:
        """Satisfy BaseLookup ABC — not used by Memory provider."""
        return ""

    def evaluate(self) -> bool:
        """Evaluate the lookup comparison. Override in subclasses."""
        raise NotImplementedError


@MemoryProvider.register_lookup
class Exact(MemoryLookup):
    """Exact Match Query"""

    lookup_name = "exact"

    def evaluate(self) -> bool:
        return bool(self._coerce(self.source) == self._coerce(self.target))


@MemoryProvider.register_lookup
class IExact(MemoryLookup):
    """Case-Insensitive Exact Match Query"""

    lookup_name = "iexact"

    def evaluate(self) -> bool:
        return str(self.source).lower() == str(self.target).lower()


@MemoryProvider.register_lookup
class Contains(MemoryLookup):
    """Contains Query"""

    lookup_name = "contains"

    def evaluate(self) -> bool:
        return self._coerce(self.target) in self._coerce(self.source)


@MemoryProvider.register_lookup
class IContains(MemoryLookup):
    """Case-Insensitive Contains Query"""

    lookup_name = "icontains"

    def evaluate(self) -> bool:
        return str(self.target).lower() in str(self.source).lower()


@MemoryProvider.register_lookup
class Startswith(MemoryLookup):
    """Startswith Query"""

    lookup_name = "startswith"

    def evaluate(self) -> bool:
        return str(self._coerce(self.source)).startswith(str(self._coerce(self.target)))


@MemoryProvider.register_lookup
class Endswith(MemoryLookup):
    """Endswith Query"""

    lookup_name = "endswith"

    def evaluate(self) -> bool:
        return str(self._coerce(self.source)).endswith(str(self._coerce(self.target)))


@MemoryProvider.register_lookup
class GreaterThan(MemoryLookup):
    """Greater than Query"""

    lookup_name = "gt"

    def evaluate(self) -> bool:
        return bool(self._coerce(self.source) > self._coerce(self.target))


@MemoryProvider.register_lookup
class GreaterThanOrEqual(MemoryLookup):
    """Greater than or Equal Query"""

    lookup_name = "gte"

    def evaluate(self) -> bool:
        return bool(self._coerce(self.source) >= self._coerce(self.target))


@MemoryProvider.register_lookup
class LessThan(MemoryLookup):
    """Less than Query"""

    lookup_name = "lt"

    def evaluate(self) -> bool:
        return bool(self._coerce(self.source) < self._coerce(self.target))


@MemoryProvider.register_lookup
class LessThanOrEqual(MemoryLookup):
    """Less than or Equal Query"""

    lookup_name = "lte"

    def evaluate(self) -> bool:
        return bool(self._coerce(self.source) <= self._coerce(self.target))


@MemoryProvider.register_lookup
class In(MemoryLookup):
    """In Query"""

    lookup_name = "in"

    def evaluate(self) -> bool:
        target = (
            self.target if isinstance(self.target, (list, tuple)) else [self.target]
        )
        return self._coerce(self.source) in [self._coerce(t) for t in target]


@MemoryProvider.register_lookup
class Any(MemoryLookup):
    """Any Query for Lists"""

    lookup_name = "any"

    def evaluate(self) -> bool:
        source = (
            self.source if isinstance(self.source, (list, tuple)) else [self.source]
        )
        target = (
            self.target if isinstance(self.target, (list, tuple)) else [self.target]
        )
        # A list (not a set) is intentional: list elements such as dicts (from
        # ``List(content_type=dict)`` or serialized value objects) are not
        # hashable, so membership must use equality, not hashing.
        coerced_target = [self._coerce(t) for t in target]
        return any(self._coerce(x) in coerced_target for x in source)


@MemoryProvider.register_lookup
class Overlap(Any):
    """Array overlap query.

    Matches when the source list shares at least one element with the target
    list. For the in-memory store this is the same equality-based membership
    test as :class:`Any` (which compares elements by equality, not hashing, so
    unhashable items such as dicts are supported); the distinct name keeps
    parity with the SQLAlchemy adapter, where ``overlap`` maps to the native
    array ``&&`` operator.
    """

    lookup_name = "overlap"


@MemoryProvider.register_lookup
class IsNull(MemoryLookup):
    """IS NULL / IS NOT NULL Query.

    ``Q(field__isnull=True)`` matches rows where ``field`` is ``None``;
    ``Q(field__isnull=False)`` matches rows where ``field`` is not ``None``.
    """

    lookup_name = "isnull"
    null_safe = True

    def evaluate(self) -> bool:
        return self.source is None if self.target else self.source is not None


def register() -> None:
    """Register MemoryProvider with Protean.

    MemoryProvider is always available as it has no external dependencies.
    """
    registry.register("memory", "protean.adapters.repository.memory.MemoryProvider")
