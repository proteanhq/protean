"""Unit-of-Work atomicity and read-your-writes guarantees on PostgreSQL.

These pin the guarantees ADR-0027 makes: the Unit of Work is one real database
transaction. Every test here would fail on the earlier AUTOCOMMIT deferred-write
model (issue #1256), where a mid-UoW flush committed durably, so read-your-writes
was broken and a rolled-back UoW could leave a half-written aggregate. They cover:

- read-your-writes inside a UoW (``filter``/``count`` see a pending insert, and
  ``get`` after a modify);
- in-UoW uniqueness sees the UoW's own pending write;
- a rolled-back child-bearing UoW leaves no orphaned parent;
- a cross-table commit is atomic (the transactional-outbox shape);
- the single-childless-aggregate cases that already worked still work.
"""

import pytest
from sqlalchemy import text

from protean import Domain, UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import ExpectedVersionError, ValidationError
from protean.fields import HasMany, Integer, Reference, String
from tests.shared import POSTGRES_PORT

# Own Domain per the repo convention; also carries the postgresql marker.
pytestmark = [pytest.mark.postgresql, pytest.mark.no_test_domain]


class Entry(BaseEntity):
    memo: String(max_length=100, required=False)
    ledger = Reference("Ledger")


class Ledger(BaseAggregate):
    title: String(max_length=100, required=False)
    entries = HasMany(Entry)


class Account(BaseAggregate):
    name: String(max_length=50, required=True, unique=True)
    balance: Integer(default=0)


@pytest.fixture
def uow_domain():
    """A postgres domain with its own tables, dropped after each test (which also
    clears any rows a durable-write hole leaked)."""
    domain = Domain(
        name="UoW guarantees",
        config={
            "identity_type": "uuid",
            "databases": {
                "default": {
                    "provider": "postgresql",
                    "database_uri": (
                        f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/postgres"
                    ),
                    "pool_size": 5,
                    "max_overflow": 5,
                }
            },
        },
    )
    domain.register(Ledger)
    domain.register(Entry, part_of=Ledger)
    domain.register(Account)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    domain.repository_for(Ledger)._dao
    domain.repository_for(Entry)._dao
    domain.repository_for(Account)._dao
    provider._metadata.create_all(provider._engine)
    try:
        with domain.domain_context():
            yield domain
    finally:
        provider._metadata.drop_all(provider._engine)
        provider.close()


def _rows(domain, table: str, where: str = "", params: dict | None = None) -> int:
    provider = domain.providers["default"]
    with provider._engine.connect() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {table} {where}"), params or {}
        ).scalar()


# ── Read-your-writes inside a Unit of Work ──────────────────────────────────


class TestReadYourWritesInUoW:
    def test_filter_sees_pending_insert(self, uow_domain):
        repo = uow_domain.repository_for(Account)
        with UnitOfWork():
            repo.add(Account(name="alice", balance=10))
            found = repo._dao.query.filter(name="alice").all()
            assert len(found.items) == 1

    def test_count_sees_pending_insert(self, uow_domain):
        repo = uow_domain.repository_for(Account)
        with UnitOfWork():
            repo.add(Account(name="bob", balance=1))
            assert repo._dao.query.filter(name="bob").all().total == 1

    def test_get_sees_pending_update(self, uow_domain):
        """Lock-in: ``get`` after modifying an existing aggregate already sees the
        change today, because SQLAlchemy's identity map returns the in-memory
        (modified) object rather than re-reading committed state. This is the one
        read-your-writes case that works on the AUTOCOMMIT model (unlike
        ``filter``/``count`` above, which emit SQL and cannot see a pending insert
        without a flush), and it must keep working after ADR-0027."""
        repo = uow_domain.repository_for(Account)
        acct = Account(name="carol", balance=0)
        repo.add(acct)
        with UnitOfWork():
            loaded = repo.get(acct.id)
            loaded.balance = 500
            repo.add(loaded)
            assert repo.get(acct.id).balance == 500


# ── In-UoW uniqueness validation ────────────────────────────────────────────


class TestInUoWUniqueness:
    def test_second_duplicate_in_same_uow_is_rejected(self, uow_domain):
        repo = uow_domain.repository_for(Account)
        with UnitOfWork():
            repo.add(Account(name="dup", balance=1))
            with pytest.raises(ValidationError):
                repo.add(Account(name="dup", balance=2))


# ── Unit-of-Work atomicity ──────────────────────────────────────────────────


class TestUoWAtomicity:
    def test_single_childless_aggregate_rollback(self, uow_domain):
        """Lock-in: the one case atomic today must stay atomic."""
        repo = uow_domain.repository_for(Account)
        uow = UnitOfWork()
        uow.start()
        repo.add(Account(name="ephemeral", balance=0))
        uow.rollback()
        assert _rows(uow_domain, "account") == 0

    def test_single_childless_aggregate_commit(self, uow_domain):
        """Lock-in: a committed childless aggregate persists."""
        repo = uow_domain.repository_for(Account)
        with UnitOfWork():
            repo.add(Account(name="kept", balance=7))
        assert _rows(uow_domain, "account", "WHERE name = :n", {"n": "kept"}) == 1

    def test_child_bearing_rollback_leaves_no_orphan(self, uow_domain):
        repo = uow_domain.repository_for(Ledger)
        uow = UnitOfWork()
        uow.start()
        ledger = Ledger(title="temp")
        ledger.add_entries(Entry(memo="e1"))
        repo.add(ledger)
        uow.rollback()
        assert _rows(uow_domain, "ledger") == 0
        assert _rows(uow_domain, "entry") == 0

    def test_cross_table_commit_is_atomic(self, uow_domain):
        """A UoW writing to two tables where one write fails at commit leaves
        neither. This is also the transactional-outbox shape (domain write +
        outbox message in different tables)."""
        provider = uow_domain.providers["default"]
        accounts = uow_domain.repository_for(Account)
        anchor = Account(name="anchor", balance=0)
        accounts.add(anchor)

        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                # INSERT into ``ledger`` ...
                uow_domain.repository_for(Ledger).add(Ledger(title="L"))
                # ... plus a stale UPDATE on ``account`` that fails at the commit
                # flush (bump the DB copy out-of-band so WHERE _version=0 matches 0).
                a = accounts.get(anchor.id)
                a.balance = 9
                accounts.add(a)
                with provider._engine.connect() as other:
                    other.execute(
                        text("UPDATE account SET _version = 1 WHERE id = :i"),
                        {"i": anchor.id},
                    )
                    other.commit()

        # The ledger INSERT must not survive the failed commit.
        assert _rows(uow_domain, "ledger") == 0
