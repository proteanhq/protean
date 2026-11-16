"""A failed commit of a standalone memory operation rolls back, closes the
session, re-raises the commit's own exception, and leaves the store
unchanged."""

import pytest

from protean import UnitOfWork
from protean.adapters.repository.memory import MemorySession
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.infra.dao import DAO
from protean.utils.query import Q


class ExceptionTestEntity(BaseAggregate):
    name: String(max_length=100, required=True)
    value: Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(ExceptionTestEntity)


class FailingSession(MemorySession):
    """A memory session whose commit raises ``error`` when the session holds
    a pending write, and that records each commit, rollback and close."""

    def __init__(self, provider, events, error):
        super().__init__(provider, new_connection=True)
        self.events = events
        self.error = error

    def commit(self):
        if self._db["ops"]:
            self.events.append("commit")
            raise self.error
        super().commit()

    def rollback(self):
        self.events.append("rollback")
        super().rollback()

    def close(self):
        self.events.append("close")
        super().close()


class FailingProvider:
    """Delegates to the real memory provider, and hands out sessions whose
    write commits fail."""

    def __init__(self, provider, error):
        self._provider = provider
        self.error = error
        self.events: list[str] = []

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def new_session(self):
        return FailingSession(self._provider, self.events, self.error)

    def commit(self, session):
        session.commit()

    def rollback(self, session):
        session.rollback()


def _failing_dao(test_domain, error):
    repo = test_domain.repository_for(ExceptionTestEntity)
    provider = FailingProvider(repo._provider, error)
    adapter = repo._provider.dao_for(ExceptionTestEntity, repo._database_model)
    return DAO(test_domain, provider, adapter), provider


def _stored(test_domain):
    dao = test_domain.repository_for(ExceptionTestEntity)._dao
    rows = dao.query.order_by("name").all().items
    return [(row.name, row.value) for row in rows]


def _seed(test_domain, *pairs):
    repo = test_domain.repository_for(ExceptionTestEntity)
    entities = [ExceptionTestEntity(name=name, value=value) for name, value in pairs]
    for entity in entities:
        repo.add(entity)
    return entities


def _write_commit_ends(events):
    """The events of the session whose write commit failed."""
    return events[events.index("commit") :]


def test_failed_insert_commit_rolls_back_and_stores_nothing(test_domain):
    dao, provider = _failing_dao(test_domain, RuntimeError("insert commit error"))

    with pytest.raises(RuntimeError, match="insert commit error"):
        dao.save(ExceptionTestEntity(name="Test", value=100))

    assert _write_commit_ends(provider.events) == ["commit", "rollback", "close"]
    assert _stored(test_domain) == []


def test_failed_update_commit_rolls_back_and_keeps_the_stored_row(test_domain):
    (entity,) = _seed(test_domain, ("Original", 50))
    dao, provider = _failing_dao(test_domain, RuntimeError("update commit error"))
    loaded = dao.get(entity.id)
    loaded.name = "Updated"

    with pytest.raises(RuntimeError, match="update commit error"):
        dao.save(loaded)

    assert _write_commit_ends(provider.events) == ["commit", "rollback", "close"]
    assert _stored(test_domain) == [("Original", 50)]


def test_failed_update_all_commit_rolls_back(test_domain):
    _seed(test_domain, ("Test1", 10), ("Test2", 20))
    dao, provider = _failing_dao(test_domain, RuntimeError("update_all error"))

    with pytest.raises(RuntimeError, match="update_all error"):
        dao.update_all(Q(name="Test1"), {"value": 100})

    assert _write_commit_ends(provider.events) == ["commit", "rollback", "close"]
    assert _stored(test_domain) == [("Test1", 10), ("Test2", 20)]


def test_failed_delete_commit_rolls_back_and_keeps_the_row(test_domain):
    (entity,) = _seed(test_domain, ("ToDelete", 75))
    dao, provider = _failing_dao(test_domain, RuntimeError("delete commit error"))

    with pytest.raises(RuntimeError, match="delete commit error"):
        dao.delete(entity)

    assert _write_commit_ends(provider.events) == ["commit", "rollback", "close"]
    assert _stored(test_domain) == [("ToDelete", 75)]


def test_failed_delete_all_commit_rolls_back(test_domain):
    _seed(test_domain, ("ToDelete1", 10), ("ToDelete2", 20))
    dao, provider = _failing_dao(test_domain, RuntimeError("delete_all error"))

    with pytest.raises(RuntimeError, match="delete_all error"):
        dao.delete_all(Q(name="ToDelete1"))

    assert _write_commit_ends(provider.events) == ["commit", "rollback", "close"]
    assert _stored(test_domain) == [("ToDelete1", 10), ("ToDelete2", 20)]


def test_a_read_commits_normally(test_domain):
    """The failure is tied to pending writes: a read's commit succeeds."""
    _seed(test_domain, ("Read", 1))
    dao, provider = _failing_dao(test_domain, RuntimeError("never raised"))

    assert [row.name for row in dao.query.all().items] == ["Read"]
    assert provider.events == ["close"]


def test_a_write_inside_a_uow_uses_the_uow_session(test_domain):
    """Inside a Unit of Work the provider opens no session, so its failing
    commit is never reached; the Unit of Work commits the write."""
    dao, provider = _failing_dao(test_domain, RuntimeError("never raised"))

    with UnitOfWork():
        dao.save(ExceptionTestEntity(name="UoWTest", value=123))

    assert provider.events == []
    assert _stored(test_domain) == [("UoWTest", 123)]


def test_the_original_exception_is_re_raised(test_domain):
    original = ValueError("Original error message")
    dao, _ = _failing_dao(test_domain, original)

    with pytest.raises(ValueError) as exc:
        dao.save(ExceptionTestEntity(name="Test", value=100))

    assert exc.value is original
