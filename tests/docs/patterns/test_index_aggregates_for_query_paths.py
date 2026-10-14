"""Run the examples on ``docs/patterns/index-aggregates-for-query-paths.md``."""

import pytest

from protean import Domain, Index, Q
from protean.exceptions import IncorrectUsageError
from protean.fields import String
from protean.utils.outbox import OUTBOX_INDEXES
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def outbox():
    example = load_example("patterns/index-aggregates-for-query-paths/001.py")
    with example.domain.domain_context():
        yield example


@pytest.fixture
def tickets():
    example = load_example("patterns/index-aggregates-for-query-paths/002.py")
    with example.domain.domain_context():
        yield example


def by_fields(indexes):
    return {index.fields: index for index in indexes}


class TestOutboxIndexes:
    def test_the_decorator_stores_the_declared_indexes(self, outbox):
        indexes = outbox.Outbox.meta_.indexes
        assert indexes == [
            Index(
                "status",
                "priority",
                desc=("priority",),
                where=Q(status__in=["pending", "failed"]),
                name="ix_active",
            ),
            Index("message_id", unique=True),
            Index("correlation_id"),
        ]

    def test_the_polling_index_is_partial_and_sorts_priority_descending(self, outbox):
        active = by_fields(outbox.Outbox.meta_.indexes)[("status", "priority")]
        assert active.name == "ix_active"
        assert active.desc == ("priority",)
        assert active.where == Q(status__in=["pending", "failed"])
        assert active.unique is False

    def test_only_message_id_is_unique(self, outbox):
        indexes = by_fields(outbox.Outbox.meta_.indexes)
        assert indexes
        assert indexes[("message_id",)].unique is True
        assert indexes[("correlation_id",)].unique is False
        assert indexes[("correlation_id",)].where is None

    def test_the_framework_outbox_differs_only_where_the_page_says(self, outbox):
        page = by_fields(outbox.Outbox.meta_.indexes)
        framework = by_fields(OUTBOX_INDEXES)

        polling = framework[("status", "priority")]
        assert polling.name == "ix_outbox_active"
        assert polling.desc == page[("status", "priority")].desc
        assert polling.where == page[("status", "priority")].where

        assert framework[("correlation_id",)] == page[("correlation_id",)]

        assert ("message_id",) not in framework
        assert framework[("message_id", "target_broker")].unique is True


class TestTicketIndexes:
    def test_each_access_path_has_its_index(self, tickets):
        indexes = by_fields(tickets.Ticket.meta_.indexes)
        assert set(indexes) == {
            ("email",),
            ("organization_id",),
            ("status", "created_at"),
        }

        assert indexes[("email",)].unique is True
        assert indexes[("organization_id",)].unique is False

        open_tickets = indexes[("status", "created_at")]
        assert open_tickets.name == "ix_open"
        assert open_tickets.desc == ("created_at",)
        assert open_tickets.where == Q(status="open")
        assert open_tickets.unique is False


class TestIndexValidation:
    def test_an_aggregate_without_indexes_declares_none(self):
        domain = Domain(name="NoIndexes")

        @domain.aggregate
        class Plain:
            name = String()

        domain.init(traverse=False)
        assert Plain.meta_.indexes == ()

    def test_an_index_on_an_undeclared_field_is_rejected_at_init(self):
        domain = Domain(name="UnknownIndexField")

        @domain.aggregate(indexes=[Index("status", "priority")])
        class Outbox:
            status = String()

        with pytest.raises(
            IncorrectUsageError, match=r"unknown field\(s\) \['priority'\]"
        ):
            domain.init(traverse=False)

    def test_a_desc_field_outside_the_index_is_rejected_at_init(self):
        domain = Domain(name="BadDescField")

        @domain.aggregate(indexes=[Index("status", desc=("created_at",))])
        class Ticket:
            status = String()
            created_at = String()

        with pytest.raises(IncorrectUsageError, match="desc field"):
            domain.init(traverse=False)
