"""The Alembic options the migration runner passes to ``context.configure``.

Autogenerate compares the provider's ``MetaData`` with the database. These
options keep that comparison to the tables the provider owns, in the schema it
owns, and add the raw indexes autogenerate cannot see. ``differences`` runs
the same comparison for ``protean db check`` and reports it as text.
"""

from __future__ import annotations

import contextlib
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from alembic.autogenerate import compare_metadata
from alembic.operations import ops
from sqlalchemy import (
    Column,
    Computed,
    Constraint,
    DefaultClause,
    Index,
    MetaData,
    Table,
    inspect,
    text,
)
from sqlalchemy.exc import SAWarning
from sqlalchemy.sql import ClauseElement

from protean.adapters.repository.sqlalchemy import _raw_indexes_of
from protean.core.index import RawIndex
from protean.exceptions import ConfigurationError

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
        self.schema = _compared_schema(metadata, connection)
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
            # without this autogenerate would drop it. Only its DDL names an
            # unnamed raw index, so a table that declares one drops no index.
            raw = _raw_indexes(_table(self.metadata, obj.table.name))
            if any(not index.name for index in raw):
                return False
            return name not in {index.name for index in raw}
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


def _compared_schema(metadata: MetaData, connection: Connection | None) -> str | None:
    """The schema of ``metadata`` as reflection names it on ``connection``."""
    default_schema = connection.dialect.default_schema_name if connection else None
    # Reflection reports the default schema as None, so the provider's schema
    # is compared as None when it is the default one.
    return None if metadata.schema == default_schema else metadata.schema


def differences(context: Any, metadata: MetaData) -> list[str]:
    """The differences between the database and ``metadata``, one line each.

    ``context`` is Alembic's environment context, configured online with
    ``configure_options``. Each line is the operation, then the table, then
    ``.<column>`` or ``.<index or constraint name>`` where there is one, such
    as ``add_column order.discount``. The lines are sorted. The comparison
    drops the same differences ``migrate`` drops, and reports a named raw
    index an existing table lacks as ``add_index``. Nothing is written to the
    database.

    Raises:
        ConfigurationError: The database is not at the latest revision of the
            migrations folder.
    """
    migration_context = context.get_context()
    if set(migration_context.get_current_heads()) != set(context.script.get_heads()):
        raise ConfigurationError(
            "The database is not at the latest migration, so it cannot be "
            "compared with the table definitions. Run `protean db upgrade` "
            "first."
        )

    return _compare(migration_context, metadata)


def _compare(migration_context: MigrationContext, metadata: MetaData) -> list[str]:
    """The sorted lines of ``differences``, without the check on the heads."""
    connection = migration_context.connection
    assert connection is not None
    diffs = _flatten(compare_metadata(migration_context, metadata))
    lines = [
        _diff_line(diff)
        for diff in diffs
        if not _changes_primary_key_nullability(metadata, diff)
    ]
    schema = _compared_schema(metadata, connection)
    lines += [
        f"add_index {table.name}.{name}"
        for table, name, _ in _missing_raw_indexes(connection, metadata, schema, set())
    ]
    return sorted(lines)


def _flatten(diffs: list[Any]) -> list[tuple[Any, ...]]:
    """``diffs`` with each list of column changes replaced by its changes."""
    flat: list[tuple[Any, ...]] = []
    for diff in diffs:
        flat += diff if isinstance(diff, list) else [diff]
    return flat


def _changes_primary_key_nullability(metadata: MetaData, diff: tuple[Any, ...]) -> bool:
    # ``("modify_nullable", schema, table, column, kw, existing, new)``
    return diff[0] == "modify_nullable" and _is_primary_key_column(
        metadata, diff[2], diff[3]
    )


def _diff_line(diff: tuple[Any, ...]) -> str:
    """``diff``, one entry of ``compare_metadata``, as ``<operation> <table>[.<name>]``."""
    operation, subject = diff[0], diff[1]
    if isinstance(subject, Table):
        return f"{operation} {subject.name}"
    if isinstance(subject, (Index, Constraint)):
        table = subject.table
        assert table is not None
        # An unnamed constraint has a placeholder name that is not a string.
        if not isinstance(subject.name, str):
            return f"{operation} {table.name}"
        return f"{operation} {table.name}.{subject.name}"
    # A column change: ``(operation, schema, table, column, ...)``, where the
    # column is a ``Column`` or, in a ``modify_*`` change, its name.
    table, column = diff[2], diff[3]
    return f"{operation} {table}.{column if isinstance(column, str) else column.name}"


def _table(metadata: MetaData, name: str) -> Table | None:
    for table in metadata.tables.values():
        if table.name == name:
            return table
    return None


def _raw_indexes(table: Table | None) -> list[RawIndex]:
    return [] if table is None else _raw_indexes_of(table)


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
    return _is_primary_key_column(metadata, op.table_name, op.column_name)


def _is_primary_key_column(metadata: MetaData, table_name: str, column: str) -> bool:
    table = _table(metadata, table_name)
    return table is not None and column in table.primary_key.columns


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
                _execute_sql(raw.ddl)
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
        rebuilt += [_drop_if_exists(connection, name, schema), _execute_sql(sql)]
    return rebuilt


def _execute_sql(sql: str) -> ops.ExecuteSQLOp:
    """An op that runs ``sql`` verbatim."""
    # Alembic runs a string through ``text()``, which reads a colon before a
    # word as a bind parameter, even inside a quoted literal. ``text()`` turns
    # each escaped colon back into a plain one.
    return ops.ExecuteSQLOp(sql.replace(":", r"\:"))


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
        (raw.name, _execute_sql(raw.ddl)) for raw in _raw_indexes(table) if raw.name
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
    for table, name, ddl in _missing_raw_indexes(connection, metadata, schema, created):
        script.upgrade_ops.ops.append(_execute_sql(ddl))
        script.downgrade_ops.ops.insert(
            0, ops.DropIndexOp(name, table.name, schema=table.schema)
        )


def _missing_raw_indexes(
    connection: Connection, metadata: MetaData, schema: str | None, created: set[str]
) -> list[tuple[Table, str, str]]:
    """The table, name and DDL of each named raw index an existing table lacks.

    A table exists when the database has it and its name is not in
    ``created``. A raw index is lacking when the table has no index of its name.
    """
    existing = set(inspect(connection).get_table_names(schema=schema)) - created
    missing: list[tuple[Table, str, str]] = []
    for table in metadata.tables.values():
        if table.name not in existing:
            continue
        present = _index_names(connection, table.name, schema)
        missing += [
            (table, raw.name, raw.ddl)
            for raw in _raw_indexes(table)
            if raw.name and raw.name not in present
        ]
    return missing


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
