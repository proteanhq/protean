"""How the ``DAO`` service picks between an adapter's own operation and the
portable one.

A provider flag (``RAW_QUERIES``, ``NATIVE_CLAIM``,
``FILTERED_CLAIM_CANDIDATES``, ``BOUNDED_DELETE``, ``INSERT_IF_ABSENT``)
selects the adapter's operation. Building the service for an adapter class that
does not subclass the matching port raises ``ConfigurationError``. The portable
claim and the portable bounded delete run inside ``claim_lock()``. The portable
``save_if_absent`` checks the key and saves with no lock; only the adapter's
``INSERT_IF_ABSENT`` write runs inside ``claim_lock()``.
"""

import threading
from contextlib import nullcontext, suppress
from types import SimpleNamespace

import pytest

from protean.adapters.repository.elasticsearch import ElasticsearchDAO, ESProvider
from protean.adapters.repository.memory import DictDAO, MemoryProvider, MemorySession
from protean.adapters.repository.sqlalchemy import (
    SADAO,
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
)
from protean.core.aggregate import BaseAggregate
from protean.exceptions import ConfigurationError
from protean.fields import Integer, String
from protean.infra.dao import DAO, _check_flag_ports, portable_claim
from protean.port.dao import DAOPort, HoldBack, NativeClaimPort
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


class BareDAO(DAOPort):
    """An adapter DAO that subclasses none of the optional ports. Its storage
    methods are never reached."""

    def __init__(self, provider, entity_cls, database_model_cls):
        self.provider = provider
        self.entity_cls = entity_cls
        self.database_model_cls = database_model_cls
        self.schema_name = entity_cls.meta_.schema_name


# ABCMeta sets the abstract set when it builds the class, so clear it after.
BareDAO.__abstractmethods__ = frozenset()


class NativeOnlyDAO(BareDAO, NativeClaimPort):
    """An adapter DAO that subclasses only :class:`NativeClaimPort` and records
    each ``claim`` call."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.claims: list[tuple] = []

    def claim(
        self, session, criteria, claim_fields, limit, order_by=(), hold_back=None
    ):
        self.claims.append((criteria, claim_fields, limit, order_by, hold_back))
        return []


NativeOnlyDAO.__abstractmethods__ = frozenset()


def _stub_provider(flags: DatabaseCapabilities) -> SimpleNamespace:
    return SimpleNamespace(name="stub", capabilities=flags)


def _service(test_domain, adapter_cls, flags: DatabaseCapabilities) -> DAO:
    provider = _stub_provider(flags)
    return DAO(test_domain, provider, adapter_cls(provider, Task, None))


HOLD_BY_KEY = HoldBack(
    group_by=("key",),
    applies=Q(key__isnull=False),
    holds=Q(status__in=["ready", "claimed"]),
    order=("seq",),
    lane_of=lambda row: None if row.key is None else 0,
)


class TestMissingPortRaises:
    @pytest.mark.parametrize(
        ("flag", "port_name"),
        [
            (DatabaseCapabilities.RAW_QUERIES, "RawQueryDAOPort"),
            (DatabaseCapabilities.NATIVE_CLAIM, "NativeClaimPort"),
            (DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES, "ClaimCandidatesPort"),
            (DatabaseCapabilities.BOUNDED_DELETE, "BoundedDeletePort"),
            (DatabaseCapabilities.INSERT_IF_ABSENT, "InsertIfAbsentPort"),
        ],
    )
    def test_a_flag_without_its_port(self, test_domain, flag, port_name):
        with pytest.raises(ConfigurationError) as exc:
            _service(test_domain, BareDAO, flag)

        assert str(exc.value) == (
            f"Provider `stub` declares `{flag.name}`, but DAO class `BareDAO` "
            f"does not subclass `{port_name}`"
        )

    def test_the_first_repository_use_raises(self, test_domain):
        repo = test_domain.repository_for(Task)
        provider = repo._provider
        flags = DatabaseCapabilities.NATIVE_CLAIM
        adapter = BareDAO(provider, Task, repo._database_model)
        stub_provider = SimpleNamespace(
            name=provider.name,
            capabilities=flags,
            dao_for=lambda entity_cls, model_cls: adapter,
        )
        repo._provider = stub_provider

        with pytest.raises(ConfigurationError) as exc:
            repo._dao

        assert "NATIVE_CLAIM" in str(exc.value)
        assert "BareDAO" in str(exc.value)

    def test_one_missing_port_among_declared_flags(self, test_domain):
        with pytest.raises(ConfigurationError) as exc:
            _service(
                test_domain,
                NativeOnlyDAO,
                DatabaseCapabilities.NATIVE_CLAIM
                | DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES,
            )

        assert "FILTERED_CLAIM_CANDIDATES" in str(exc.value)
        assert "NativeOnlyDAO" in str(exc.value)
        assert "ClaimCandidatesPort" in str(exc.value)

    def test_no_flags_builds_without_any_port(self, test_domain):
        dao = _service(test_domain, BareDAO, DatabaseCapabilities(0))

        assert isinstance(dao._adapter, BareDAO)

    def test_a_port_without_its_flag_builds(self, test_domain):
        dao = _service(test_domain, NativeOnlyDAO, DatabaseCapabilities(0))

        assert isinstance(dao._adapter, NativeOnlyDAO)

    @pytest.mark.parametrize(
        ("provider_cls", "adapter_cls"),
        [
            (MemoryProvider, DictDAO),
            (PostgresqlProvider, SADAO),
            (SqliteProvider, SADAO),
            (MssqlProvider, SADAO),
            (MysqlProvider, SADAO),
            (ESProvider, ElasticsearchDAO),
        ],
    )
    def test_each_built_in_adapter_has_the_ports_of_its_flags(
        self, provider_cls, adapter_cls
    ):
        # ``capabilities`` reads no instance state, so an uninitialized
        # provider is enough, and no database is reached.
        provider = object.__new__(provider_cls)
        provider.name = provider_cls.__name__
        adapter = object.__new__(adapter_cls)

        assert _check_flag_ports(provider, adapter) is None

    def test_a_non_positive_limit_returns_before_dispatch(self, test_domain):
        dao = _service(test_domain, NativeOnlyDAO, DatabaseCapabilities.NATIVE_CLAIM)

        assert dao.claim(Q(), {"status": "claimed"}, limit=0) == []
        assert dao._adapter.claims == []

    def test_a_native_claim_reaches_the_adapter(self, test_domain):
        dao = _service(test_domain, NativeOnlyDAO, DatabaseCapabilities.NATIVE_CLAIM)
        dao.provider.new_session = lambda: SimpleNamespace(close=lambda: None)
        dao.provider.commit = lambda session: None

        assert dao.claim(Q(status="ready"), {"status": "claimed"}, limit=2) == []
        assert dao._adapter.claims == [
            (Q(status="ready"), {"status": "claimed"}, 2, (), None)
        ]


class TestPortableClaimOrder:
    def test_a_bare_string_order_is_one_key(self, test_domain):
        repo = test_domain.repository_for(Task)
        for seq in (1, 3, 2):
            repo.add(Task(status="ready", seq=seq))

        rows = portable_claim(
            repo._dao, Q(status="ready"), {"status": "claimed"}, 1, "-seq"
        )

        assert [row.seq for row in rows] == [3]


class TestClaimLock:
    def test_the_port_default_claim_lock_is_a_null_context(self, test_domain):
        adapter = BareDAO(_stub_provider(DatabaseCapabilities(0)), Task, None)

        assert isinstance(adapter.claim_lock(), nullcontext)

    def test_memory_claim_lock_is_the_session_lock(self, test_domain):
        adapter = test_domain.repository_for(Task)._dao._adapter
        assert isinstance(adapter, DictDAO)
        provider = adapter.provider

        assert adapter.claim_lock() is provider._locks[provider.name]
        assert adapter.claim_lock() is provider.new_session()._db["lock"]

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
                rows = dao.claim(Q(status="ready"), {"status": "claimed"}, limit=1)
                claimed[idx] = [row.id for row in rows]

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert not any(thread.is_alive() for thread in threads)

        assert sorted(len(ids) for ids in claimed.values()) == [0, 1]
