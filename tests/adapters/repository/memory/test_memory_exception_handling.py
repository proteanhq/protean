"""Test Memory Provider exception handling during database operations"""

import pytest
from unittest.mock import patch, MagicMock

from protean import UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.exceptions import DatabaseError
from protean.utils.query import Q


class ExceptionTestEntity(BaseAggregate):
    name: str
    value: int | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(ExceptionTestEntity)


def test_create_operation_exception_handling_without_uow(test_domain):
    """Test exception handling during create operation when not in UoW"""
    dao = test_domain.repository_for(ExceptionTestEntity)._dao

    # Create a test entity
    entity = ExceptionTestEntity(name="Test", value=100)
    model_dict = dao.database_model_cls.from_entity(entity)

    # Mock the session's commit method to raise an exception
    with patch.object(dao, "_get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session._db = {
            "data": {"exception_test_entity": {}},
            "lock": MagicMock(),
            "counters": {},
        }
        mock_get_session.return_value = mock_session

        # Make commit raise an exception
        mock_session.commit.side_effect = Exception("Simulated commit error")

        # This should trigger the exception handling in _create
        with pytest.raises(DatabaseError) as exc_info:
            dao._create(model_dict)

        # Verify the exception was properly handled
        assert "Database error during creation" in str(exc_info.value)
        assert "Simulated commit error" in str(exc_info.value)

        # Verify rollback was called
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


def test_update_operation_exception_handling_without_uow(test_domain):
    """Test exception handling during update operation when not in UoW"""
    # First create an entity
    entity = ExceptionTestEntity(name="Original", value=50)
    test_domain.repository_for(ExceptionTestEntity).add(entity)

    dao = test_domain.repository_for(ExceptionTestEntity)._dao

    # Update the entity
    entity.name = "Updated"
    model_dict = dao.database_model_cls.from_entity(entity)

    # Mock the session's commit method to raise an exception
    with patch.object(dao, "_get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session._db = {
            "data": {"exception_test_entity": {entity.id: model_dict}},
            "lock": MagicMock(),
        }
        mock_get_session.return_value = mock_session

        # Make commit raise an exception
        mock_session.commit.side_effect = Exception("Simulated update commit error")

        # This should trigger the exception handling in _update
        with pytest.raises(DatabaseError) as exc_info:
            dao._update(model_dict)

        # Verify the exception was properly handled
        assert "Database error during update" in str(exc_info.value)
        assert "Simulated update commit error" in str(exc_info.value)

        # Verify rollback was called
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


def test_update_all_operation_exception_handling_without_uow(test_domain):
    """Test exception handling during update_all operation when not in UoW"""
    # Create test entities
    entity1 = ExceptionTestEntity(name="Test1", value=10)
    entity2 = ExceptionTestEntity(name="Test2", value=20)
    test_domain.repository_for(ExceptionTestEntity).add(entity1)
    test_domain.repository_for(ExceptionTestEntity).add(entity2)

    dao = test_domain.repository_for(ExceptionTestEntity)._dao

    # Mock the session's commit method to raise an exception
    with patch.object(dao, "_get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session._db = {
            "data": {
                "exception_test_entity": {
                    entity1.id: {"id": entity1.id, "name": "Test1", "value": 10},
                    entity2.id: {"id": entity2.id, "name": "Test2", "value": 20},
                }
            },
            "lock": MagicMock(),
        }
        mock_get_session.return_value = mock_session

        # Mock _filter_items to return some items
        with patch.object(dao, "_filter_items") as mock_filter:
            mock_filter.return_value = {
                entity1.id: {"id": entity1.id, "name": "Test1", "value": 10}
            }

            # Make commit raise an exception
            mock_session.commit.side_effect = Exception(
                "Simulated update_all commit error"
            )

            # This should trigger the exception handling in _update_all
            with pytest.raises(DatabaseError) as exc_info:
                dao._update_all(Q(name="Test1"), value=100)

            # Verify the exception was properly handled
            assert "Database error during update_all" in str(exc_info.value)
            assert "Simulated update_all commit error" in str(exc_info.value)

            # Verify rollback was called
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()


def test_delete_operation_exception_handling_without_uow(test_domain):
    """Test exception handling during delete operation when not in UoW"""
    # Create an entity
    entity = ExceptionTestEntity(name="ToDelete", value=75)
    test_domain.repository_for(ExceptionTestEntity).add(entity)

    dao = test_domain.repository_for(ExceptionTestEntity)._dao
    model_dict = dao.database_model_cls.from_entity(entity)

    # Mock the session's commit method to raise an exception
    with patch.object(dao, "_get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session._db = {
            "data": {"exception_test_entity": {entity.id: model_dict}},
            "lock": MagicMock(),
        }
        mock_get_session.return_value = mock_session

        # Make commit raise an exception
        mock_session.commit.side_effect = Exception("Simulated delete commit error")

        # This should trigger the exception handling in _delete
        with pytest.raises(DatabaseError) as exc_info:
            dao._delete(model_dict)

        # Verify the exception was properly handled
        assert "Database error during deletion" in str(exc_info.value)
        assert "Simulated delete commit error" in str(exc_info.value)

        # Verify rollback was called
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()


def test_delete_all_operation_exception_handling_without_uow(test_domain):
    """Test exception handling during delete_all operation when not in UoW"""
    # Create test entities
    entity1 = ExceptionTestEntity(name="ToDelete1", value=10)
    entity2 = ExceptionTestEntity(name="ToDelete2", value=20)
    test_domain.repository_for(ExceptionTestEntity).add(entity1)
    test_domain.repository_for(ExceptionTestEntity).add(entity2)

    dao = test_domain.repository_for(ExceptionTestEntity)._dao

    # Mock the session's commit method to raise an exception
    with patch.object(dao, "_get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session._db = {
            "data": {
                "exception_test_entity": {
                    entity1.id: {"id": entity1.id, "name": "ToDelete1", "value": 10},
                    entity2.id: {"id": entity2.id, "name": "ToDelete2", "value": 20},
                }
            },
            "lock": MagicMock(),
        }
        mock_get_session.return_value = mock_session

        # Mock _filter_items to return some items
        with patch.object(dao, "_filter_items") as mock_filter:
            mock_filter.return_value = {
                entity1.id: {"id": entity1.id, "name": "ToDelete1", "value": 10}
            }

            # Make commit raise an exception
            mock_session.commit.side_effect = Exception(
                "Simulated delete_all commit error"
            )

            # This should trigger the exception handling in _delete_all
            with pytest.raises(DatabaseError) as exc_info:
                dao._delete_all(Q(name="ToDelete1"))

            # Verify the exception was properly handled
            assert "Database error during delete_all" in str(exc_info.value)
            assert "Simulated delete_all commit error" in str(exc_info.value)

            # Verify rollback was called
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()


def test_operations_within_uow_do_not_trigger_exception_handling(test_domain):
    """Test that operations within UoW do not trigger the exception handling paths"""
    with UnitOfWork():
        dao = test_domain.repository_for(ExceptionTestEntity)._dao

        # Mock session to raise exception on commit
        with patch.object(dao, "_get_session") as mock_get_session:
            mock_session = MagicMock()
            mock_session._db = {
                "data": {"exception_test_entity": {}},
                "lock": MagicMock(),
                "counters": {},
            }
            mock_get_session.return_value = mock_session

            # Make commit raise an exception
            mock_session.commit.side_effect = Exception("Should not be called in UoW")

            # Create entity within UoW - should not trigger exception handling
            entity = ExceptionTestEntity(name="UoWTest", value=123)
            model_dict = dao.database_model_cls.from_entity(entity)

            # This should NOT raise an exception because we're in UoW
            result = dao._create(model_dict)

            # Verify commit was not called (because we're in UoW)
            mock_session.commit.assert_not_called()
            mock_session.rollback.assert_not_called()
            mock_session.close.assert_not_called()

            # Verify the model was returned
            assert result is not None


def test_exception_preserves_original_exception_details(test_domain):
    """Test that DatabaseError preserves original exception information"""
    dao = test_domain.repository_for(ExceptionTestEntity)._dao

    # Create a test entity
    entity = ExceptionTestEntity(name="Test", value=100)
    model_dict = dao.database_model_cls.from_entity(entity)

    # Custom exception with specific details
    original_exception = ValueError("Original error message")

    with patch.object(dao, "_get_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session._db = {
            "data": {"exception_test_entity": {}},
            "lock": MagicMock(),
            "counters": {},
        }
        mock_get_session.return_value = mock_session
        mock_session.commit.side_effect = original_exception

        with pytest.raises(DatabaseError) as exc_info:
            dao._create(model_dict)

        # Verify the original exception is preserved
        assert exc_info.value.original_exception is original_exception
        assert "Original error message" in str(exc_info.value)
