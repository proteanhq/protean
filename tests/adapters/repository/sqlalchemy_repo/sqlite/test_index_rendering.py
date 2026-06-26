"""SQLAlchemy rendering of portable Index declarations (issue #944).

Covers table-level index emission (create_all), partial/unique/desc handling,
the per-dialect ``render_index_ddl`` output, RawIndex escape-hatch emission,
and dialect fallback warnings.
"""

import logging

import pytest
from sqlalchemy import inspect

from protean import Index, Q
from protean.adapters.repository.sqlalchemy import render_index_ddl
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class IndexedJob(BaseAggregate):
    status = String(max_length=32, default="pending")
    priority = Integer(default=0)
    message_id = String(max_length=64)
    correlation_id = String(max_length=64)


JOB_INDEXES = [
    Index(
        "status",
        "priority",
        desc=("priority",),
        where=Q(status__in=["pending", "failed"]),
        name="ix_job_active",
    ),
    Index("message_id", unique=True),
    Index("correlation_id"),
]


@pytest.fixture
def indexed_domain(test_domain):
    test_domain.register(IndexedJob, indexes=JOB_INDEXES)
    test_domain.init(traverse=False)
    # Touch the DAO so the table is registered in the provider metadata before
    # create_all runs.
    test_domain.repository_for(IndexedJob)._dao
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    yield test_domain


@pytest.mark.sqlite
class TestIndexCreation:
    def test_indexes_created_in_database(self, indexed_domain):
        provider = indexed_domain.providers["default"]
        indexed_domain.repository_for(IndexedJob)._dao  # ensure table registered
        insp = inspect(provider._engine)
        names = {i["name"] for i in insp.get_indexes("indexed_job")}
        assert {
            "ix_job_active",
            "ix_indexed_job_correlation_id",
            "uq_indexed_job_message_id",
        } <= names

    def test_unique_flag_emitted(self, indexed_domain):
        provider = indexed_domain.providers["default"]
        insp = inspect(provider._engine)
        by_name = {i["name"]: i for i in insp.get_indexes("indexed_job")}
        assert by_name["uq_indexed_job_message_id"]["unique"] == 1


@pytest.mark.sqlite
class TestRenderIndexDDL:
    def test_sqlite_emits_partial_and_desc(self, test_domain):
        test_domain.register(IndexedJob, indexes=JOB_INDEXES)
        test_domain.init(traverse=False)
        ddl = "\n".join(render_index_ddl(IndexedJob, "sqlite"))
        assert "priority DESC" in ddl
        assert "WHERE status IN ('pending', 'failed')" in ddl
        assert "CREATE UNIQUE INDEX uq_indexed_job_message_id" in ddl

    def test_postgresql_emits_partial_and_include(self, test_domain):
        test_domain.register(
            IndexedJob,
            indexes=[Index("status", include=("priority",), name="ix_cover")],
        )
        test_domain.init(traverse=False)
        ddl = "\n".join(render_index_ddl(IndexedJob, "postgresql"))
        assert "INCLUDE (priority)" in ddl

    def test_mssql_falls_back_for_partial(self, test_domain, caplog):
        test_domain.register(
            IndexedJob,
            indexes=[Index("status", where=Q(status="pending"), name="ix_part")],
        )
        test_domain.init(traverse=False)
        with caplog.at_level(logging.WARNING):
            ddl = "\n".join(render_index_ddl(IndexedJob, "mssql"))
        assert "WHERE" not in ddl
        assert "ix_part" in ddl
        assert any("does not support" in r.message for r in caplog.records)

    def test_raw_index_only_for_matching_dialect(self, test_domain):
        test_domain.register(
            IndexedJob,
            indexes=[
                Index.from_sql("postgresql", "CREATE INDEX gx ON indexed_job (status)")
            ],
        )
        test_domain.init(traverse=False)
        assert render_index_ddl(IndexedJob, "postgresql") == [
            "CREATE INDEX gx ON indexed_job (status)"
        ]
        assert render_index_ddl(IndexedJob, "sqlite") == []

    def test_no_indexes_returns_empty(self, test_domain):
        class Plain(BaseAggregate):
            name = String(max_length=32)

        test_domain.register(Plain)
        test_domain.init(traverse=False)
        assert render_index_ddl(Plain, "postgresql") == []


class TestMergeTableArgs:
    """`__table_args__` may be a dict or a tuple ending in a dict (SQLAlchemy
    table kwargs); the trailing dict must stay last when indexes are appended."""

    def test_empty_returns_indexes(self):
        from protean.adapters.repository.sqlalchemy import _merge_table_args

        assert _merge_table_args(None, ["i1", "i2"]) == ("i1", "i2")

    def test_dict_kept_last(self):
        from protean.adapters.repository.sqlalchemy import _merge_table_args

        opts = {"schema": "reporting"}
        assert _merge_table_args(opts, ["i1"]) == ("i1", opts)

    def test_tuple_ending_in_dict_keeps_dict_last(self):
        from protean.adapters.repository.sqlalchemy import _merge_table_args

        opts = {"schema": "reporting"}
        assert _merge_table_args(("existing", opts), ["i1"]) == (
            "existing",
            "i1",
            opts,
        )

    def test_plain_tuple_appends(self):
        from protean.adapters.repository.sqlalchemy import _merge_table_args

        assert _merge_table_args(("existing",), ["i1"]) == ("existing", "i1")


@pytest.mark.sqlite
class TestPartialIndexPredicate:
    """The where= predicate reuses Q; cover OR, negation, and lookups."""

    def _ddl(self, test_domain, predicate):
        test_domain.register(IndexedJob, indexes=[Index("status", where=predicate)])
        test_domain.init(traverse=False)
        return "\n".join(render_index_ddl(IndexedJob, "sqlite"))

    def test_or_predicate(self, test_domain):
        ddl = self._ddl(test_domain, Q(status="active") | Q(status="pending"))
        assert "WHERE status = 'active' OR status = 'pending'" in ddl

    def test_negated_predicate(self, test_domain):
        ddl = self._ddl(test_domain, ~Q(status="done"))
        assert "WHERE status != 'done'" in ddl

    def test_comparison_lookup(self, test_domain):
        ddl = self._ddl(test_domain, Q(priority__gte=5))
        assert "WHERE priority >= 5" in ddl

    def test_isnull_lookup(self, test_domain):
        ddl = self._ddl(test_domain, Q(locked_by__isnull=True))
        assert "locked_by IS NULL" in ddl

    def test_unsupported_lookup_raises(self, test_domain):
        from protean.exceptions import IncorrectUsageError

        test_domain.register(
            IndexedJob, indexes=[Index("status", where=Q(status__icontains="x"))]
        )
        test_domain.init(traverse=False)
        with pytest.raises(
            IncorrectUsageError, match="not supported in a partial-index"
        ):
            render_index_ddl(IndexedJob, "sqlite")

    def test_sqlite_include_falls_back(self, test_domain, caplog):
        test_domain.register(
            IndexedJob, indexes=[Index("status", include=("priority",), name="ix_c")]
        )
        test_domain.init(traverse=False)
        with caplog.at_level(logging.WARNING):
            ddl = "\n".join(render_index_ddl(IndexedJob, "sqlite"))
        assert "INCLUDE" not in ddl
        assert any("does not support" in r.message for r in caplog.records)
