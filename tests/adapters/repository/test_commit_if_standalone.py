"""Tests for BaseDAO._commit_if_standalone and _is_standalone.

These tests validate the unified commit/rollback helper that replaces
the boilerplate that was repeated across all adapter DAO implementations.
"""

import pytest
from unittest.mock import MagicMock

from protean import UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.fields import String, Integer


class StandaloneTestEntity(BaseAggregate):
    name: String(max_length=100, required=True)
    value: Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(StandaloneTestEntity)


class TestIsStandalone:
    """Tests for the _is_standalone property."""

    def test_is_standalone_without_uow(self, test_domain):
        """DAO is standalone when there is no active UoW."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        assert dao._is_standalone is True

    def test_is_not_standalone_within_uow(self, test_domain):
        """DAO is not standalone when inside an active UoW."""
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            assert dao._is_standalone is False

    def test_is_standalone_with_outside_uow_flag(self, test_domain):
        """DAO is standalone when _outside_uow is set, even inside UoW."""
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            dao.outside_uow()
            assert dao._is_standalone is True

    def test_is_standalone_with_outside_uow_flag_without_uow(self, test_domain):
        """DAO is standalone when _outside_uow is set and no UoW exists."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        dao.outside_uow()
        assert dao._is_standalone is True


class TestCommitIfStandalone:
    """Tests for the _commit_if_standalone helper method."""

    def test_commits_when_standalone(self, test_domain):
        """Commits and closes the connection when not in a UoW."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        mock_conn = MagicMock()

        dao._commit_if_standalone(mock_conn)

        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
        mock_conn.rollback.assert_not_called()

    def test_skips_commit_within_uow(self, test_domain):
        """Does not commit, rollback, or close when inside a UoW."""
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            mock_conn = MagicMock()

            dao._commit_if_standalone(mock_conn)

            mock_conn.commit.assert_not_called()
            mock_conn.rollback.assert_not_called()
            mock_conn.close.assert_not_called()

    def test_rollbacks_on_commit_failure(self, test_domain):
        """Rolls back and closes on commit failure, re-raises the exception."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        mock_conn = MagicMock()
        original_error = RuntimeError("commit failed")
        mock_conn.commit.side_effect = original_error

        with pytest.raises(RuntimeError, match="commit failed"):
            dao._commit_if_standalone(mock_conn)

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_close_called_even_when_rollback_fails(self, test_domain):
        """Close is called even if rollback also fails."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        mock_conn = MagicMock()
        mock_conn.commit.side_effect = RuntimeError("commit failed")
        mock_conn.rollback.side_effect = RuntimeError("rollback also failed")

        with pytest.raises(RuntimeError, match="rollback also failed"):
            dao._commit_if_standalone(mock_conn)

        mock_conn.close.assert_called_once()

    def test_commits_when_outside_uow_flag_set_inside_uow(self, test_domain):
        """Commits when _outside_uow is set, even inside an active UoW."""
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            dao.outside_uow()
            mock_conn = MagicMock()

            dao._commit_if_standalone(mock_conn)

            mock_conn.commit.assert_called_once()
            mock_conn.close.assert_called_once()


class TestIntegrationWithDAOMethods:
    """Integration tests verifying _commit_if_standalone works correctly
    through actual DAO operations (create, update, delete)."""

    def test_create_commits_without_uow(self, test_domain):
        """Create operation works correctly without UoW."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        dao.create(name="Test", value=42)

        # Verify data was persisted
        results = dao.query.all()
        assert len(results) == 1
        assert results.first.name == "Test"

    def test_update_commits_without_uow(self, test_domain):
        """Update operation works correctly without UoW."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        entity = dao.create(name="Original", value=10)
        dao.update(entity, name="Updated")

        # Verify data was persisted
        result = dao.get(entity.id)
        assert result.name == "Updated"

    def test_delete_commits_without_uow(self, test_domain):
        """Delete operation works correctly without UoW."""
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        entity = dao.create(name="ToDelete", value=99)
        dao.delete(entity)

        # Verify data was removed
        results = dao.query.all()
        assert len(results) == 0

    def test_create_within_uow_defers_commit(self, test_domain):
        """Create within UoW does not commit until UoW commits."""
        with UnitOfWork():
            dao = test_domain.repository_for(StandaloneTestEntity)._dao
            dao.create(name="InUoW", value=55)
            # Data is available within the UoW session
            results = dao.query.all()
            assert len(results) == 1

        # After UoW, data should be committed
        dao = test_domain.repository_for(StandaloneTestEntity)._dao
        results = dao.query.all()
        assert len(results) == 1
