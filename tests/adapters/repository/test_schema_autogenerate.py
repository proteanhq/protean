"""Tests for the helpers that adjust what Alembic autogenerate writes."""

import pytest
import sqlalchemy
from sqlalchemy import (
    CheckConstraint,
    Column,
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)

pytest.importorskip("alembic")
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext

from protean.adapters.repository.schema_migrator.autogenerate import (
    _compare,
    _Comparison,
    _copies_table,
    _diff_line,
    _drop_primary_key_nullability,
    _index_names,
    _qualified,
    configure_options,
)

pytestmark = [pytest.mark.sqlite, pytest.mark.no_test_domain]


@pytest.fixture
def metadata():
    metadata = MetaData()
    Table("product", metadata, Column("id", String(36), primary_key=True))
    return metadata


class TestIndexNames:
    def test_reads_the_indexes_of_an_attached_sqlite_schema(self):
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as connection:
            connection.execute(text("ATTACH DATABASE ':memory:' AS shop"))
            connection.execute(text("CREATE TABLE shop.product (name TEXT)"))
            connection.execute(
                text("CREATE INDEX shop.ix_lower_name ON product (lower(name))")
            )

            assert _index_names(connection, "product", "shop") == {"ix_lower_name"}
            assert _index_names(connection, "product", None) == set()


class TestDropPrimaryKeyNullability:
    def test_an_absent_container_is_left_alone(self, metadata):
        _drop_primary_key_nullability(metadata, None)

    def test_a_primary_key_op_that_changes_more_keeps_the_other_change(self, metadata):
        op = ops.AlterColumnOp(
            "product",
            "id",
            modify_nullable=False,
            existing_type=String(36),
            modify_type=String(50),
        )
        container = ops.UpgradeOps(ops=[op])

        _drop_primary_key_nullability(metadata, container)

        assert container.ops == [op]
        assert op.modify_nullable is None
        assert isinstance(op.modify_type, String)

    def test_a_primary_key_op_that_only_changes_nullability_is_removed(self, metadata):
        op = ops.AlterColumnOp("product", "id", modify_nullable=False)
        container = ops.UpgradeOps(ops=[op])

        _drop_primary_key_nullability(metadata, container)

        assert container.ops == []


class TestProcessRevisionDirectives:
    def test_a_script_without_upgrade_ops_is_left_alone(self, metadata):
        script = ops.MigrationScript(rev_id="abc", upgrade_ops=[], downgrade_ops=[])
        directives = [script]

        _Comparison(metadata, None).process_revision_directives(None, None, directives)

        assert directives == [script]


def modify(*children):
    return ops.ModifyTableOps("product", list(children))


class TestCopiesTable:
    def test_a_plain_added_column_or_an_index_change_does_not_copy(self):
        op = modify(
            ops.AddColumnOp("product", Column("stock", Integer)),
            ops.CreateIndexOp("ix_stock", "product", ["stock"]),
            ops.DropIndexOp("ix_old", "product"),
        )

        assert _copies_table(op) is False

    def test_a_changed_column_copies(self):
        assert _copies_table(modify(ops.AlterColumnOp("product", "name"))) is True

    def test_an_added_column_with_an_sql_default_copies(self):
        column = Column("stock", Integer, server_default=text("0"))

        assert _copies_table(modify(ops.AddColumnOp("product", column))) is True

    def test_an_added_column_with_a_literal_default_does_not_copy(self):
        column = Column("stock", Integer, server_default="0")

        assert _copies_table(modify(ops.AddColumnOp("product", column))) is False

    def test_an_added_stored_computed_column_copies(self):
        column = Column("double", Integer, Computed("stock * 2", persisted=True))

        assert _copies_table(modify(ops.AddColumnOp("product", column))) is True

    def test_an_added_virtual_computed_column_does_not_copy(self):
        column = Column("double", Integer, Computed("stock * 2"))

        assert _copies_table(modify(ops.AddColumnOp("product", column))) is False


class TestQualified:
    def test_names_the_schema_of_an_attached_database(self):
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as connection:
            assert _qualified(connection, "ix_name", None) == "ix_name"
            assert _qualified(connection, "ix_name", "shop") == "shop.ix_name"
            assert _qualified(connection, "ix name", "my shop") == '"my shop"."ix name"'


class TestDiffLine:
    @pytest.fixture
    def order(self):
        return Table(
            "order",
            MetaData(),
            Column("id", String(36), primary_key=True),
            Column("name", String(50)),
            Column("customer_id", String(36)),
        )

    def test_a_table(self, order):
        assert _diff_line(("add_table", order)) == "add_table order"

    def test_a_column(self, order):
        diff = ("remove_column", None, "order", order.c.name)

        assert _diff_line(diff) == "remove_column order.name"

    def test_a_column_change_names_the_column(self, order):
        diff = ("modify_type", None, "order", "name", {}, String(50), String(100))

        assert _diff_line(diff) == "modify_type order.name"

    def test_an_index(self, order):
        index = Index("ix_order_name", order.c.name)

        assert _diff_line(("add_index", index)) == "add_index order.ix_order_name"

    def test_a_named_constraint(self, order):
        constraint = UniqueConstraint(order.c.name, name="uq_order_name")
        order.append_constraint(constraint)

        assert (
            _diff_line(("remove_constraint", constraint))
            == "remove_constraint order.uq_order_name"
        )

    def test_an_unnamed_foreign_key(self, order):
        constraint = ForeignKeyConstraint([order.c.customer_id], ["customer.id"])
        order.append_constraint(constraint)

        assert _diff_line(("add_fk", constraint)) == "add_fk order.customer_id"

    def test_an_unnamed_constraint_on_two_columns(self, order):
        constraint = UniqueConstraint(order.c.name, order.c.customer_id)
        order.append_constraint(constraint)

        assert (
            _diff_line(("add_constraint", constraint))
            == "add_constraint order.name,customer_id"
        )

    def test_an_unnamed_constraint_without_columns(self, order):
        constraint = CheckConstraint("length(name) > 0")
        order.append_constraint(constraint)

        assert _diff_line(("add_constraint", constraint)) == "add_constraint order"


class TestCompare:
    """``_compare`` on a SQLite database whose primary key is stored NOT NULL."""

    @pytest.fixture
    def connection(self):
        engine = sqlalchemy.create_engine("sqlite://")
        with engine.connect() as connection:
            connection.execute(
                text(
                    "CREATE TABLE product (id VARCHAR(36) NOT NULL PRIMARY KEY, "
                    "name VARCHAR(50) NOT NULL)"
                )
            )
            yield connection
        engine.dispose()

    def compare(self, connection, metadata):
        context = MigrationContext.configure(
            connection, opts=configure_options(metadata, "sqlite", connection)
        )
        return _compare(context, metadata)

    def test_drops_a_nullability_change_on_the_primary_key(self, connection):
        metadata = MetaData()
        Table(
            "product",
            metadata,
            Column("id", String(36), primary_key=True, nullable=True),
            Column("name", String(50), nullable=False),
        )

        assert self.compare(connection, metadata) == []

    def test_reports_a_nullability_change_on_another_column(self, connection):
        metadata = MetaData()
        Table(
            "product",
            metadata,
            Column("id", String(36), primary_key=True, nullable=True),
            Column("name", String(50), nullable=True),
        )

        assert self.compare(connection, metadata) == ["modify_nullable product.name"]
