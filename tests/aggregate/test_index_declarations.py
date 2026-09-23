"""Tests for the portable Index API and ``indexes=`` decorator option.

Covers the Index/RawIndex surface, registration-time validation, and that
declarations land on the element's ``meta_.indexes``. DDL rendering is covered
under tests/adapters; this file is adapter-agnostic.
"""

import pytest

from protean import Index, Q
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.index import RENDERED_INDEX_DIALECTS, RawIndex
from protean.core.projection import BaseProjection
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, Integer, String


class TestIndexAPI:
    def test_index_requires_at_least_one_field(self):
        with pytest.raises(ValueError):
            Index()

    def test_index_stores_fields_and_options(self):
        idx = Index("status", "priority", desc=("priority",), unique=True)
        assert idx.fields == ("status", "priority")
        assert idx.desc == ("priority",)
        assert idx.unique is True
        assert idx.where is None
        assert idx.include == ()

    def test_index_is_frozen(self):
        idx = Index("status")
        with pytest.raises(Exception):
            idx.unique = True  # frozen dataclass

    def test_index_accepts_where_predicate(self):
        q = Q(status__in=["pending", "failed"])
        idx = Index("status", where=q)
        assert idx.where is q

    def test_resolved_name_uses_explicit_name(self):
        assert Index("status", name="ix_custom").resolved_name("job") == "ix_custom"

    def test_resolved_name_derives_for_plain_index(self):
        assert (
            Index("status", "priority").resolved_name("job") == "ix_job_status_priority"
        )

    def test_resolved_name_derives_for_unique_index(self):
        assert Index("sku", unique=True).resolved_name("job") == "uq_job_sku"

    def test_from_sql_returns_raw_index(self):
        raw = Index.from_sql("postgresql", "CREATE INDEX x ON t USING gin (data)")
        assert isinstance(raw, RawIndex)
        assert raw.dialect == "postgresql"
        assert "gin" in raw.ddl


class TestIndexDecoratorOption:
    def test_indexes_stored_on_meta(self, test_domain):
        @test_domain.aggregate(
            indexes=[Index("status", "priority"), Index("message_id", unique=True)]
        )
        class Job(BaseAggregate):
            status = String(max_length=32)
            priority = Integer()
            message_id = String(max_length=64)

        test_domain.init(traverse=False)

        assert len(Job.meta_.indexes) == 2
        assert Job.meta_.indexes[0].fields == ("status", "priority")
        assert Job.meta_.indexes[1].unique is True

    def test_default_is_empty(self, test_domain):
        @test_domain.aggregate
        class Plain(BaseAggregate):
            name = String(max_length=32)

        test_domain.init(traverse=False)
        assert Plain.meta_.indexes == ()

    def test_indexes_supported_on_entities(self, test_domain):
        @test_domain.aggregate
        class Order(BaseAggregate):
            name = String(max_length=32)

        @test_domain.entity(part_of=Order, indexes=[Index("sku", unique=True)])
        class Item(BaseEntity):
            sku = String(max_length=64)

        test_domain.init(traverse=False)
        assert len(Item.meta_.indexes) == 1

    def test_indexes_supported_on_projections(self, test_domain):
        @test_domain.projection(indexes=[Index("status"), Index("ref", unique=True)])
        class OrderView(BaseProjection):
            id = Identifier(identifier=True)
            status = String(max_length=32)
            ref = String(max_length=64)

        test_domain.init(traverse=False)
        assert len(OrderView.meta_.indexes) == 2

    def test_projection_index_validates_fields(self, test_domain):
        @test_domain.projection(indexes=[Index("ghost")])
        class BadView(BaseProjection):
            id = Identifier(identifier=True)
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError, match="unknown"):
            test_domain.init(traverse=False)


class TestIndexValidation:
    """Index declarations are validated during ``Domain.init()`` (after
    reference resolution), via ``DomainValidator``."""

    def test_unknown_field_rejected(self, test_domain):
        @test_domain.aggregate(indexes=[Index("nonexistent")])
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError, match="unknown"):
            test_domain.init(traverse=False)

    def test_desc_must_be_subset_of_fields(self, test_domain):
        @test_domain.aggregate(indexes=[Index("status", desc=("priority",))])
        class Job(BaseAggregate):
            status = String(max_length=32)
            priority = Integer()

        with pytest.raises(IncorrectUsageError, match="desc"):
            test_domain.init(traverse=False)

    def test_unknown_include_field_rejected(self, test_domain):
        @test_domain.aggregate(indexes=[Index("status", include=("ghost",))])
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError, match="include"):
            test_domain.init(traverse=False)

    def test_non_index_entry_rejected(self, test_domain):
        @test_domain.aggregate(indexes=["status"])
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError, match="Index"):
            test_domain.init(traverse=False)

    def test_indexes_must_be_a_list(self, test_domain):
        @test_domain.aggregate(indexes=Index("status"))
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError, match="must be a list"):
            test_domain.init(traverse=False)

    def test_raw_index_is_accepted_without_field_validation(self, test_domain):
        @test_domain.aggregate(
            indexes=[Index.from_sql("postgresql", "CREATE INDEX x ON job (status)")]
        )
        class Job(BaseAggregate):
            status = String(max_length=32)

        test_domain.init(traverse=False)
        assert isinstance(Job.meta_.indexes[0], RawIndex)


class TestRawIndexDialectValidation:
    """A ``RawIndex`` names one dialect. A name the framework cannot render for
    (a typo, or a dialect with no provider) would be dropped silently at every
    call site, so validation rejects it at ``Domain.init()``."""

    def test_misspelt_dialect_rejected(self, test_domain):
        @test_domain.aggregate(
            indexes=[
                Index.from_sql(
                    "postgres",  # typo for "postgresql"
                    "CREATE INDEX ix_job_gin ON job USING gin (data)",
                    name="ix_job_gin",
                )
            ]
        )
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        message = str(exc.value)
        assert "Job" in message  # the element
        assert "ix_job_gin" in message  # the index (name)
        # The whole clause, not a bare "postgres": that substring is already in
        # the allowed "postgresql" the message lists, so a looser assertion
        # would still pass if the message stopped naming the offending value.
        assert "targets unknown dialect 'postgres'." in message

    def test_unknown_dialect_without_a_provider_rejected(self, test_domain):
        @test_domain.aggregate(
            indexes=[
                Index.from_sql("oracle", "CREATE INDEX ix_job_status ON job (status)")
            ]
        )
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        message = str(exc.value)
        assert "Job" in message
        assert "targets unknown dialect 'oracle'." in message
        # With no explicit name, the DDL identifies the index.
        assert "CREATE INDEX ix_job_status ON job (status)" in message

    @pytest.mark.parametrize(
        "dialect",
        sorted(RENDERED_INDEX_DIALECTS),
        # Explicit, non-colliding ids: a bare dialect name as a parametrize id
        # becomes a test keyword, which the suite's db-gate would read as a
        # marker and skip the case (see tests/conftest.py).
        ids=[f"known_{d}" for d in sorted(RENDERED_INDEX_DIALECTS)],
    )
    def test_known_dialect_survives_on_meta(self, test_domain, dialect):
        @test_domain.aggregate(
            indexes=[Index.from_sql(dialect, "CREATE INDEX x ON job (status)")]
        )
        class Job(BaseAggregate):
            status = String(max_length=32)

        test_domain.init(traverse=False)

        raw = Job.meta_.indexes[0]
        assert isinstance(raw, RawIndex)
        assert raw.dialect == dialect

    @pytest.mark.parametrize("dialect", ["PostgreSQL", " postgresql", "postgresql "])
    def test_dialect_matched_by_exact_string(self, test_domain, dialect):
        # Every consumer matches the dialect by exact string, so a name that
        # differs only in case or whitespace renders nothing. Validation rejects
        # it for the same reason it rejects a typo.
        @test_domain.aggregate(
            indexes=[Index.from_sql(dialect, "CREATE INDEX x ON job (status)")]
        )
        class Job(BaseAggregate):
            status = String(max_length=32)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert f"targets unknown dialect '{dialect}'." in str(exc.value)
