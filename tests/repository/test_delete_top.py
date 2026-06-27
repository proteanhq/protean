"""Cross-adapter tests for ``BaseDAO._delete_top`` bounded delete.

Marker-gated so they exercise the SQLAlchemy single-statement path
(PostgreSQL/SQLite/MSSQL) and the Elasticsearch ``delete_by_query`` path in
addition to the in-memory default. Core behaviour is covered against memory in
``tests/port/test_dao_delete_top.py``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.utils.query import Q


class Ticket(BaseAggregate):
    status = String(max_length=20, default="open")
    rank = Integer(default=0)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Ticket)
    test_domain.init(traverse=False)


@pytest.fixture
def seeded_dao(test_domain, db):
    """Seed seven open Tickets and return their DAO.

    Depends on ``db`` so table setup precedes the inserts on SQL adapters.
    """
    repo = test_domain.repository_for(Ticket)
    for i in range(7):
        repo.add(Ticket(status="open", rank=i))
    return repo._dao


@pytest.mark.basic_storage
@pytest.mark.usefixtures("db")
class TestDeleteTopAcrossAdapters:
    def test_bounded_delete_returns_count(self, seeded_dao):
        deleted = seeded_dao._delete_top(Q(), limit=3)

        assert deleted == 3
        assert seeded_dao.query.count() == 4

    def test_drains_table_in_batches(self, seeded_dao):
        total = 0
        while True:
            deleted = seeded_dao._delete_top(Q(), limit=2)
            total += deleted
            if deleted < 2:
                break

        assert total == 7
        assert seeded_dao.query.count() == 0

    def test_criteria_restricts_eligible_rows(self, test_domain, db):
        repo = test_domain.repository_for(Ticket)
        for i in range(3):
            repo.add(Ticket(status="open", rank=i))
        for i in range(4):
            repo.add(Ticket(status="closed", rank=i))

        deleted = repo._dao._delete_top(Q(status="closed"), limit=10)

        assert deleted == 4
        assert repo._dao.query.count() == 3

    def test_order_by_controls_which_rows_go_first(self, seeded_dao):
        seeded_dao._delete_top(Q(), limit=2, order_by="-rank")

        remaining = sorted(t.rank for t in seeded_dao.query.all().items)
        assert remaining == [0, 1, 2, 3, 4]

    def test_limit_zero_or_negative_deletes_nothing(self, seeded_dao):
        assert seeded_dao._delete_top(Q(), limit=0) == 0
        assert seeded_dao._delete_top(Q(), limit=-1) == 0
        assert seeded_dao.query.count() == 7
