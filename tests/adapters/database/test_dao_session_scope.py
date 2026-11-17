"""Tests for ``DAO.session_scope``: the one place a standalone operation's
session is opened, committed or rolled back, and closed.

The adapter DAO reads and writes in the session it is given and never commits.
The service picks the session: the Unit of Work's inside one, else a new one
from the provider that it ends itself.
"""

import pytest

from protean import UnitOfWork
from protean.adapters.database.memory import MemorySession
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String
from protean.infra.dao import DAO


class StandaloneTestEntity(BaseAggregate):
    name: String(max_length=100, required=True)
    value: Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(StandaloneTestEntity)


class RecordingSession(MemorySession):
    """A memory session that records when it is committed, rolled back or
    closed."""

    def __init__(self, provider, events, fail_commit=False):
        super().__init__(provider, new_connection=True)
        self.events = events
        self.fail_commit = fail_commit

    def commit(self):
        self.events.append("commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")
        super().commit()

    def rollback(self):
        self.events.append("rollback")
        super().rollback()

    def close(self):
        self.events.append("close")
        super().close()


class RecordingProvider:
    """Delegates to the real memory provider, and hands out recording
    sessions."""

    def __init__(self, provider, fail_commit=False):
        self._provider = provider
        self.events: list[str] = []
        self.sessions: list[RecordingSession] = []
        self.fail_commit = fail_commit

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def new_session(self):
        session = RecordingSession(self._provider, self.events, self.fail_commit)
        self.sessions.append(session)
        return session

    def commit(self, session):
        session.commit()

    def rollback(self, session):
        session.rollback()


def _recording_dao(test_domain, fail_commit=False):
    repo = test_domain.repository_for(StandaloneTestEntity)
    provider = RecordingProvider(repo._provider, fail_commit=fail_commit)
    adapter = repo._provider.dao_for(StandaloneTestEntity, repo._database_model)
    return DAO(test_domain, provider, adapter), provider


class TestIsStandalone:
    def test_is_standalone_without_uow(self, test_domain):
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        assert dao._is_standalone is True

    def test_is_not_standalone_within_uow(self, test_domain):
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            assert dao._is_standalone is False

    def test_is_standalone_with_outside_uow_flag(self, test_domain):
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            dao.outside_uow()
            assert dao._is_standalone is True


class TestSessionScope:
    def test_standalone_commits_then_closes_a_new_session(self, test_domain):
        dao, provider = _recording_dao(test_domain)

        with dao.session_scope() as session:
            assert session is provider.sessions[0]

        assert provider.events == ["commit", "close"]

    def test_standalone_rolls_back_and_closes_when_the_block_raises(self, test_domain):
        dao, provider = _recording_dao(test_domain)

        with pytest.raises(ValueError, match="block failed"):
            with dao.session_scope():
                raise ValueError("block failed")

        assert provider.events == ["rollback", "close"]

    def test_standalone_rolls_back_and_closes_when_the_commit_raises(self, test_domain):
        dao, provider = _recording_dao(test_domain, fail_commit=True)

        with pytest.raises(RuntimeError, match="commit failed"):
            with dao.session_scope():
                pass

        assert provider.events == ["commit", "rollback", "close"]

    def test_inside_a_uow_yields_its_session_and_ends_nothing(self, test_domain):
        dao, provider = _recording_dao(test_domain)

        with UnitOfWork() as uow:
            with dao.session_scope() as session:
                assert session is uow.get_session(provider.name)

        assert provider.sessions == []
        assert provider.events == []

    def test_outside_uow_inside_a_uow_commits_its_own_session(self, test_domain):
        dao, provider = _recording_dao(test_domain)

        with UnitOfWork() as uow:
            dao.outside_uow()
            with dao.session_scope() as session:
                assert session is provider.sessions[0]
                assert session is not uow.get_session(provider.name)

        assert provider.events == ["commit", "close"]

    def test_each_standalone_step_of_a_save_commits_its_own_session(self, test_domain):
        dao, provider = _recording_dao(test_domain)

        dao.create(name="Test", value=42)

        assert provider.sessions
        assert provider.events == ["commit", "close"] * len(provider.sessions)
        stored = test_domain.repository_for(StandaloneTestEntity)._dao.query.all()
        assert [item.name for item in stored.items] == ["Test"]


class TestIntegrationWithDAOMethods:
    def test_update_commits_without_uow(self, test_domain):
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        entity = dao.create(name="Original", value=10)
        dao.update(entity, name="Updated")

        assert dao.get(entity.id).name == "Updated"

    def test_delete_commits_without_uow(self, test_domain):
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        entity = dao.create(name="ToDelete", value=99)
        dao.delete(entity)

        assert dao.query.all().items == []

    def test_create_within_uow_commits_with_the_uow(self, test_domain):
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            dao.create(name="InUoW", value=55)
            assert len(dao.query.all()) == 1

        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        assert [item.name for item in dao.query.all().items] == ["InUoW"]
