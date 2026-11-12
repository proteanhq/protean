"""The Alembic options the migration runner passes to ``context.configure``.

Autogenerate compares the provider's ``MetaData`` with the database. These
options keep that comparison to the tables the provider owns, in the schema it
owns, and add the raw indexes autogenerate cannot see.
"""

from __future__ import annotations

import contextlib
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from alembic.operations import ops
from sqlalchemy import Column, Computed, DefaultClause, MetaData, Table, inspect, text
from sqlalchemy.exc import SAWarning
from sqlalchemy.sql import ClauseElement

from protean.adapters.repository.sqlalchemy import _raw_indexes_of
from protean.core.index import RawIndex

if TYPE_CHECKING:
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy.engine import Connection


def configure_options(
    metadata: MetaData, dialect_name: str, connection: Connection | None
) -> dict[str, Any]:
    """The keyword arguments for ``context.configure``, online or offline.

    ``connection`` is None in offline mode, where nothing is compared.
    """
    comparison = _Comparison(metadata, connection)
    return {
        "target_metadata": metadata,
        "compare_type": True,
        # SQLite alters most columns only by copying the table.
        "render_as_batch": dialect_name == "sqlite",
        "version_table_schema": metadata.schema,
        "include_schemas": True,
        "include_name": comparison.include_name,
        "include_object": comparison.include_object,
        "process_revision_directives": comparison.process_revision_directives,
    }


class _Comparison:
    """The autogenerate hooks for one provider's ``MetaData``."""

    def __init__(self, metadata: MetaData, connection: Connection | None) -> None:
        self.metadata = metadata
        default_schema = connection.dialect.default_schema_name if connection else None
        # Reflection reports the default schema as None, so the provider's
        # schema is compared as None when it is the default one.
        self.schema = None if metadata.schema == default_schema else metadata.schema
        self.known_tables = {table.name for table in metadata.tables.values()}

    def include_name(self, name: str | None, type_: str, parent_names: Any) -> bool:
        if type_ == "schema":
            return name == self.schema
        if type_ == "table":
            # A table the provider does not own is never compared, and so never
            # dropped. ``alembic_version`` is one of them.
            return name in self.known_tables
        return True

    def include_object(
        self, obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
    ) -> bool:
        if type_ == "index" and reflected and compare_to is None:
            # A raw index is in the database and not in ``Table.indexes``, so
            # without this autogenerate would drop it.
            return name not in _raw_index_names(self.metadata, obj.table.name)
        if type_ == "unique_constraint" and not reflected:
            # The identifier field is marked unique as well as primary, and the
            # primary key already makes it unique in the database.
            return not _is_primary_key(obj)
        return True

    def process_revision_directives(
        self, context: MigrationContext, revision: Any, directives: list[Any]
    ) -> None:
        script = directives[0]
        if script.upgrade_ops is None:
            return
        _drop_primary_key_nullability(self.metadata, script.upgrade_ops)
        _drop_primary_key_nullability(self.metadata, script.downgrade_ops)
        if context.dialect.name == "sqlite":
            _rebuild_indexes_after_copy(context, self.metadata, self.schema, script)
        created = _add_raw_indexes_to_new_tables(self.metadata, script.upgrade_ops.ops)
        _add_missing_raw_indexes(context, self.metadata, self.schema, script, created)
        # An empty migration adds a step to the history that does nothing.
        if script.upgrade_ops.is_empty():
            directives[:] = []


def _table(metadata: MetaData, name: str) -> Table | None:
    for table in metadata.tables.values():
        if table.name == name:
            return table
    return None


def _raw_indexes(table: Table | None) -> list[RawIndex]:
    return [] if table is None else _raw_indexes_of(table)


def _raw_index_names(metadata: MetaData, table_name: str) -> set[str]:
    return {raw.name for raw in _raw_indexes(_table(metadata, table_name)) if raw.name}


def _is_primary_key(constraint: Any) -> bool:
    primary = {column.name for column in constraint.table.primary_key.columns}
    return bool(primary) and {column.name for column in constraint.columns} == primary


def _drop_primary_key_nullability(metadata: MetaData, container: Any) -> None:
    """Remove the nullability changes autogenerate finds on primary key columns.

    Protean declares an identifier column nullable. PostgreSQL, MySQL and SQL
    Server store a primary key column as NOT NULL, so on them the model and the
    database differ there and the difference means nothing. An op left with no
    change, and a table left with no op, are removed.
    """
    if container is None:
        return
    kept: list[Any] = []
    for op in container.ops:
        if isinstance(op, ops.ModifyTableOps):
            _drop_primary_key_nullability(metadata, op)
            if op.ops:
                kept.append(op)
        elif isinstance(op, ops.AlterColumnOp) and _alters_primary_key(metadata, op):
            op.modify_nullable = None
            op.kw.pop("autoincrement", None)
            if op.has_changes():
                kept.append(op)
        else:
            kept.append(op)
    container.ops = kept


def _alters_primary_key(metadata: MetaData, op: ops.AlterColumnOp) -> bool:
    table = _table(metadata, op.table_name)
    return table is not None and op.column_name in table.primary_key.columns


def _add_raw_indexes_to_new_tables(metadata: MetaData, upgrade: list[Any]) -> set[str]:
    """Put every raw index of a table right after the op that creates it.

    Returns the names of the tables the migration creates.
    """
    created: set[str] = set()
    for position in range(len(upgrade) - 1, -1, -1):
        op = upgrade[position]
        if isinstance(op, ops.CreateTableOp):
            created.add(op.table_name)
            sql = [
                ops.ExecuteSQLOp(raw.ddl)
                for raw in _raw_indexes(_table(metadata, op.table_name))
            ]
            upgrade[position + 1 : position + 1] = sql
    return created


def _rebuild_indexes_after_copy(
    context: MigrationContext, metadata: MetaData, schema: str | None, script: Any
) -> None:
    """Rebuild the indexes a SQLite table copy drops or changes, in ``script``.

    Alembic's batch mode copies a SQLite table from reflection, and reflection
    leaves out expression indexes and the sort order of an index column. After
    each op that copies a table in the upgrade, each index the database holds
    before the migration is dropped and created again from the model when it
    is a named raw index or a declared index with an expression, such as a DESC
    column. After each op that copies a table in the downgrade, each index the
    database holds before the migration is dropped and created again from the
    statement SQLite stored for it, so the downgrade restores the old
    definition of an index the migration changes.
    """
    connection = context.connection
    assert connection is not None
    for container, rebuild in (
        (script.upgrade_ops, _index_rebuild),
        (script.downgrade_ops, _stored_index_rebuild),
    ):
        for position in range(len(container.ops) - 1, -1, -1):
            op = container.ops[position]
            if isinstance(op, ops.ModifyTableOps) and _copies_table(op):
                rebuilt = rebuild(connection, metadata, schema, op.table_name)
                container.ops[position + 1 : position + 1] = rebuilt


def _index_rebuild(
    connection: Connection, metadata: MetaData, schema: str | None, table_name: str
) -> list[Any]:
    """The ops that drop and create again each index a copy of the table loses.

    Only the indexes the database holds are rebuilt. The others are created by
    the migration's own ops.
    """
    table = _table(metadata, table_name)
    assert table is not None
    present = _index_names(connection, table_name, schema)
    rebuilt: list[Any] = []
    for name, create in _lossy_indexes(table):
        if name in present:
            # The copy keeps an index it can reflect, in its reflected form.
            rebuilt += [_drop_if_exists(connection, name, schema), create]
    return rebuilt


def _stored_index_rebuild(
    connection: Connection, metadata: MetaData, schema: str | None, table_name: str
) -> list[Any]:
    """The ops that drop and create again each index the database holds now.

    Each index is created from its statement in ``sqlite_master``. An index
    SQLite creates for a constraint has no statement, and the copy keeps it.
    """
    rebuilt: list[Any] = []
    for name, sql in _stored_index_sql(connection, table_name, schema):
        rebuilt += [_drop_if_exists(connection, name, schema), ops.ExecuteSQLOp(sql)]
    return rebuilt


def _drop_if_exists(
    connection: Connection, name: str, schema: str | None
) -> ops.ExecuteSQLOp:
    return ops.ExecuteSQLOp(
        f"DROP INDEX IF EXISTS {_qualified(connection, name, schema)}"
    )


def _qualified(connection: Connection, name: str, schema: str | None) -> str:
    preparer = connection.dialect.identifier_preparer
    quoted = preparer.quote(name)
    return quoted if schema is None else f"{preparer.quote_schema(schema)}.{quoted}"


def _copies_table(op: ops.ModifyTableOps) -> bool:
    """Whether Alembic copies the SQLite table to apply ``op``.

    The same rule as Alembic's ``SQLiteImpl.requires_recreate_in_batch``: only
    a plain added column and an index change run without a copy.
    """
    for child in op.ops:
        if isinstance(child, ops.AddColumnOp):
            default = child.column.server_default
            if isinstance(default, DefaultClause) and isinstance(
                default.arg, ClauseElement
            ):
                return True
            if isinstance(default, Computed) and default.persisted:
                return True
        elif not isinstance(child, (ops.CreateIndexOp, ops.DropIndexOp)):
            return True
    return False


def _lossy_indexes(table: Table) -> list[tuple[str, Any]]:
    """The named indexes of ``table`` a SQLite copy loses, with the op creating each."""
    lossy: list[tuple[str, Any]] = [
        (index.name, ops.CreateIndexOp.from_index(index))
        for index in sorted(table.indexes, key=lambda index: str(index.name))
        if index.name
        and not all(isinstance(column, Column) for column in index.expressions)
    ]
    lossy += [
        (raw.name, ops.ExecuteSQLOp(raw.ddl)) for raw in _raw_indexes(table) if raw.name
    ]
    return lossy


def _add_missing_raw_indexes(
    context: MigrationContext,
    metadata: MetaData,
    schema: str | None,
    script: Any,
    created: set[str],
) -> None:
    """Add the named raw indexes that existing tables lack to ``script``.

    A table exists when the database has it and the migration does not create
    it. Each named raw index the database has no index of that name for is
    created in the upgrade and dropped in the downgrade.
    """
    connection = context.connection
    assert connection is not None
    existing = set(inspect(connection).get_table_names(schema=schema)) - created
    for table in metadata.tables.values():
        if table.name not in existing:
            continue
        present = _index_names(connection, table.name, schema)
        for raw in _raw_indexes(table):
            if raw.name and raw.name not in present:
                script.upgrade_ops.ops.append(ops.ExecuteSQLOp(raw.ddl))
                script.downgrade_ops.ops.insert(
                    0, ops.DropIndexOp(raw.name, table.name, schema=table.schema)
                )


def _index_names(
    connection: Connection, table_name: str, schema: str | None
) -> set[str]:
    """The names of every index on a table, expression indexes included."""
    if connection.dialect.name == "sqlite":
        # SQLAlchemy's SQLite reflection leaves expression indexes out.
        return {name for name, _ in _sqlite_indexes(connection, table_name, schema)}
    return {
        index["name"]
        for index in inspect(connection).get_indexes(table_name, schema=schema)
        if index["name"]
    }


def _stored_index_sql(
    connection: Connection, table_name: str, schema: str | None
) -> list[tuple[str, str]]:
    """The name and ``CREATE INDEX`` statement of each SQLite index with one."""
    return sorted(
        (name, sql)
        for name, sql in _sqlite_indexes(connection, table_name, schema)
        if sql is not None
    )


def _sqlite_indexes(
    connection: Connection, table_name: str, schema: str | None
) -> list[tuple[str, str | None]]:
    master = "sqlite_master"
    if schema is not None:
        quoted = connection.dialect.identifier_preparer.quote_schema(schema)
        master = f"{quoted}.sqlite_master"
    rows = connection.execute(
        text(f"SELECT name, sql FROM {master} WHERE type = 'index' AND tbl_name = :t"),
        {"t": table_name},
    )
    return [(row[0], row[1]) for row in rows]


@contextlib.contextmanager
def expression_index_warnings_hidden() -> Iterator[None]:
    """Hide SQLAlchemy's warning that it skipped an expression index.

    Reflection skips the expression indexes of some databases. Protean declares
    them only as raw indexes, which the runner checks by name.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Skipped unsupported reflection of expression-based index",
            category=SAWarning,
        )
        yield
