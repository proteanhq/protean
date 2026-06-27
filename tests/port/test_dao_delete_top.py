"""Contract tests for ``BaseDAO._delete_top`` — the bounded-batch delete
primitive that backs batched outbox cleanup.

These run against the in-memory adapter (core suite). The contract is:

- at most ``limit`` matching rows are deleted, and the deleted count is
  returned;
- ``criteria`` restricts which rows are eligible;
- ``order_by`` controls which rows go first;
- ``limit <= 0`` deletes nothing.

Cross-adapter behaviour is covered in ``tests/repository/test_delete_top.py``
and the SQLAlchemy single-statement path in
``tests/adapters/repository/sqlalchemy_repo/``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.port.dao import BaseDAO
from protean.utils.query import Q


class Widget(BaseAggregate):
    status = String(max_length=20, default="active")
    rank = Integer(default=0)


@pytest.fixture(autouse=True)
def setup(test_domain):
    test_domain.register(Widget)
    test_domain.init(traverse=False)
    return test_domain


@pytest.fixture
def dao(test_domain):
    return test_domain.repository_for(Widget)._dao


@pytest.fixture
def seed(test_domain):
    """Factory: insert ``count`` Widgets with the given status."""

    def _seed(count, status="active"):
        repo = test_domain.repository_for(Widget)
        for i in range(count):
            repo.add(Widget(status=status, rank=i))

    return _seed


class TestDeleteTopContract:
    def test_deletes_up_to_limit_and_returns_count(self, dao, seed):
        seed(7)

        deleted = dao._delete_top(Q(), limit=3)

        assert deleted == 3
        assert dao.query.count() == 4

    def test_deletes_fewer_than_limit_when_table_is_small(self, dao, seed):
        seed(2)

        deleted = dao._delete_top(Q(), limit=5)

        assert deleted == 2
        assert dao.query.count() == 0

    def test_criteria_restricts_eligible_rows(self, dao, seed):
        seed(3, status="active")
        seed(4, status="stale")

        deleted = dao._delete_top(Q(status="stale"), limit=10)

        assert deleted == 4
        assert dao.query.count() == 3
        assert all(w.status == "active" for w in dao.query.all().items)

    def test_order_by_controls_which_rows_go_first(self, dao, seed):
        seed(5)  # ranks 0..4

        dao._delete_top(Q(), limit=2, order_by="-rank")

        remaining = sorted(w.rank for w in dao.query.all().items)
        assert remaining == [0, 1, 2]

    def test_limit_zero_or_negative_deletes_nothing(self, dao, seed):
        seed(3)

        assert dao._delete_top(Q(), limit=0) == 0
        assert dao._delete_top(Q(), limit=-1) == 0
        assert dao.query.count() == 3

    def test_no_matches_returns_zero(self, dao, seed):
        seed(3, status="active")

        assert dao._delete_top(Q(status="missing"), limit=5) == 0
        assert dao.query.count() == 3


class TestPortableDefault:
    """The portable ``BaseDAO._delete_top`` (select-ids then delete-by-id) is
    what non-overriding adapters use. Invoke it directly so it is exercised
    even though the memory adapter ships a faster override."""

    def test_portable_default_deletes_bounded_batch(self, dao, seed):
        seed(6)

        # Call the unbound base implementation against the memory DAO.
        deleted = BaseDAO._delete_top(dao, Q(), limit=4)

        assert deleted == 4
        assert dao.query.count() == 2

    def test_portable_default_honours_order_by(self, dao, seed):
        seed(5)  # ranks 0..4

        BaseDAO._delete_top(dao, Q(), limit=2, order_by="-rank")

        remaining = sorted(w.rank for w in dao.query.all().items)
        assert remaining == [0, 1, 2]

    def test_portable_default_limit_zero(self, dao, seed):
        seed(3)

        assert BaseDAO._delete_top(dao, Q(), limit=0) == 0
        assert dao.query.count() == 3

    def test_portable_default_no_matches(self, dao, seed):
        seed(3, status="active")

        assert BaseDAO._delete_top(dao, Q(status="missing"), limit=5) == 0
        assert dao.query.count() == 3

    def test_portable_default_chunks_large_in_clause(self, dao, seed):
        # More ids than fit in one IN clause: the portable path must split the
        # delete into sub-batches (kept under SQLite's 999-variable ceiling).
        seed(1000)

        delete_all_calls = []
        original = dao._delete_all

        def spy(criteria):
            delete_all_calls.append(criteria)
            return original(criteria)

        dao._delete_all = spy

        deleted = BaseDAO._delete_top(dao, Q(), limit=1000)

        assert deleted == 1000
        assert dao.query.count() == 0
        # 1000 ids chunked at 900 → two _delete_all calls.
        assert len(delete_all_calls) == 2
