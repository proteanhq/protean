"""QuerySet Implementation"""

import copy
import logging
import math
from collections.abc import Callable, Iterator, KeysView
from typing import TYPE_CHECKING, Any, Self

from protean._deprecation import warn_from_registry
from protean.exceptions import NotSupportedError
from protean.fields.resolved import serialize_custom_value
from protean.port.provider import DatabaseCapabilities
from protean.utils.globals import _find_uow
from protean.utils.query import Q
from protean.utils.reflection import attributes, fields, id_field

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity
    from protean.core.unit_of_work import UnitOfWork
    from protean.domain import Domain
    from protean.port.dao import BaseDAO

logger = logging.getLogger(__name__)


class QuerySet:
    """A chainable, lazy query over one aggregate's or entity's data store.

    ``filter()``, ``exclude()``, ``order_by()``, ``limit()``, ``offset()`` and
    ``only()`` each return a new QuerySet and fetch nothing. The query runs
    when you call ``all()``, which returns a ``ResultSet``, or when you call
    ``len()``, ``bool()`` or ``list()`` on the QuerySet, iterate over it, or
    slice it.

    The QuerySet keeps a non-empty result of its last run, and iterating or
    slicing again reuses it. An empty result is not kept, so the query runs
    again. When the Unit of Work transaction has changed since that run, the
    query runs again. ``all()`` always runs the query again, so
    call it to see changes made since the last run.
    """

    def __init__(
        self,
        owner_dao: "BaseDAO",
        domain: "Domain",
        entity_cls: type["BaseEntity"],
        criteria: Q | None = None,
        offset: int = 0,
        limit: int | None = None,  # No limit by default
        order_by: list[str] | str | None = None,
        only_fields: list[str] | None = None,
    ) -> None:
        """Initialize either with empty preferences (when invoked on an Entity)
        or carry forward filters and preferences when chained
        """
        self._owner_dao = owner_dao
        self._domain = domain
        self._entity_cls = entity_cls
        self._criteria = criteria or Q()
        self._result_cache: ResultSet | None = None
        # The transaction the cache was filled in, and how to fill it again.
        self._result_cache_transaction: object | None = None
        self._refill_cache: Callable[[], ResultSet] | None = None
        self._offset = offset or 0

        # Field selection set via ``only()``. ``None`` means "fetch full
        # rows and materialize entities"; a list means "fetch only these
        # attributes and return read-only ``Record`` objects". Stored as
        # attribute (column) names so adapters can consume it directly.
        self._only_fields: list[str] | None = only_fields

        # If an explicit limit is not provided, use the limit from the entity class
        self._limit = limit or entity_cls.meta_.limit

        # `order_by` could be empty, or a string or a list.
        #   Initialize empty list if `order_by` is None
        #   Convert string to list if `order_by` is a String
        #   Safe-cast list to a list if `order_by` is already a list
        self._order_by: list[str]
        if order_by:
            self._order_by = [order_by] if isinstance(order_by, str) else order_by
        else:
            self._order_by = []

    def _clone(self) -> Self:
        """
        Return a copy of the current QuerySet.
        """
        clone = self.__class__(
            self._owner_dao,
            self._domain,
            self._entity_cls,
            criteria=self._criteria,
            offset=self._offset,
            limit=self._limit,
            order_by=self._order_by,
            only_fields=self._only_fields,
        )
        return clone

    #########################
    # Query support methods #
    #########################

    def _add_q(self, q_object: Q) -> None:
        """Add a Q-object to the current filter."""
        self._criteria = self._criteria._combine(q_object, q_object.connector)

    def filter(self, *args: Any, **kwargs: Any) -> Self:
        """
        Return a new QuerySet instance with the args ANDed to the existing
        set.
        """
        return self._filter_or_exclude(False, *args, **kwargs)

    def exclude(self, *args: Any, **kwargs: Any) -> Self:
        """
        Return a new QuerySet instance with NOT (args) ANDed to the existing
        set.
        """
        return self._filter_or_exclude(True, *args, **kwargs)

    def _filter_or_exclude(self, negate: bool, *args: Any, **kwargs: Any) -> Self:
        clone = self._clone()

        # Parse kwarg keys and replace field names with referenced_as if present
        #   This way, the domain and filtering logic will always refer to a field by its field name,
        #   but the database will use the referenced_as attribute name.
        new_kwargs = {}
        for key, value in kwargs.items():
            # Extract the field name in the composite key (e.g. `name` from `name__contains`)
            extracted_key_name, _ = self._owner_dao.provider._extract_lookup(key)

            # Get the attribute name of the field
            # We want to support both field name and attribute name in the query,
            #   so we look for the key name in both fields and attributes.
            #
            # If we don't find it in either, we raise an error.
            field_obj = self._resolve_field(extracted_key_name)
            attr_name = field_obj.attribute_name
            # A field returned from a registered entity always has its
            # ``attribute_name`` populated (set during ``__set_name__``).
            assert attr_name is not None

            # Replace the field name in the composite key with the attribute name
            new_key_name = key.replace(extracted_key_name, attr_name)
            # Add the new key and value to the new kwargs. A custom field is
            # stored as whatever its ``as_dict`` returns, so a filter carrying a
            # live instance is serialized the same way; otherwise the criterion
            # compares against, or binds to the driver, an object the store never
            # saw. Plain values (a raw primitive, an ``__isnull`` flag) pass
            # through untouched, and an ``__in`` list is serialized item by item.
            new_kwargs[new_key_name] = serialize_custom_value(field_obj, value)

        if negate:
            clone._add_q(~Q(*args, **new_kwargs))
        else:
            clone._add_q(Q(*args, **new_kwargs))
        return clone

    def limit(self, limit: int | None) -> Self:
        """Limit number of records"""
        clone = self._clone()

        # Assign limit if it is an integer or None
        if isinstance(limit, int) or limit is None:
            clone._limit = limit

        return clone

    def offset(self, offset: int) -> Self:
        """Fetch results after `offset` value"""
        clone = self._clone()

        if isinstance(offset, int):
            clone._offset = offset

        return clone

    def order_by(self, order_by: list[str] | str) -> Self:
        """Update order_by setting for filter set"""
        clone = self._clone()

        if isinstance(order_by, str):
            order_by = [order_by]

        # Get the attribute name of the field
        # We want to support both field name and attribute name in the query,
        #   so we look for the key name in both fields and attributes.
        #
        # If we don't find it in either, we raise an error.
        new_order_by = []

        for key in order_by:
            # If the key starts with a minus sign, it is a descending order
            reverse = False
            if key.startswith("-"):
                reverse = True
                cleaned_key = key[1:]
            else:
                cleaned_key = key

            attr_name = self._resolve_attribute_name(cleaned_key)

            if reverse:
                new_order_by.append(f"-{attr_name}")
            else:
                new_order_by.append(attr_name)

        clone._order_by.extend(
            item for item in new_order_by if item not in clone._order_by
        )

        return clone

    def only(self, *field_names: str) -> Self:
        """Return a QuerySet that fetches only the named fields.

        The new QuerySet fetches only these columns, plus the identifier, which
        is always included. It yields read-only
        [`Record`][protean.core.queryset.Record] objects instead of domain
        entities. A ``Record`` has no behavior, runs no invariants and cannot be
        persisted, so ``update()`` and ``delete()`` raise ``NotSupportedError``
        on a QuerySet with a selection.

        Calling ``only()`` again replaces the selection. Calling it with no
        arguments clears the selection and restores full entities.

        Args:
            *field_names: Names of the persisted fields to fetch. Field names
                and attribute names both work.

        Raises:
            KeyError: A name is not a field or attribute of the entity.
            NotSupportedError: A name is not a persisted field, such as an
                association.
        """
        clone = self._clone()

        # No arguments clears the selection (last call wins).
        if not field_names:
            clone._only_fields = None
            return clone

        entity_attributes = attributes(self._entity_cls)
        resolved: list[str] = []

        def _add(name: str) -> None:
            attr_name = self._resolve_attribute_name(name)

            # Only persisted attributes (real columns) can be projected.
            # Associations and other non-persisted fields have no column to
            # fetch and would make the selection meaningless.
            if attr_name not in entity_attributes:
                raise NotSupportedError(
                    f"`.only()` cannot project '{name}' on "
                    f"{self._entity_cls.__name__}: it is not a persisted field."
                )

            if attr_name not in resolved:
                resolved.append(attr_name)

        # The identifier is always included so every Record is addressable.
        id_field_obj = id_field(self._entity_cls)
        if id_field_obj is not None:
            # A registered identity field always has its ``field_name`` populated
            # (set during ``__set_name__``); ``None`` only occurs on an unbound Field.
            assert id_field_obj.field_name is not None
            _add(id_field_obj.field_name)

        for name in field_names:
            _add(name)

        clone._only_fields = resolved
        return clone

    def _resolve_field(self, name: str) -> Any:
        """Resolve a field or attribute name to the field object behind it.

        Accepts both field names and attribute names, mirroring the lookup used
        by ``filter`` and ``order_by``.

        :raises KeyError: if ``name`` is neither a field nor an attribute.
        """
        entity_fields = fields(self._entity_cls)
        if name in entity_fields:
            return entity_fields[name]

        entity_attributes = attributes(self._entity_cls)
        if name in entity_attributes:
            return entity_attributes[name]

        raise KeyError(
            f"Key '{name}' not found in either fields or attributes "
            f"of {self._entity_cls}"
        )

    def _resolve_attribute_name(self, name: str) -> str:
        """Resolve a field or attribute name to its persisted attribute name.

        :raises KeyError: if ``name`` is neither a field nor an attribute.
        """
        attr_name: str | None = self._resolve_field(name).attribute_name

        # A field returned from a registered entity's ``fields()``/``attributes()``
        # always has its ``attribute_name`` populated (set during ``__set_name__``);
        # it is only ``None`` on an unbound Field instance, which cannot occur here.
        assert attr_name is not None
        return attr_name

    def _reject_if_projected(self, action: str) -> None:
        """Guard mutating operations against a projected query.

        Projections yield read-only ``Record`` objects rather than entities, so a
        mutation has nothing valid to act on. Raise rather than silently
        operating on the wrong type.
        """
        if self._only_fields is not None:
            raise NotSupportedError(
                f"`{action}()` cannot be combined with `only()`. Projections "
                f"yield read-only records, not entities; drop `only()` to "
                f"{action}."
            )

    def all(self, with_total: bool = True) -> "ResultSet":
        """Primary method to fetch data based on filters

        Also trigged when the QuerySet is evaluated by calling one of the following methods:
            * len()
            * bool()
            * list()
            * Iteration
            * Slicing

        When ``with_total`` is ``False`` the adapter may skip any expensive
        total-count computation (e.g. SQL's separate ``COUNT`` query); use this
        when only ``ResultSet.items`` is needed and ``ResultSet.total`` can be
        disregarded.
        """
        logger.debug(f"Query `{self.__class__.__name__}` objects with filters {self}")

        # Destroy any cached results
        self._result_cache = None

        # Call the read method of the dao
        results = self._owner_dao._filter(
            self._criteria,
            self._offset,
            self._limit,
            self._order_by,
            with_total=with_total,
            fields=self._only_fields,
        )

        if self._only_fields is not None:
            # Projection path: build inert, read-only Record objects. These are
            # not domain entities, so they are deliberately not retrieved-
            # marked, event-synced, or tracked in the Unit of Work.
            results.items = self._owner_dao.database_model_cls.to_records(
                results.items, self._only_fields
            )
            self._cache(results, lambda: self.all(with_total=with_total))
            return results

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity = self._owner_dao.database_model_cls.to_entity(item)
            entity.state_.mark_retrieved()

            # Sync event position and register in UoW identity map, or take
            # the instance the UoW already tracks
            entity = self._owner_dao._track_in_uow(entity)

            entity_items.append(entity)

        results.items = entity_items

        self._cache(results, lambda: self.all(with_total=with_total))

        return results

    def count(self) -> int:
        """Return the count of records matching the current criteria.

        Issues a single ``SELECT COUNT(*)`` (or adapter equivalent) without
        projecting columns or materializing entities. Ignores ``offset``,
        ``limit``, and ``order_by`` since they do not affect the row count.
        """
        return self._owner_dao._count(self._criteria)

    def update(self, *data: Any, apply_hooks: bool = True, **kwargs: Any) -> int:
        """Update every matching aggregate and return how many matched.

        .. deprecated:: 0.18.0
            The patch-and-persist path is deprecated and is removed in v0.20.0.
            Load the matched aggregates, invoke a behaviour method on each, and
            persist each one with ``repository.add()`` instead.

        Applies the values to each matched aggregate through
        ``BaseDAO.update()``, which takes the same ``*data``, ``apply_hooks``
        and keyword arguments. Each aggregate is saved on its own, with its own
        version check. Outside a Unit of Work, an error on one aggregate, such
        as ``ExpectedVersionError``, leaves the aggregates before it saved.

        Returns:
            The number of aggregates matched.

        Raises:
            NotSupportedError: The QuerySet has an ``only()`` selection.
        """
        self._reject_if_projected("update")

        # Warn once for the whole bulk call, then drive the silent internal path
        # (``_apply_update``) per row so a batch does not re-warn once per item.
        warn_from_registry("queryset_update", "QuerySet.update()")

        updated_item_count = 0

        items = self.all()

        for item in items:
            self._owner_dao._apply_update(
                item, *data, apply_hooks=apply_hooks, **kwargs
            )
            updated_item_count += 1

        return updated_item_count

    def raw(self, query: Any, data: Any = None) -> "ResultSet":
        """Run a raw query on the database and return the matching entities.

        The query goes to the database as it is, unchecked. Any error from the
        adapter or the database is raised unchanged. The bundled adapters
        ignore ``data``; use the provider's ``raw()`` to bind values to
        placeholders.

        ``order_by``, ``offset``, ``limit`` and any ``only()`` selection do not
        apply. The result always holds full entities, never ``Record``
        objects.

        Raises:
            NotSupportedError: The provider does not support raw queries.
        """
        provider = self._owner_dao.provider
        if not provider.has_capability(DatabaseCapabilities.RAW_QUERIES):
            raise NotSupportedError(
                f"Provider '{provider.name}' ({provider.__class__.__name__}) "
                "does not support raw queries"
            )

        logger.debug(
            f"Query `{self.__class__.__name__}` objects with raw query {query}"
        )

        # Destroy any cached results
        self._result_cache = None

        # Call the raw method of the repository
        results = self._owner_dao._raw(query, data)

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity = self._owner_dao.database_model_cls.to_entity(item)
            entity.state_.mark_retrieved()

            # Sync event position and register in UoW identity map, or take
            # the instance the UoW already tracks
            entity = self._owner_dao._track_in_uow(entity)

            entity_items.append(entity)
        results.items = entity_items

        self._cache(results, lambda: self.raw(query, data))

        return results

    def delete(self) -> int:
        """Deletes matching objects from the Repository

        Does not throw error if no objects are matched.

        Returns the number of objects matched (which may not be equal to the number of objects
            deleted if objects rows already have the new value).
        """
        self._reject_if_projected("delete")

        # Fetch Model class and connected repository from Domain
        deleted_item_count = 0

        items = self.all()

        for item in items:
            self._owner_dao.delete(item)
            deleted_item_count += 1

        return deleted_item_count

    ###############################
    # Python Magic method support #
    ###############################

    def _active_uow(self) -> "UnitOfWork | None":
        """The Unit of Work this QuerySet's DAO reads through, if any."""
        return None if self._owner_dao._is_standalone else _find_uow()

    def _cache(self, results: "ResultSet", refill: Callable[[], "ResultSet"]) -> None:
        uow = self._active_uow()
        self._result_cache = results
        self._result_cache_transaction = uow._transaction if uow else None
        self._refill_cache = refill

    @property
    def _data(self) -> "ResultSet":
        uow = self._active_uow()
        transaction = uow._transaction if uow else None
        if self._result_cache and self._result_cache_transaction is transaction:
            active_data = self._result_cache
        elif self._refill_cache is not None:
            # A cache filled in another transaction, or outside one, holds
            # what was stored then and instances this transaction does not
            # track, so the query runs again for this one. An empty or failed
            # fill runs again as the same query, because a `raw()` query is
            # not the query this QuerySet's criteria build.
            active_data = self._refill_cache()
        else:
            active_data = self.all()

        if uow is None:
            return copy.deepcopy(active_data)

        # A copy of an aggregate the Unit of Work tracks would be a second
        # instance of it in the transaction, so the tracked instance is handed
        # out in its place.
        memo: dict[int, Any] = {}
        for item in active_data.items:
            tracked = self._owner_dao._tracked_in_uow(item)
            if tracked is not None:
                memo[id(item)] = tracked
        return copy.deepcopy(active_data, memo)

    def __iter__(self) -> Any:
        """Return results on iteration"""
        return iter(self._data)

    def __len__(self) -> int:
        """Return length of results"""
        return self._data.total

    def __bool__(self) -> bool:
        """Return True if query results have items"""
        return bool(self._data)

    def __repr__(self) -> str:
        """Support friendly print of query criteria"""
        return f"<{self.__class__.__name__}: entity: {self._entity_cls}, criteria: {self._criteria.deconstruct()}, offset: {self._offset}, limit: {self._limit}, order_by: {self._order_by}>"

    def __getitem__(self, k: Any) -> Any:
        """Support slicing of results"""
        return self._data.items[k]

    def __contains__(self, k: Any) -> bool:
        """Support `in` operations"""
        return k.id in [item.id for item in self._data.items]

    #########################
    # Result properties #
    #########################

    @property
    def total(self) -> int:
        """Return the total number of records"""
        return self._data.total

    @property
    def items(self) -> list[Any]:
        """Return result values"""
        return self._data.items

    @property
    def first(self) -> Any | None:
        """Return the first result"""
        return self._data.first

    @property
    def last(self) -> Any | None:
        """Return the last result"""
        return self._data.last

    @property
    def has_next(self) -> bool:
        """Return True if more pages exist beyond the current one."""
        return self._data.has_next

    @property
    def has_prev(self) -> bool:
        """Return True if this page has items and starts after the first item (offset > 0)."""
        return self._data.has_prev

    @property
    def page(self) -> int:
        """Return the current page number"""
        return self._data.page

    @property
    def page_size(self) -> int | None:
        """Return the page size"""
        return self._data.page_size

    @property
    def total_pages(self) -> int:
        """Return the total number of pages"""
        return self._data.total_pages


class ReadOnlyQuerySet(QuerySet):
    """A QuerySet that blocks all mutation operations.

    Used by ``domain.view_for().query`` to enforce CQRS read-only access
    on projections. All read operations (filter, exclude, order_by,
    limit, offset, all, raw) work unchanged. Mutation methods raise
    ``NotSupportedError``.
    """

    def update(self, *data: Any, **kwargs: Any) -> int:
        raise NotSupportedError(
            "Updates are not allowed on a read-only query. "
            "Use domain.repository_for() if you need to mutate projections."
        )

    def delete(self) -> int:
        raise NotSupportedError(
            "Deletes are not allowed on a read-only query. "
            "Use domain.repository_for() if you need to mutate projections."
        )


class ResultSet:
    """This is an internal helper class returned by DAO query operations.

    The purpose of this class is to prevent DAO-specific data structures from leaking into the domain layer.
    It can help check whether results exist, traverse the results, fetch the total number of items and also provide
    basic pagination support.
    """

    def __init__(
        self, offset: int, limit: int | None, total: int, items: list[Any]
    ) -> None:
        # the current offset (zero indexed)
        self.offset = offset
        # the number of items to be fetched (None means unlimited)
        self.limit = limit
        # the total number of items matching the query
        self.total = total
        # the results
        self.items = items

    @property
    def has_prev(self) -> bool:
        """Is ``True`` if this page has items and starts after the first item (offset > 0)."""
        return bool(self.items) and self.offset > 0

    @property
    def has_next(self) -> bool:
        """Is ``True`` if more pages exist beyond the current one."""
        if self.limit is None:
            return False
        return (self.offset + self.limit) < self.total

    @property
    def page(self) -> int:
        """Current page number (1-indexed).

        Returns 1 when ``limit`` is ``None`` (unlimited).
        """
        if not self.limit:
            return 1
        return self.offset // self.limit + 1

    @property
    def page_size(self) -> int | None:
        """Number of items per page. Alias for ``limit``.

        Returns ``None`` when no limit is set (unlimited results).
        """
        return self.limit

    @property
    def total_pages(self) -> int:
        """Total number of pages for the full result set.

        Returns 0 when there are no results, 1 when ``limit`` is ``None``.
        """
        if self.total == 0:
            return 0
        if not self.limit:
            return 1
        return math.ceil(self.total / self.limit)

    @property
    def first(self) -> Any | None:
        """Return the first item from results."""
        if self.items:
            return self.items[0]
        return None

    @property
    def last(self) -> Any | None:
        """Return the last item from results."""
        if self.items:
            return self.items[-1]
        return None

    def __bool__(self) -> bool:
        """Returns ``True`` when the resultset is not empty."""
        return bool(self.items)

    def __iter__(self) -> Iterator[Any]:
        """Returns an iterable on items, to support traversal."""
        return iter(self.items)

    def __len__(self) -> int:
        """Returns number of items in the resultset."""
        return len(self.items)

    def __repr__(self) -> str:
        return f"<ResultSet: {len(self.items)} items>"

    def to_dict(self) -> dict[str, Any]:
        """Return the resultset as a dictionary."""
        return {
            "offset": self.offset,
            "limit": self.limit,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_prev": self.has_prev,
            "items": self.items,
        }


class Record:
    """A read-only selection of fields from a single result.

    Returned by [`QuerySet.only`][protean.core.queryset.QuerySet.only] instead of a fully materialized domain
    entity. A ``Record`` is intentionally **inert**: it is not a domain entity, it
    carries no behavior, runs no invariants, and cannot be persisted. It exists
    purely to carry a subset of column values on read-optimized paths (counts,
    cleanups, statistics) without the cost, or the validity guarantees, of a
    full entity. This keeps the domain model airtight: field selection never
    produces a partially-valid aggregate.

    Access selected values by attribute (``record.status``) or item
    (``record["status"]``). Reading a field that was not selected raises
    `AttributeError` / `KeyError` rather than returning a silent
    ``None``, so an unselected field is never mistaken for a null value.
    """

    # Records compare by value but are deliberately unhashable: they are
    # mutable-shaped data carriers, not identities, and should not be used as
    # dict keys or set members (use the entity for that).
    # ``__hash__ = None`` is the documented Python idiom for making a class
    # unhashable, but the type system models ``object.__hash__`` as
    # non-Optional, so both checkers flag the assignment. Genuine false-positive.
    __hash__ = None  # type: ignore[assignment]

    __slots__ = ("_data", "_entity_name")

    _entity_name: str
    _data: dict[str, Any]

    def __init__(self, entity_name: str, data: dict[str, Any]) -> None:
        object.__setattr__(self, "_entity_name", entity_name)
        object.__setattr__(self, "_data", dict(data))

    def __getattr__(self, name: str) -> Any:
        # ``__getattr__`` only fires when normal lookup fails, so the slots
        # (``_entity_name``, ``_data``) resolve directly and never reach here.
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(
                f"'{self._entity_name}' record has no field '{name}'. "
                f"Selected fields: {sorted(self._data)}. "
                f"Add it to .only(...) to fetch it."
            ) from None

    def __setattr__(self, name: str, value: Any) -> None:
        raise NotSupportedError("`Record` objects are read-only.")

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> KeysView[str]:
        """Return the projected field names."""
        return self._data.keys()

    def to_dict(self) -> dict[str, Any]:
        """Return the projected values as a plain dict."""
        return dict(self._data)

    # Explicit pickle/copy hooks so that read-only ``__setattr__`` does not
    # break ``copy.deepcopy`` (used when a QuerySet hands out cached results).
    def __getstate__(self) -> dict[str, Any]:
        return {"_entity_name": self._entity_name, "_data": self._data}

    def __setstate__(self, state: dict[str, Any]) -> None:
        object.__setattr__(self, "_entity_name", state["_entity_name"])
        object.__setattr__(self, "_data", state["_data"])

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Record)
            and self._entity_name == other._entity_name
            and self._data == other._data
        )

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self._data.items())
        return f"<Record {self._entity_name}({inner})>"
