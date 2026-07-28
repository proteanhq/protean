"""Unit-of-Work atomicity and read-your-writes guarantees on PostgreSQL.

These pin the guarantees ADR-0027 makes: the Unit of Work is one real database
transaction. Most tests here would fail on the earlier AUTOCOMMIT deferred-write
model (issue #1256), where a mid-UoW flush committed durably, so read-your-writes
was broken and a rolled-back UoW could leave a half-written aggregate.

Two groups of tests live here:

- Red-on-old regression tests (they fail on the AUTOCOMMIT model and pass on the
  fix): read-your-writes for ``filter``/``count``/``exists`` and for an update
  that emits SQL; in-UoW uniqueness; a rolled-back child-bearing UoW leaving no
  orphaned parent; a cross-table commit being atomic; and a pending write staying
  invisible to a separate connection until commit.
- Lock-in tests (they pass on both models and must keep passing): ``get`` after a
  modify (served by the identity map), and the single-childless-aggregate
  rollback/commit cases that were already atomic.

Uses aggregates named ``Register``/``Posting``/``Wallet`` so its tables do not
collide with the shared ``ledger``/``account`` tables other files in this
directory create through the module-autouse ``setup_db`` fixture.
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


class Posting(BaseEntity):
    memo: String(max_length=100, required=False)
    register = Reference("Register")


class Register(BaseAggregate):
    title: String(max_length=100, required=False)
    postings = HasMany(Posting)


class Wallet(BaseAggregate):
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
    domain.register(Register)
    domain.register(Posting, part_of=Register)
    domain.register(Wallet)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    domain.repository_for(Register)._dao
    domain.repository_for(Posting)._dao
    domain.repository_for(Wallet)._dao
    provider._metadata.create_all(provider._engine)
    try:
        with domain.domain_context():
            yield domain
    finally:
        provider._metadata.drop_all(provider._engine)
        provider.close()


def _rows(domain, table: str, where: str = "", params: dict | None = None) -> int:
    """Count rows on a SEPARATE connection from any open UoW, so this reads
    committed state (PostgreSQL MVCC read-committed never blocks on another
    connection's uncommitted rows)."""
    provider = domain.providers["default"]
    with provider._engine.connect() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {table} {where}"), params or {}
        ).scalar()


# ── Read-your-writes inside a Unit of Work ──────────────────────────────────


class TestReadYourWritesInUoW:
    def test_filter_sees_pending_insert(self, uow_domain):
        repo = uow_domain.repository_for(Wallet)
        with UnitOfWork():
            repo.add(Wallet(name="alice", balance=10))
            found = repo._dao.query.filter(name="alice").all()
            assert len(found.items) == 1

    def test_count_sees_pending_insert(self, uow_domain):
        repo = uow_domain.repository_for(Wallet)
        with UnitOfWork():
            repo.add(Wallet(name="bob", balance=1))
            assert repo._dao.query.filter(name="bob").all().total == 1

    def test_exists_sees_pending_insert(self, uow_domain):
        """``exists`` is its own code path (``dao.exists``); pin it directly, both
        the True direction (a pending row is found) and the False direction (an
        absent one is not)."""
        repo = uow_domain.repository_for(Wallet)
        with UnitOfWork():
            repo.add(Wallet(name="eve", balance=1))
            assert repo._dao.exists({}, name="eve") is True
            assert repo._dao.exists({}, name="absent") is False

    def test_filter_sees_pending_update(self, uow_domain):
        """Read-your-writes for an UPDATE that emits SQL. Filtering on the updated
        column forces a query the identity map cannot answer, so on the old
        AUTOCOMMIT model (autoflush off) the DB still holds the old value and this
        returns 0 rows. It is the honest RYW-for-update test (unlike
        ``test_get_sees_pending_update``, which the identity map answers)."""
        repo = uow_domain.repository_for(Wallet)
        acct = Wallet(name="frank", balance=0)
        repo.add(acct)
        with UnitOfWork():
            loaded = repo.get(acct.id)
            loaded.balance = 500
            repo.add(loaded)
            assert repo._dao.query.filter(balance=500).all().total == 1

    def test_get_sees_pending_update(self, uow_domain):
        """Lock-in: ``get`` after modifying an existing aggregate already sees the
        change today, because SQLAlchemy's identity map returns the in-memory
        (modified) object rather than re-reading committed state. This passes on
        both models and must keep passing after ADR-0027."""
        repo = uow_domain.repository_for(Wallet)
        acct = Wallet(name="carol", balance=0)
        repo.add(acct)
        with UnitOfWork():
            loaded = repo.get(acct.id)
            loaded.balance = 500
            repo.add(loaded)
            assert repo.get(acct.id).balance == 500


# ── In-UoW uniqueness validation ────────────────────────────────────────────


class TestInUoWUniqueness:
    def test_second_duplicate_in_same_uow_is_rejected(self, uow_domain):
        repo = uow_domain.repository_for(Wallet)
        with UnitOfWork():
            repo.add(Wallet(name="dup", balance=1))
            with pytest.raises(ValidationError):
                repo.add(Wallet(name="dup", balance=2))


# ── Unit-of-Work atomicity ──────────────────────────────────────────────────


class TestUoWAtomicity:
    def test_single_childless_aggregate_rollback(self, uow_domain):
        """Lock-in: the one case atomic today must stay atomic."""
        repo = uow_domain.repository_for(Wallet)
        uow = UnitOfWork()
        uow.start()
        repo.add(Wallet(name="ephemeral", balance=0))
        uow.rollback()
        assert _rows(uow_domain, "wallet") == 0

    def test_single_childless_aggregate_commit(self, uow_domain):
        """Lock-in: a committed childless aggregate persists."""
        repo = uow_domain.repository_for(Wallet)
        with UnitOfWork():
            repo.add(Wallet(name="kept", balance=7))
        assert _rows(uow_domain, "wallet", "WHERE name = :n", {"n": "kept"}) == 1

    def test_child_bearing_rollback_leaves_no_orphan(self, uow_domain):
        repo = uow_domain.repository_for(Register)
        uow = UnitOfWork()
        uow.start()
        register = Register(title="temp")
        register.add_postings(Posting(memo="p1"))
        repo.add(register)
        uow.rollback()
        assert _rows(uow_domain, "register") == 0
        assert _rows(uow_domain, "posting") == 0

    def test_child_bearing_commit_persists_parent_and_children(self, uow_domain):
        """The positive of the orphan test: a committed child-bearing aggregate
        persists the parent AND its children together."""
        repo = uow_domain.repository_for(Register)
        with UnitOfWork():
            register = Register(title="kept")
            register.add_postings(Posting(memo="a"))
            register.add_postings(Posting(memo="b"))
            repo.add(register)
        assert _rows(uow_domain, "register") == 1
        assert _rows(uow_domain, "posting") == 2

    def test_pending_write_is_isolated_until_commit(self, uow_domain):
        """ADR-0027 finding 1: a pending write is invisible to a SEPARATE
        connection until the UoW commits, and visible after. Uses a child-bearing
        aggregate so the adapter forces a mid-UoW parent flush; on the old
        AUTOCOMMIT model that flush committed durably, so the separate-connection
        read would already see the row before commit (this test goes red there).
        PostgreSQL-only: on MSSQL's lock-based read-committed the separate SELECT
        would block on the uncommitted row rather than return 0."""
        repo = uow_domain.repository_for(Register)
        with UnitOfWork():
            register = Register(title="iso")
            register.add_postings(Posting(memo="x"))
            repo.add(register)  # forces a mid-UoW parent flush
            # Separate connection must NOT see the pending register yet.
            assert _rows(uow_domain, "register") == 0
        # After the with-block commits, it is visible.
        assert _rows(uow_domain, "register") == 1

    def test_cross_table_commit_is_atomic(self, uow_domain):
        """A UoW writing to two tables where one write fails at commit leaves
        neither. This is also the transactional-outbox shape (domain write +
        outbox message in different tables)."""
        provider = uow_domain.providers["default"]
        wallets = uow_domain.repository_for(Wallet)
        anchor = Wallet(name="anchor", balance=0)
        wallets.add(anchor)

        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                # INSERT into ``register`` ...
                uow_domain.repository_for(Register).add(Register(title="L"))
                # ... plus a stale UPDATE on ``wallet`` that fails at the commit
                # flush (bump the DB copy out-of-band so WHERE _version=0 matches 0).
                a = wallets.get(anchor.id)
                a.balance = 9
                wallets.add(a)
                with provider._engine.connect() as other:
                    other.execute(
                        text("UPDATE wallet SET _version = 1 WHERE id = :i"),
                        {"i": anchor.id},
                    )
                    other.commit()

        # Neither table's write from the failed UoW survives: the register INSERT
        # is gone, and the wallet balance did not move to 9.
        assert _rows(uow_domain, "register") == 0
        assert (
            _rows(
                uow_domain, "wallet", "WHERE name = :n AND balance = 9", {"n": "anchor"}
            )
            == 0
        )

    def test_cross_table_commit_persists_both(self, uow_domain):
        """The positive of ``test_cross_table_commit_is_atomic``: a UoW writing to
        two tables that commits cleanly persists both rows (the atomic-outbox
        happy path)."""
        with UnitOfWork():
            uow_domain.repository_for(Register).add(Register(title="L"))
            uow_domain.repository_for(Wallet).add(Wallet(name="both", balance=1))
        assert _rows(uow_domain, "register") == 1
        assert _rows(uow_domain, "wallet", "WHERE name = :n", {"n": "both"}) == 1


# ── Optimistic concurrency surfaced by an in-UoW read ────────────────────────


class TestInUoWOptimisticConcurrency:
    def test_occ_conflict_at_in_uow_read_raises_expected_version_error(
        self, uow_domain
    ):
        """With autoflush on, a read inside a UoW first flushes a pending
        version-guarded UPDATE. If a concurrent commit already advanced the
        version, that flush fails; the read must surface ``ExpectedVersionError``
        (not a raw ``StaleDataError``) so the version-retry path can handle it."""
        provider = uow_domain.providers["default"]
        repo = uow_domain.repository_for(Wallet)
        anchor = Wallet(name="occ", balance=0)
        repo.add(anchor)

        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                loaded = repo.get(anchor.id)
                loaded.balance = 99
                repo.add(loaded)
                # Advance the DB copy out-of-band so the pending WHERE _version=0
                # matches nothing.
                with provider._engine.connect() as other:
                    other.execute(
                        text("UPDATE wallet SET _version = 1 WHERE id = :i"),
                        {"i": anchor.id},
                    )
                    other.commit()
                # A read autoflushes the pending guarded UPDATE, which now conflicts.
                repo._dao.query.filter(balance=99).all()

    def test_occ_conflict_at_in_uow_count_raises_expected_version_error(
        self, uow_domain
    ):
        """Same as the read case, but the conflicting query is a ``count`` (the
        ``_count`` path), which also autoflushes and must translate the conflict."""
        provider = uow_domain.providers["default"]
        repo = uow_domain.repository_for(Wallet)
        anchor = Wallet(name="occ-count", balance=0)
        repo.add(anchor)

        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                loaded = repo.get(anchor.id)
                loaded.balance = 99
                repo.add(loaded)
                with provider._engine.connect() as other:
                    other.execute(
                        text("UPDATE wallet SET _version = 1 WHERE id = :i"),
                        {"i": anchor.id},
                    )
                    other.commit()
                repo._dao.query.filter(balance=99).count()


# ── Reset teardown does not deadlock on a leaked UoW ─────────────────────────


class TestDataResetUnderActiveUoW:
    def test_data_reset_rolls_back_a_dangling_uow_without_deadlock(self, uow_domain):
        """``_data_reset`` rolls back a leaked in-progress UoW before deleting, so a
        UoW holding row locks from a flushed write does not deadlock the reset."""
        provider = uow_domain.providers["default"]
        repo = uow_domain.repository_for(Wallet)
        uow = UnitOfWork()
        uow.start()
        repo.add(Wallet(name="leaked", balance=1))
        # Force a flush so the row (and its lock) exists inside the transaction.
        repo._dao.query.filter(name="leaked").all()

        # Must not block on the lock: it rolls the dangling UoW back first.
        provider._data_reset()

        assert uow.in_progress is False
        assert _rows(uow_domain, "wallet") == 0
