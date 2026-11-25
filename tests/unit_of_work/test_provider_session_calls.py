"""The Unit of Work flushes, commits and rolls back each session through the
session's provider, so a provider's translation of a version conflict and its
``occ_trace`` records apply to a Unit of Work's sessions too."""

import pytest

from protean import UnitOfWork
from protean.adapters.database.memory import MemoryDatabase
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Ledger(BaseAggregate):
    name = String(max_length=50)


class Counter(BaseAggregate):
    value = Integer(default=0)


@pytest.fixture
def calls(test_domain, monkeypatch):
    """Record each provider-level ``flush``, ``commit`` and ``rollback`` as
    ``(method, provider name, session)``, then run the real method."""
    recorded: list[tuple[str, str, object]] = []

    def recording(method_name):
        real = getattr(MemoryDatabase, method_name)

        def wrapper(self, session):
            recorded.append((method_name, self.name, session))
            return real(self, session)

        return wrapper

    for method_name in ("flush", "commit", "rollback"):
        monkeypatch.setattr(MemoryDatabase, method_name, recording(method_name))
    return recorded


@pytest.fixture
def two_providers(test_domain):
    test_domain.config["databases"]["secondary"] = {"provider": "memory"}
    test_domain._initialize()
    test_domain.register(Ledger)
    test_domain.register(Counter, database="secondary")
    test_domain.init(traverse=False)
    return test_domain


def test_a_commit_flushes_then_commits_each_session_once_through_its_provider(
    two_providers, calls
):
    with UnitOfWork() as uow:
        two_providers.repository_for(Ledger).add(Ledger(name="Cash"))
        two_providers.repository_for(Counter).add(Counter(value=1))
        sessions = dict(uow._sessions)

    assert sorted(sessions) == ["default", "secondary"]
    uow_calls = [call for call in calls if call[2] in sessions.values()]
    assert [(method, name) for method, name, _ in uow_calls] == [
        ("flush", "default"),
        ("flush", "secondary"),
        ("commit", "default"),
        ("commit", "secondary"),
    ]
    for method, name, session in uow_calls:
        assert session is sessions[name], method


def test_a_rollback_rolls_back_each_session_once_through_its_provider(
    two_providers, calls
):
    with pytest.raises(RuntimeError, match="handler failed"):
        with UnitOfWork() as uow:
            two_providers.repository_for(Ledger).add(Ledger(name="Cash"))
            two_providers.repository_for(Counter).add(Counter(value=1))
            sessions = dict(uow._sessions)
            raise RuntimeError("handler failed")

    uow_calls = [call for call in calls if call[2] in sessions.values()]
    assert sorted((method, name) for method, name, _ in uow_calls) == [
        ("rollback", "default"),
        ("rollback", "secondary"),
    ]
    assert two_providers.repository_for(Ledger)._dao.query.all().items == []


def test_the_memory_provider_flush_reaches_the_session_flush(test_domain):
    test_domain.register(Ledger)
    test_domain.init(traverse=False)
    provider = test_domain.repository_for(Ledger)._dao.provider
    session = provider.get_session()

    provider.flush(session)
    try:
        assert session._db["flush_held"] is True
    finally:
        provider.rollback(session)
    assert session._db["flush_held"] is False
