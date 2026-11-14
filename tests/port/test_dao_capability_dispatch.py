"""How ``BaseDAO`` picks between an adapter's own claim or bounded-delete
operation and the portable one.

A provider flag (``NATIVE_CLAIM``, ``FILTERED_CLAIM_CANDIDATES``,
``BOUNDED_DELETE``) selects the adapter's operation. A DAO class that does not
subclass the matching port raises ``ConfigurationError`` instead of falling
back. The portable operations run inside ``claim_lock()``.
"""

import threading
from contextlib import nullcontext, suppress
from types import SimpleNamespace

import pytest

from protean.adapters.repository.memory import DictDAO, MemorySession
from protean.core.aggregate import BaseAggregate
from protean.exceptions import ConfigurationError
from protean.fields import Integer, String
from protean.port.dao import BaseDAO, HoldBack
from protean.port.provider import DatabaseCapabilities
from protean.utils.query import Q


class Task(BaseAggregate):
    status = String(max_length=20, default="ready")
    key = String(max_length=20)
    seq = Integer(default=0)


@pytest.fixture(autouse=True)
def setup(test_domain):
    test_domain.register(Task)
    test_domain.init(traverse=False)


class BareDAO(BaseDAO):
    """A DAO that subclasses none of the ports. Its storage methods are never
    reached: dispatch fails first."""


# ABCMeta sets the abstract set when it builds the class, so clear it after.
BareDAO.__abstractmethods__ = frozenset()


def _bare_dao(test_domain, flags: DatabaseCapabilities) -> BareDAO:
    provider = SimpleNamespace(name="stub", capabilities=flags)
    return BareDAO(test_domain, provider, Task, None)


HOLD_BY_KEY = HoldBack(
    group_by=("key",),
    applies=Q(key__isnull=False),
    holds=Q(status__in=["ready", "claimed"]),
    order=("seq",),
    lane_of=lambda row: None if row.key is None else 0,
)


class TestMissingPortRaises:
    def test_native_claim_without_the_port(self, test_domain):
        dao = _bare_dao(test_domain, DatabaseCapabilities.NATIVE_CLAIM)

        with pytest.raises(ConfigurationError) as exc:
            dao._claim(Q(status="ready"), {"status": "claimed"}, limit=1)

        assert "NATIVE_CLAIM" in str(exc.value)
        assert "BareDAO" in str(exc.value)
        assert "NativeClaimPort" in str(exc.value)

    def test_filtered_claim_candidates_without_the_port(self, test_domain):
        dao = _bare_dao(test_domain, DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES)

        with pytest.raises(ConfigurationError) as exc:
            dao._claim(
                Q(status="ready"),
                {"status": "claimed"},
                limit=1,
                hold_back=HOLD_BY_KEY,
            )

        assert "FILTERED_CLAIM_CANDIDATES" in str(exc.value)
        assert "BareDAO" in str(exc.value)
        assert "ClaimCandidatesPort" in str(exc.value)

    def test_bounded_delete_without_the_port(self, test_domain):
        dao = _bare_dao(test_domain, DatabaseCapabilities.BOUNDED_DELETE)

        with pytest.raises(ConfigurationError) as exc:
            dao._delete_top(Q(), limit=1)

        assert "BOUNDED_DELETE" in str(exc.value)
        assert "BareDAO" in str(exc.value)
        assert "BoundedDeletePort" in str(exc.value)

    def test_a_non_positive_limit_returns_before_dispatch(self, test_domain):
        dao = _bare_dao(
            test_domain,
            DatabaseCapabilities.NATIVE_CLAIM | DatabaseCapabilities.BOUNDED_DELETE,
        )

        assert dao._claim(Q(), {"status": "claimed"}, limit=0) == []
        assert dao._delete_top(Q(), limit=0) == 0


class TestClaimLock:
    def test_base_dao_claim_lock_is_a_null_context(self, test_domain):
        dao = _bare_dao(test_domain, DatabaseCapabilities(0))

        assert isinstance(dao.claim_lock(), nullcontext)

    def test_memory_claim_lock_is_the_session_lock(self, test_domain):
        dao = test_domain.repository_for(Task)._dao
        assert isinstance(dao, DictDAO)
        provider = dao.provider

        assert dao.claim_lock() is provider._locks[provider.name]
        assert dao.claim_lock() is dao._get_session()._db["lock"]

    def test_memory_claims_do_not_overlap(self, test_domain, monkeypatch):
        """Two threads claim the same row. Each waits briefly for the other
        between its guarded update's read and its write; ``claim_lock`` keeps
        the second thread out until the first has committed, so only one
        thread claims the row."""
        test_domain.repository_for(Task).add(Task(status="ready"))
        meet = threading.Barrier(2, timeout=0.5)
        write = MemorySession.write

        def write_after_meeting(self, *args, **kwargs):
            with suppress(threading.BrokenBarrierError):
                meet.wait()
            return write(self, *args, **kwargs)

        monkeypatch.setattr(MemorySession, "write", write_after_meeting)
        start = threading.Barrier(2, timeout=10)
        claimed: dict[int, list[str]] = {}

        def worker(idx: int) -> None:
            with test_domain.domain_context():
                dao = test_domain.repository_for(Task)._dao
                start.wait()
                rows = dao._claim(Q(status="ready"), {"status": "claimed"}, limit=1)
                claimed[idx] = [row.id for row in rows]

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert not any(thread.is_alive() for thread in threads)

        assert sorted(len(ids) for ids in claimed.values()) == [0, 1]
