"""The examples on the indexes reference behave as the page says."""

import pytest

from protean import Index
from protean.core.index import RawIndex
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import String
from tests.docs.support import load_example


def test_declared_indexes_appear_in_meta_in_order():
    example = load_example("reference/domain-elements/indexes/001.py")
    example.domain.init(traverse=False)

    indexes = example.Order.meta_.indexes
    assert len(indexes) == 3
    composite, unique_email, partial = indexes

    assert composite.fields == ("status", "priority")
    assert composite.desc == ("priority",)
    assert composite.unique is False

    assert unique_email.fields == ("email",)
    assert unique_email.unique is True

    assert partial.fields == ("status",)
    assert partial.name == "ix_active"
    assert partial.where.children == [("status__in", ["pending", "failed"])]


def test_names_are_derived_as_the_naming_table_shows():
    example = load_example("reference/domain-elements/indexes/001.py")
    example.domain.init(traverse=False)

    composite, unique_email, partial = example.Order.meta_.indexes
    table = example.Order.meta_.schema_name

    assert table == "order"
    assert composite.resolved_name(table) == "ix_order_status_priority"
    assert unique_email.resolved_name(table) == "uq_order_email"
    assert partial.resolved_name(table) == "ix_active"


def test_memory_provider_enforces_the_unique_index():
    example = load_example("reference/domain-elements/indexes/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Order)
        repo.add(example.Order(email="jane@example.com", status="pending", priority=1))
        # A different email is accepted.
        repo.add(example.Order(email="john@example.com", status="pending", priority=1))

        with pytest.raises(ValidationError):
            repo.add(
                example.Order(email="jane@example.com", status="failed", priority=2)
            )


def test_an_index_on_an_undeclared_field_fails_init():
    example = load_example("reference/domain-elements/indexes/001.py")

    @example.domain.aggregate(indexes=[Index("region")])
    class Shipment:
        status: String(max_length=20)

    with pytest.raises(IncorrectUsageError) as exc:
        example.domain.init(traverse=False)

    assert "region" in str(exc.value)


def test_from_sql_declares_a_raw_index_for_postgresql():
    example = load_example("reference/domain-elements/indexes/002.py")
    example.domain.init(traverse=False)

    indexes = example.Order.meta_.indexes
    assert len(indexes) == 1
    raw = indexes[0]

    assert isinstance(raw, RawIndex)
    assert raw.dialect == "postgresql"
    assert raw.ddl == (
        'CREATE INDEX ix_order_data_gin ON "order" USING gin (data jsonb_path_ops)'
    )


def test_from_sql_rejects_a_misspelled_dialect():
    example = load_example("reference/domain-elements/indexes/002.py")

    @example.domain.aggregate(
        indexes=[Index.from_sql("postgres", "CREATE INDEX ix_a ON audit (data)")]
    )
    class Audit:
        data: String()

    with pytest.raises(IncorrectUsageError) as exc:
        example.domain.init(traverse=False)

    assert "postgres" in str(exc.value)
