"""The examples on the indexes guide declare the indexes the page says."""

import pytest

from protean.core.index import RawIndex
from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_customer_declares_a_unique_and_a_plain_index():
    example = load_example("guides/domain-definition/indexes/001.py")
    example.domain.init(traverse=False)

    indexes = example.Customer.meta_.indexes
    assert len(indexes) == 2
    email, status = indexes
    assert email.fields == ("email",)
    assert email.unique is True
    assert status.fields == ("status",)
    assert status.unique is False


def test_customer_unique_email_index_rejects_a_duplicate_on_memory():
    example = load_example("guides/domain-definition/indexes/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Customer)
        repo.add(example.Customer(email="jane@example.com"))
        # A second customer with another email is fine: the status index
        # is not unique, so both rows keep the default "active".
        repo.add(example.Customer(email="john@example.com"))

        with pytest.raises(ValidationError):
            repo.add(example.Customer(email="jane@example.com"))


def test_job_composite_index_sorts_priority_descending():
    example = load_example("guides/domain-definition/indexes/002.py")
    example.domain.init(traverse=False)

    (index,) = example.Job.meta_.indexes
    assert index.fields == ("status", "priority")
    assert index.desc == ("priority",)


def test_task_partial_index_covers_pending_and_failed_rows():
    example = load_example("guides/domain-definition/indexes/003.py")
    example.domain.init(traverse=False)

    (index,) = example.Task.meta_.indexes
    assert index.fields == ("status",)
    assert index.name == "ix_active"
    assert index.where is not None
    assert index.where.children == [("status__in", ["pending", "failed"])]


def test_job_covering_index_includes_priority():
    example = load_example("guides/domain-definition/indexes/004.py")
    example.domain.init(traverse=False)

    (index,) = example.Job.meta_.indexes
    assert index.fields == ("status",)
    assert index.include == ("priority",)
    assert index.name == "ix_status_cover"


def test_line_item_entity_declares_a_unique_sku_index():
    example = load_example("guides/domain-definition/indexes/005.py")
    example.domain.init(traverse=False)

    (index,) = example.LineItem.meta_.indexes
    assert index.fields == ("sku",)
    assert index.unique is True
    assert example.LineItem.meta_.part_of is example.Order


def test_order_summary_projection_declares_two_indexes():
    example = load_example("guides/domain-definition/indexes/006.py")
    example.domain.init(traverse=False)

    indexes = example.OrderSummary.meta_.indexes
    assert [index.fields for index in indexes] == [("status",), ("customer_id",)]


def test_task_reuses_the_shared_active_tasks_index():
    example = load_example("guides/domain-definition/indexes/007.py")
    example.domain.init(traverse=False)

    indexes = example.Task.meta_.indexes
    assert len(indexes) == 2
    active, correlation = indexes
    assert active is example.ACTIVE_TASKS
    assert active.fields == ("status", "priority")
    assert active.desc == ("priority",)
    assert active.name == "ix_active"
    assert correlation.fields == ("correlation_id",)


def test_document_declares_a_postgresql_only_raw_index():
    example = load_example("guides/domain-definition/indexes/008.py")
    example.domain.init(traverse=False)

    (index,) = example.Document.meta_.indexes
    assert isinstance(index, RawIndex)
    assert index.dialect == "postgresql"
    assert "USING gin (data jsonb_path_ops)" in index.ddl
