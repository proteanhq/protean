"""Portable index declarations for aggregates and entities.

`Index` lets an aggregate author declare, in the domain layer, which indexes
the persistence layer should create. The portable subset (single-column,
composite, unique, sort direction, naming) is honored by every adapter.
Opt-in fields (`where` partial predicates, `include` covering columns) are
honored on supporting dialects and fall back with a warning elsewhere.

For dialect-specific DDL the framework cannot model (GIN/BRIN, expression
indexes), use :meth:`Index.from_sql` to emit verbatim DDL for a single
dialect.

See ADR-0014 for why index declarations are decorator parameters rather than
a ``class Meta`` block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from protean.exceptions import IncorrectUsageError
from protean.utils.reflection import attributes, fields

if TYPE_CHECKING:
    from protean.utils.query import Q


@dataclass(frozen=True, init=False)
class Index:
    """A portable index declaration on an aggregate or entity.

    Args:
        *fields: One or more field names, in index order. At least one is
            required.
        name: Explicit index name. When omitted, a deterministic name is
            derived from the table and fields at render time.
        unique: Whether the index enforces uniqueness.
        desc: Subset of ``fields`` to index in descending order. Every entry
            must also appear in ``fields``.
        where: A :class:`~protean.utils.query.Q` predicate for a partial
            index. Honored on PostgreSQL and SQLite; ignored with a warning
            on dialects that do not support partial indexes.
        include: Covering (non-key) columns. Honored on PostgreSQL and SQL
            Server; ignored with a warning elsewhere.

    Example:
        ```python
        from protean import Index, Q

        @domain.aggregate(indexes=[
            Index("status", "priority", desc=("priority",)),
            Index("message_id", unique=True),
            Index("status", where=Q(status__in=["pending", "failed"]),
                  name="ix_outbox_active"),
        ])
        class Outbox:
            ...
        ```
    """

    fields: tuple[str, ...]
    name: str | None = None
    unique: bool = False
    desc: tuple[str, ...] = ()
    where: Q | None = None
    include: tuple[str, ...] = ()

    def __init__(
        self,
        *fields: str,
        name: str | None = None,
        unique: bool = False,
        desc: tuple[str, ...] | list[str] = (),
        where: Q | None = None,
        include: tuple[str, ...] | list[str] = (),
    ) -> None:
        if not fields:
            raise ValueError("An Index must declare at least one field.")

        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "unique", unique)
        object.__setattr__(self, "desc", tuple(desc))
        object.__setattr__(self, "where", where)
        object.__setattr__(self, "include", tuple(include))

    @classmethod
    def from_sql(cls, dialect: str, ddl: str, name: str | None = None) -> RawIndex:
        """Escape hatch for dialect-specific DDL the framework cannot model.

        The schema generator emits the verbatim ``ddl`` only when the
        configured dialect matches ``dialect``.

        Args:
            dialect: The dialect this DDL targets (e.g. ``"postgresql"``).
            ddl: The verbatim ``CREATE INDEX`` statement.
            name: Optional name, for reporting and deduplication.

        Example:
            ```python
            Index.from_sql(
                "postgresql",
                "CREATE INDEX ix_data_gin ON outbox USING gin (data)",
            )
            ```
        """
        return RawIndex(dialect=dialect, ddl=ddl, name=name)

    def resolved_name(self, table_name: str) -> str:
        """Return the explicit name, or derive a deterministic one.

        Derived names follow ``ix_<table>_<fields>``, with a ``uq_`` prefix
        for unique indexes.
        """
        if self.name:
            return self.name
        prefix = "uq" if self.unique else "ix"
        return "_".join([prefix, table_name, *self.fields])


@dataclass(frozen=True)
class RawIndex:
    """Verbatim, dialect-specific index DDL produced by :meth:`Index.from_sql`.

    Honored only by the adapter whose dialect matches ``dialect``; every other
    adapter ignores it.
    """

    dialect: str
    ddl: str
    name: str | None = None


def validate_indexes(element_cls: type) -> None:
    """Validate the ``indexes`` declared on an element.

    Invoked by ``DomainValidator`` during ``Domain.init()`` (after reference
    resolution), so field/attribute introspection sees a fully resolved element.

    Checks, fail-fast, that:

    - ``indexes`` is a list/tuple of :class:`Index` / :class:`RawIndex`.
    - Every field referenced by an :class:`Index` (in ``fields``, ``desc``,
      and ``include``) is declared on the element.
    - Every ``desc`` entry is also present in ``fields``.

    :class:`RawIndex` entries are opaque verbatim DDL and are not introspected.
    """
    meta = getattr(element_cls, "meta_", None)
    indexes = getattr(meta, "indexes", ()) or ()

    if not isinstance(indexes, (list, tuple)):
        raise IncorrectUsageError(
            f"`indexes` on '{element_cls.__name__}' must be a list of Index "
            f"declarations, got {type(indexes).__name__}."
        )

    # Nothing to validate for the common (no-index) case. Returning early also
    # avoids forcing field/attribute resolution at registration time, before
    # string references (value objects, associations) have been resolved.
    if not indexes:
        return

    # A field reference is valid if it matches a declared field name or its
    # mapped attribute name (covering value-object / association attributes).
    known = set(fields(element_cls)) | set(attributes(element_cls))

    for index in indexes:
        if isinstance(index, RawIndex):
            continue
        if not isinstance(index, Index):
            raise IncorrectUsageError(
                f"`indexes` on '{element_cls.__name__}' must contain Index "
                f"instances, got {type(index).__name__}."
            )

        unknown = [f for f in index.fields if f not in known]
        if unknown:
            raise IncorrectUsageError(
                f"Index on '{element_cls.__name__}' references unknown "
                f"field(s) {unknown}. Declared fields: {sorted(known)}."
            )

        bad_desc = [f for f in index.desc if f not in index.fields]
        if bad_desc:
            raise IncorrectUsageError(
                f"Index on '{element_cls.__name__}' lists desc field(s) "
                f"{bad_desc} that are not in the index fields "
                f"{list(index.fields)}."
            )

        unknown_include = [f for f in index.include if f not in known]
        if unknown_include:
            raise IncorrectUsageError(
                f"Index on '{element_cls.__name__}' references unknown "
                f"include field(s) {unknown_include}."
            )
