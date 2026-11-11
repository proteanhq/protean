"""Tests for the helpers that adjust what Alembic autogenerate writes."""

import pytest
import sqlalchemy
from sqlalchemy import Column, MetaData, String, Table, text

pytest.importorskip("alembic")
from alembic.operations import ops

from protean.adapters.repository.schema_migrator.autogenerate import (
    _Comparison,
    _drop_primary_key_nullability,
    _index_names,
    _raw_index_names,
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


class TestRawIndexNames:
    def test_a_table_the_metadata_lacks_has_none(self, metadata):
        assert _raw_index_names(metadata, "order") == set()


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
