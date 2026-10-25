"""SQLite coverage for ``_claim``.

SQLite has no row-level locking or ``SKIP LOCKED``; the SQLAlchemy adapter
falls back to the portable :meth:`BaseDAO._claim` default, which is
correct because SQLite serializes writers. These tests assert that fallback
produces correct claims through the SQLAlchemy DAO's ``_filter``/``_update_all``.
"""

import itertools

import pytest

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Auto, DateTime, Integer, String
from protean.port.dao import HoldBack
from protean.utils.query import Q


class ClaimJob(BaseAggregate):
    status = String(max_length=20, default="ready")
    priority = Integer(default=0)
    locked_by = String(max_length=50)
    locked_until = DateTime()


@pytest.fixture
def claim_domain(test_domain):
    test_domain.register(ClaimJob)
    test_domain.init(traverse=False)
    # Accessing the DAO registers ClaimJob's table in the provider metadata,
    # which must happen before create_all(). create_all is idempotent; the
    # autouse data-reset fixture clears rows between tests, so the table is left
    # in place (dropping it here would race that reset's DELETE).
    dao = test_domain.repository_for(ClaimJob)._dao
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    # Start each test from a clean slate — rows persist across tests in this
    # module (the table is shared and not dropped between tests).
    dao._delete_all()
    yield test_domain


def _seed(domain, count, status="ready"):
    repo = domain.repository_for(ClaimJob)
    for i in range(count):
        repo.add(ClaimJob(status=status, priority=i))


@pytest.mark.sqlite
class TestSqliteClaim:
    def test_uses_portable_fallback(self, claim_domain):
        """SQLite dispatches to the portable default rather than SKIP LOCKED."""
        dao = claim_domain.repository_for(ClaimJob)._dao
        assert dao.provider._engine.dialect.name == "sqlite"

    def test_claims_persist_and_skip_already_claimed(self, claim_domain):
        _seed(claim_domain, 4)
        dao = claim_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed", "locked_by": "w1"},
            limit=10,
        )
        assert len(claimed) == 4
        assert all(j.status == "claimed" for j in claimed)

        repo = claim_domain.repository_for(ClaimJob)
        for job in claimed:
            assert repo.get(job.id).status == "claimed"

        assert (
            dao._claim(
                Q(status="ready"), {"status": "claimed", "locked_by": "w2"}, limit=10
            )
            == []
        )

    def test_orders_and_limits(self, claim_domain):
        _seed(claim_domain, 6)
        dao = claim_domain.repository_for(ClaimJob)._dao

        claimed = dao._claim(
            Q(status="ready"),
            {"status": "claimed", "locked_by": "w1"},
            limit=3,
            order_by="-priority",
        )
        assert [j.priority for j in claimed] == [5, 4, 3]

    def test_non_positive_limit_claims_nothing(self, claim_domain):
        _seed(claim_domain, 3)
        dao = claim_domain.repository_for(ClaimJob)._dao

        assert dao._claim(Q(status="ready"), {"status": "claimed"}, 0) == []
        assert dao._claim(Q(status="ready"), {"status": "claimed"}, -1) == []


@pytest.mark.sqlite
class TestSqliteClaimHoldBackWithIntegerIdentity:
    def test_a_lost_claim_on_an_earlier_row_holds_the_rest_of_its_key(
        self, monkeypatch
    ):
        # An integer column hands ``only()`` records an ``int`` id, while the
        # ``Auto`` field gives the entity a ``str`` one.
        ids = itertools.count(1)
        domain = Domain(
            name="IntegerIdentityClaim",
            config={
                "databases": {
                    "default": {
                        "provider": "sqlite",
                        "database_uri": "sqlite:///:memory:",
                    }
                },
                "identity_type": "integer",
                "identity_strategy": "function",
            },
            identity_function=lambda: next(ids),
        )

        @domain.aggregate
        class IntKeyedJob(BaseAggregate):
            job_id: Auto(identifier=True)
            status: String(max_length=20, default="ready")
            key: String(max_length=20)
            seq: Integer(required=True)

        domain.init(traverse=False)
        with domain.domain_context():
            repo = domain.repository_for(IntKeyedJob)
            dao = repo._dao
            provider = domain.providers["default"]
            provider._metadata.create_all(provider._engine)
            head = IntKeyedJob(seq=0, key="k1")
            repo.add(head)
            repo.add(IntKeyedJob(seq=1, key="k1"))
            other = IntKeyedJob(seq=2, key="k2")
            repo.add(other)

            update_all = dao._update_all

            def another_worker_takes_the_head(criteria, values):
                # Another worker claims the head row between this call's read
                # and its guarded update, so the update matches no row.
                if f"('job_id', '{head.job_id}')" in str(criteria):
                    return 0
                return update_all(criteria, values)

            monkeypatch.setattr(dao, "_update_all", another_worker_takes_the_head)

            claimed = dao._claim(
                Q(status="ready"),
                {"status": "claimed"},
                limit=10,
                order_by=["seq"],
                hold_back=HoldBack(
                    group_by=("key",),
                    applies=Q(key__isnull=False),
                    holds=Q(status__in=["ready", "claimed"]),
                    order=("seq",),
                ),
            )

        assert [job.job_id for job in claimed] == [other.job_id]
