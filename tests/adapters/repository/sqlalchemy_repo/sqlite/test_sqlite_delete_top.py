"""SQLite coverage for ``BaseDAO._delete_top`` dispatch: a provider that
declares ``BOUNDED_DELETE`` runs the single-statement ``SADAO.delete_top``,
and one that does not falls back to the portable ``portable_delete_top``."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.port import dao as dao_module
from protean.port.provider import DatabaseCapabilities
from protean.utils.query import Q


class Prunable(BaseAggregate):
    status = String(max_length=20, default="old")
    rank = Integer(default=0)


@pytest.fixture
def prune_domain(test_domain):
    test_domain.register(Prunable)
    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Prunable)._dao
    provider = test_domain.providers["default"]
    provider._metadata.create_all(provider._engine)
    # Start from a clean slate; the table is shared across tests in this module.
    dao._delete_all()
    yield test_domain


def _seed(domain, count):
    repo = domain.repository_for(Prunable)
    for i in range(count):
        repo.add(Prunable(rank=i))


def _spy_on_portable_default(monkeypatch):
    """Record calls into the portable ``portable_delete_top``."""
    calls = []
    original = dao_module.portable_delete_top

    def spy(dao, criteria, limit, order_by=None):
        calls.append(True)
        return original(dao, criteria, limit, order_by)

    monkeypatch.setattr(dao_module, "portable_delete_top", spy)
    return calls


@pytest.mark.sqlite
class TestSqliteDeleteTopDispatch:
    def test_sqlite_declares_bounded_delete(self, prune_domain):
        provider = prune_domain.providers["default"]
        assert DatabaseCapabilities.BOUNDED_DELETE in provider.capabilities

    def test_declared_flag_uses_single_statement_path(self, prune_domain, monkeypatch):
        _seed(prune_domain, 5)
        dao = prune_domain.repository_for(Prunable)._dao

        portable_calls = _spy_on_portable_default(monkeypatch)

        deleted = dao._delete_top(Q(), limit=2, order_by="rank")

        assert deleted == 2
        assert sorted(p.rank for p in dao.query.all().items) == [2, 3, 4]
        assert portable_calls == []

    def test_missing_flag_falls_back_to_portable_default(
        self, prune_domain, monkeypatch
    ):
        _seed(prune_domain, 5)
        dao = prune_domain.repository_for(Prunable)._dao
        provider_cls = type(dao.provider)
        declared = provider_cls.capabilities.fget(dao.provider)

        monkeypatch.setattr(
            provider_cls,
            "capabilities",
            property(lambda self: declared & ~DatabaseCapabilities.BOUNDED_DELETE),
        )
        portable_calls = _spy_on_portable_default(monkeypatch)

        def fail(*args, **kwargs):
            raise AssertionError("delete_top must not run without BOUNDED_DELETE")

        monkeypatch.setattr(dao, "delete_top", fail)

        deleted = dao._delete_top(Q(), limit=2, order_by="rank")

        assert deleted == 2
        assert sorted(p.rank for p in dao.query.all().items) == [2, 3, 4]
        assert portable_calls == [True]
