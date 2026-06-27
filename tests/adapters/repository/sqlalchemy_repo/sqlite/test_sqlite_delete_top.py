"""SQLite coverage for ``SqlalchemyDAO._delete_top`` — verifies the
single-statement bounded-delete path is used on a supported dialect and that
unsupported dialects fall back to the portable ``BaseDAO._delete_top``."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.port.dao import BaseDAO
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
    """Record calls into the portable ``BaseDAO._delete_top`` default."""
    calls = []
    original = BaseDAO._delete_top

    def spy(self, criteria, limit, order_by=None):
        calls.append(True)
        return original(self, criteria, limit, order_by)

    monkeypatch.setattr(BaseDAO, "_delete_top", spy)
    return calls


@pytest.mark.sqlite
class TestSqliteDeleteTopDispatch:
    def test_supported_dialect_uses_single_statement_path(
        self, prune_domain, monkeypatch
    ):
        _seed(prune_domain, 5)
        dao = prune_domain.repository_for(Prunable)._dao

        portable_calls = _spy_on_portable_default(monkeypatch)

        deleted = dao._delete_top(Q(), limit=2)

        assert deleted == 2
        assert dao.query.count() == 3
        # SQLite is a bounded-delete dialect: the single-statement override
        # runs and never falls through to the portable default.
        assert portable_calls == []

    def test_unsupported_dialect_falls_back_to_portable_default(
        self, prune_domain, monkeypatch
    ):
        _seed(prune_domain, 5)
        dao = prune_domain.repository_for(Prunable)._dao

        # Pretend this dialect lacks single-statement bounded-delete support.
        monkeypatch.setattr(type(dao), "_BOUNDED_DELETE_DIALECTS", frozenset())
        portable_calls = _spy_on_portable_default(monkeypatch)

        deleted = dao._delete_top(Q(), limit=2)

        assert deleted == 2
        assert dao.query.count() == 3
        assert portable_calls == [True]
